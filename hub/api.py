"""FastAPI application for the agent hub."""

import asyncio
import contextlib
import json
import os
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from hub import agents, memory, ollama, obsidian, providers, remote, skills
from hub.config import load_config, save_config, set_primary_bot, validate_name
from hub.runner import (
    run_agent,
    stop_run,
    get_run,
    list_runs,
    agent_status,
    recover_stale_runs,
)
from hub import coordinator
from hub import routines as routines_engine

security = HTTPBearer(auto_error=False)

# Rate limiting for authentication failures
_auth_failure_store: Dict[str, List[float]] = {}
_auth_failure_lock = threading.Lock()
_AUTH_MAX_FAILURES = 10
_AUTH_WINDOW_SECONDS = 60

def _check_auth_rate_limit(client_ip: str) -> None:
    """Rate limit authentication failures per IP address.
    
    Raises HTTPException 429 if too many failures in the time window.
    """
    now = time.time()
    with _auth_failure_lock:
        if client_ip not in _auth_failure_store:
            _auth_failure_store[client_ip] = []
        # Remove old entries outside the window
        failures = _auth_failure_store[client_ip]
        _auth_failure_store[client_ip] = [t for t in failures if now - t < _AUTH_WINDOW_SECONDS]
        failures = _auth_failure_store[client_ip]
        if len(failures) >= _AUTH_MAX_FAILURES:
            raise HTTPException(
                status_code=429, 
                detail="Too many authentication failures. Try again later."
            )

def _record_auth_failure(client_ip: str) -> None:
    """Record an authentication failure for rate limiting."""
    now = time.time()
    with _auth_failure_lock:
        if client_ip not in _auth_failure_store:
            _auth_failure_store[client_ip] = []
        _auth_failure_store[client_ip].append(now)


# Static files directory
_STATIC_DIR = Path(__file__).resolve().parent / "static"

# SSE event store: maps run_id -> SSERunStore (append-only, bounded).
# Each client reads from the store via its own last event ID cursor, so
# multiple clients get independent ordered streams that survive evictions.
_sse_event_store: Dict[str, "SSERunStore"] = {}
_sse_event_store_lock = threading.Lock()
# Max events per run to prevent unbounded memory growth
_SSE_MAX_EVENTS = 1000
# Terminal events that must never be silently dropped
_TERMINAL_EVENTS = {"complete", "error", "end"}
# Global monotonically increasing event ID counter (across all runs)
_sse_next_id: int = 0


class SSERunStore:
    """Bounded, append-only event store for one run.

    Each event carries a monotonically increasing ID so clients can track
    their position independently of list indices.  When the buffer is full,
    the oldest non-terminal events are evicted and the store records the
    highest evicted ID so reconnecting clients can detect a retention gap.
    """

    __slots__ = ("events", "evicted_before_id")

    def __init__(self) -> None:
        # List of tuples: (event_id: int, sse_string: str)
        self.events: list = []
        # If events were evicted, this holds the highest event ID that was
        # evicted so far.  A client whose cursor (last_event_id) is less
        # than this value knows it missed at least one event.  None means
        # no eviction has occurred.
        self.evicted_before_id: Optional[int] = None


def _sse_buffer_for_run(run_id: str) -> SSERunStore:
    """Get or create an SSE event store for a run."""
    with _sse_event_store_lock:
        if run_id not in _sse_event_store:
            _sse_event_store[run_id] = SSERunStore()
        return _sse_event_store[run_id]


def _sse_remove_buffer(run_id: str) -> None:
    """Remove an SSE event store after completion."""
    with _sse_event_store_lock:
        _sse_event_store.pop(run_id, None)


def _sse_send_event(run_id: str, event: str, data: str) -> None:
    """Send an SSE event to the store for a run.

    Uses bounded retention: when the buffer is full, non-terminal events are
    dropped from the front to make room. Terminal events (complete, error, end)
    are never silently discarded — they always replace the oldest non-terminal
    event if the buffer is full.

    Returns the assigned event ID (for testing).
    """
    global _sse_next_id
    sse_event = f"event: {event}\ndata: {data}\n\n"
    is_terminal = event in _TERMINAL_EVENTS

    with _sse_event_store_lock:
        if run_id not in _sse_event_store:
            _sse_event_store[run_id] = SSERunStore()
        store = _sse_event_store[run_id]

        # Assign a monotonically increasing ID
        _sse_next_id += 1
        event_id = _sse_next_id

        if len(store.events) >= _SSE_MAX_EVENTS:
            # Evict from the front until there is room
            if is_terminal:
                # Try to remove the oldest non-terminal event first
                removed = False
                for i in range(len(store.events)):
                    ev_id, ev_str = store.events[i]
                    if not any(f"event: {t}" in ev_str for t in _TERMINAL_EVENTS):
                        oldest_evicted = ev_id
                        store.events.pop(i)
                        removed = True
                        if store.evicted_before_id is None or oldest_evicted > store.evicted_before_id:
                            store.evicted_before_id = oldest_evicted
                        break
                if not removed and store.events:
                    # All events are terminal — remove the oldest one
                    oldest_evicted = store.events[0][0]
                    store.events.pop(0)
                    if store.evicted_before_id is None or oldest_evicted > store.evicted_before_id:
                        store.evicted_before_id = oldest_evicted
            else:
                # Drop the oldest event
                oldest_evicted = store.events[0][0]
                store.events.pop(0)
                if store.evicted_before_id is None or oldest_evicted > store.evicted_before_id:
                    store.evicted_before_id = oldest_evicted

        store.events.append((event_id, sse_event))


def _get_api_key() -> str:
    key = os.environ.get("HUB_API_KEY", "")
    if not key:
        raise RuntimeError("HUB_API_KEY environment variable is not set. Refusing to start.")
    return key


def _verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    request: Request = None,
) -> None:
    client_ip = request.client.host if request else "unknown"
    _check_auth_rate_limit(client_ip)
    if credentials is None:
        _record_auth_failure(client_ip)
        raise HTTPException(status_code=401, detail="Authorization header missing")
    expected = _get_api_key()
    if credentials.credentials != expected:
        _record_auth_failure(client_ip)
        raise HTTPException(status_code=401, detail="Invalid API key")


def _verify_token_or_query(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    request: Request = None,
) -> None:
    """Verify token from Authorization header or cookie.

    Used for SSE endpoints where EventSource cannot send custom headers.
    Falls back to cookie-based auth instead of query parameters to avoid
    logging the API key in server access logs, browser history, and proxy logs.
    """
    client_ip = request.client.host if request else "unknown"
    _check_auth_rate_limit(client_ip)
    expected = _get_api_key()
    # Try Authorization header first
    if credentials is not None:
        if credentials.credentials == expected:
            return
    # Fall back to cookie
    cookie_token = request.cookies.get("hub_api_key") if request else None
    if cookie_token is not None and cookie_token == expected:
        return
    _record_auth_failure(client_ip)
    raise HTTPException(status_code=401, detail="Invalid API key")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown event handler."""
    recover_stale_runs()
    providers.ensure_default_providers()
    routines_engine.start_scheduler()
    # H1: Recover persisted queue state on startup
    try:
        from hub import queue_manager
        queue_manager.recover_queue()
    except Exception:
        pass  # Don't fail startup if queue recovery fails
    # H4: Build run index for fast lookups
    try:
        from hub.runner import _build_run_index
        _build_run_index()
    except Exception:
        pass  # Don't fail startup if index build fails
    yield
    routines_engine.stop_scheduler()

app = FastAPI(title="Agent Hub", lifespan=lifespan)


def _validate_startup() -> Dict[str, Any]:
    """Validate configuration and return a status report."""
    issues: List[Dict[str, Any]] = []
    config = load_config()

    # Check each agent's provider availability
    for agent_name, agent_cfg in config.get("agents", {}).items():
        runner_name = agent_cfg.get("runner", "junie")
        provider = providers.get_provider(runner_name)
        if provider is None:
            issues.append({
                "agent": agent_name,
                "severity": "error",
                "message": f"Provider '{runner_name}' not registered",
            })
        elif not provider.check_available():
            issues.append({
                "agent": agent_name,
                "severity": "warning",
                "message": f"Provider '{runner_name}' binary not found on PATH",
            })

        # Check project directory exists
        project_dir = agent_cfg.get("project_dir", "")
        if project_dir:
            p = Path(project_dir).expanduser().resolve()
            if not p.exists():
                issues.append({
                    "agent": agent_name,
                    "severity": "warning",
                    "message": f"Project directory does not exist: {project_dir}",
                })

        # Check remote target connectivity
        remote_cfg = remote.get_agent_remote_config(config, agent_name)
        if remote_cfg:
            target = remote.RemoteTarget(remote_cfg)
            if not target.is_available():
                issues.append({
                    "agent": agent_name,
                    "severity": "warning",
                    "message": f"Remote target '{remote_cfg.host}' is not reachable",
                })

    # Check registered providers
    available_providers = []
    for pname in providers.list_providers():
        p = providers.get_provider(pname)
        if p:
            available_providers.append({
                "name": pname,
                "available": p.check_available(),
            })

    return {
        "issues": issues,
        "providers": available_providers,
        "healthy": len([i for i in issues if i["severity"] == "error"]) == 0,
    }


@app.get("/api/status")
async def api_status(_auth: None = Depends(_verify_token)):
    config = load_config()
    primary_bot = config.get("primary_bot")
    agent_list = []
    for name in config.get("agents", {}):
        status = agent_status(name)
        status["is_primary"] = (name == primary_bot)
        # Add session-based info: last message preview and unread count
        try:
            sessions = memory.list_sessions(agent_id=name, limit=1)
            if sessions:
                sess = sessions[0]
                status["last_message_preview"] = sess.get("last_message_preview", "")
                status["updated_at"] = sess.get("updated_at", "")
                status["unread_count"] = memory.get_unread_count(sess["id"])
            else:
                status["last_message_preview"] = ""
                status["updated_at"] = ""
                status["unread_count"] = 0
        except Exception:
            status["last_message_preview"] = ""
            status["updated_at"] = ""
            status["unread_count"] = 0
        # Add pending approvals count
        try:
            pending = memory.list_approvals(bot_id=name, status="pending")
            status["pending_approvals"] = len(pending)
        except Exception:
            status["pending_approvals"] = 0
        agent_list.append(status)

    validation = _validate_startup()
    return {
        "agents": agent_list,
        "primary_bot": primary_bot,
        "providers": validation["providers"],
        "issues": validation["issues"],
        "healthy": validation["healthy"],
    }


# --- Agents ---


@app.get("/api/agents")
async def api_list_agents(_auth: None = Depends(_verify_token)):
    config = load_config()
    result = []
    for name, data in config.get("agents", {}).items():
        entry = {"name": name}
        for key in ("title", "description", "runner", "project_dir", "skills", "guidelines", "permissions"):
            if key in data:
                entry[key] = data[key]
        result.append(entry)
    return {"agents": result}


@app.post("/api/agents/generate", status_code=201)
async def api_generate_agent(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Generate a Bot config from a one-sentence description."""
    from hub import templates as templates_module
    description = body.get("description", "")
    if not description:
        raise HTTPException(status_code=400, detail="description is required")
    config = templates_module.generate_bot_config(description)
    return config


@app.get("/api/agents/{name}")
async def api_get_agent(name: str, _auth: None = Depends(_verify_token)):
    try:
        data = agents.get_agent(name)
        return {"name": name, **data}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")


@app.post("/api/agents/{name}", status_code=201)
async def api_create_agent(name: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    if not validate_name(name):
        raise HTTPException(status_code=400, detail=f"Invalid agent name: {name}")
    runner = body.get("runner", "junie")
    project_dir = body.get("project_dir", "")
    if not project_dir:
        raise HTTPException(status_code=400, detail="project_dir is required")
    try:
        result = agents.create_agent(
            name=name,
            runner=runner,
            project_dir=project_dir,
            title=body.get("title", ""),
            description=body.get("description", ""),
            skills=body.get("skills", []),
            guidelines=body.get("guidelines", ""),
            permissions=body.get("permissions"),
        )
        return {"name": name, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/agents/{name}")
async def api_update_agent(name: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    allowed = {"title", "description", "runner", "project_dir", "skills", "guidelines", "permissions"}
    updates = {k: v for k, v in body.items() if k in allowed}
    try:
        result = agents.update_agent_data(name, updates)
        return {"name": name, **result}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/primary-bot")
async def api_set_primary_bot(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Set or clear the primary bot."""
    bot_name = body.get("bot_name")
    config = load_config()
    try:
        config = set_primary_bot(config, bot_name)
        save_config(config)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Create proactive check-in routine when setting a primary bot
    if bot_name:
        try:
            _ensure_primary_checkin_routine(bot_name)
        except Exception:
            pass  # Don't fail if routine creation fails

    return {"primary_bot": config.get("primary_bot")}


def _ensure_primary_checkin_routine(bot_name: str) -> None:
    """Create a daily check-in routine for the primary bot if it doesn't exist."""
    existing = memory.list_routines(bot_id=bot_name)
    for r in existing:
        if r.get("name") == "Daily Check-in":
            return  # Already exists
    memory.create_routine(
        bot_id=bot_name,
        name="Daily Check-in",
        task="Review recent activity from other bots and approvals. Post a brief summary of what needs attention.",
        schedule_type="interval",
        schedule_value="1d",
        enabled=True,
    )


@app.delete("/api/agents/{name}")
async def api_delete_agent(name: str, _auth: None = Depends(_verify_token)):
    try:
        agents.delete_agent_by_name(name)
        return {"deleted": name}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")


# --- Skills ---


@app.get("/api/skills")
async def api_list_skills(_auth: None = Depends(_verify_token)):
    skill_list = skills.list_skills()
    for s in skill_list:
        s["used_by"] = skills.skill_usage(s["name"])
    return {"skills": skill_list}


@app.get("/api/skills/{name}")
async def api_get_skill(name: str, _auth: None = Depends(_verify_token)):
    skill_path = skills._skill_path(name)
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    content = skill_md.read_text(encoding="utf-8")
    return {"name": name, "content": content, "used_by": skills.skill_usage(name)}


@app.post("/api/skills/{name}", status_code=201)
async def api_create_skill(name: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    content = body.get("content", "")
    description = body.get("description", "")
    try:
        result = skills.create_skill(name, description=description, content=content)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/skills/{name}")
async def api_update_skill(name: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    content = body.get("content", "")
    description = body.get("description", "")
    try:
        result = skills.update_skill(name, description=description, content=content)
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")


@app.delete("/api/skills/{name}")
async def api_delete_skill(name: str, _auth: None = Depends(_verify_token)):
    try:
        skills.delete_skill(name)
        return {"deleted": name}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")


# --- Agent Skills ---


@app.post("/api/agents/{agent}/skills/{skill}")
async def api_enable_skill(agent: str, skill: str, _auth: None = Depends(_verify_token)):
    try:
        skills.enable_skill(agent, skill)
        skills.sync_agent(agent)
        return {"agent": agent, "skill": skill, "enabled": True}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/agents/{agent}/skills/{skill}")
async def api_disable_skill(agent: str, skill: str, _auth: None = Depends(_verify_token)):
    try:
        skills.disable_skill(agent, skill)
        skills.sync_agent(agent)
        return {"agent": agent, "skill": skill, "enabled": False}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Runs ---


@app.post("/api/agents/{name}/runs", status_code=201)
async def api_dispatch_run(name: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Dispatch a run for an agent, respecting per-bot sequential queueing (M5 fix)."""
    task = body.get("task", "")
    if not task:
        raise HTTPException(status_code=400, detail="task is required")
    try:
        agents.get_agent(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Wire through queue manager instead of bypassing it
    from hub import queue_manager
    run = queue_manager.enqueue_task(bot_id=name, task=task)
    return {"status": "queued", "agent": name, "task": task, "run_id": run.id}


@app.get("/api/runs")
async def api_list_runs(
    agent: Optional[str] = None,
    state: Optional[str] = None,
    _auth: None = Depends(_verify_token),
):
    runs = list_runs(agent=agent, state=state)
    return {"runs": [r.to_dict() for r in runs]}


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: str, _auth: None = Depends(_verify_token)):
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run.to_dict()


@app.post("/api/runs/{run_id}/stop")
async def api_stop_run(run_id: str, _auth: None = Depends(_verify_token)):
    run = stop_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run.to_dict()


# --- Sessions ---


@app.get("/api/sessions")
async def api_list_sessions(
    agent: Optional[str] = None,
    _auth: None = Depends(_verify_token),
):
    sessions = memory.list_sessions(agent_id=agent)
    # Add unread count to each session
    for s in sessions:
        s["unread_count"] = memory.get_unread_count(s["id"])
    return {"sessions": sessions}


@app.post("/api/sessions", status_code=201)
async def api_create_session(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    title = body.get("title", "")
    project_path = body.get("project_path")
    agent_id = body.get("agent_id")
    bot_ids = body.get("bot_ids")
    session = memory.create_session(
        title=title,
        project_path=project_path,
        agent_id=agent_id,
        bot_ids=bot_ids,
    )
    return session


@app.get("/api/sessions/{session_id}")
async def api_get_session(
    session_id: str,
    _auth: None = Depends(_verify_token),
):
    session = memory.get_session_with_messages(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    # Mark session as read and include unread count
    memory.mark_session_read(session_id)
    session["unread_count"] = 0
    return session


@app.delete("/api/sessions/{session_id}")
async def api_delete_session(
    session_id: str,
    _auth: None = Depends(_verify_token),
):
    deleted = memory.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return {"deleted": session_id}


# --- Message dispatch ---


@app.post("/api/sessions/{session_id}/messages", status_code=201)
async def api_dispatch_message(
    session_id: str,
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    # Validate session exists
    session = memory.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    content = body.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="content is required")

    # Allow overriding agent_id from request body
    agent_id = body.get("agent_id") or session.get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=400, detail="Session has no agent_id set")

    # Validate agent exists
    try:
        agent_cfg = agents.get_agent(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # Update session's agent_id if it changed
    if session.get("agent_id") != agent_id:
        conn = memory._get_connection()
        conn.execute(
            "UPDATE sessions SET agent_id = ? WHERE id = ?",
            (agent_id, session_id),
        )
        conn.commit()

    # Optional prompt refinement via Ollama
    refine_prompt = body.get("refine_prompt", False)
    refined_content = content
    if refine_prompt:
        ollama_client = _get_ollama_client()
        if ollama_client and ollama_client.is_available():
            project_path = session.get("project_path", "")
            context = None
            if project_path:
                context = memory.assemble_context(
                    session_id=session_id,
                    agent_id=agent_id,
                    project_path=project_path,
                )
            refined_content = ollama_client.refine_prompt(
                prompt=content,
                context=context,
            )

    # Persist user message (original content, not refined)
    memory.add_message(
        session_id=session_id,
        role="user",
        content=content,
        bot_id=agent_id,
    )

    # Pre-create a run ID and SSE buffer BEFORE starting the run.
    # This ensures output_callback has a buffer to write to from the very first line.
    pre_run_id = str(uuid.uuid4())
    _sse_buffer_for_run(pre_run_id)

    def _output_callback(line_type: str, text: str) -> None:
        """Called for each line of agent output during execution."""
        clean = text.rstrip()
        if clean:
            _sse_send_event(pre_run_id, "output", json.dumps({
                "event": "output",
                "run_id": pre_run_id,
                "type": line_type,
                "text": clean,
            }))

    def _on_start(rid: str) -> None:
        _sse_send_event(rid, "start", json.dumps({"event": "start", "run_id": rid, "state": "working"}))

    def _on_complete(result: Run) -> None:
        if result.state == "done":
            _sse_send_event(result.id, "complete", json.dumps({
                "event": "complete",
                "run_id": result.id,
                "state": "done",
                "answer": result.answer,
            }))
        elif result.state == "failed":
            _sse_send_event(result.id, "error", json.dumps({
                "event": "error",
                "run_id": result.id,
                "state": "failed",
                "reason": result.fail_reason,
            }))
        else:
            _sse_send_event(result.id, "complete", json.dumps({
                "event": "complete",
                "run_id": result.id,
                "state": result.state,
            }))
        _sse_send_event(result.id, "end", "")

        def _delayed_cleanup():
            time.sleep(30)
            _sse_remove_buffer(result.id)

        threading.Thread(target=_delayed_cleanup, daemon=True).start()

    from hub import queue_manager
    queue_manager.enqueue_task(
        bot_id=agent_id,
        task=refined_content,
        session_id=session_id,
        output_callback=_output_callback,
        on_start=_on_start,
        on_complete=_on_complete,
        run_id=pre_run_id,
    )

    # Return immediately with the run ID; client connects to SSE stream
    return {
        "status": "queued",
        "session_id": session_id,
        "agent": agent_id,
        "run_id": pre_run_id,
    }


# --- Bot Queue & Pause/Resume ---


@app.post("/api/bots/{bot_id}/pause")
async def api_pause_bot(bot_id: str, _auth: None = Depends(_verify_token)):
    try:
        agents.get_agent(bot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    from hub import queue_manager
    queue_manager.pause_bot(bot_id)
    return {"status": "paused", "bot": bot_id}


@app.post("/api/bots/{bot_id}/resume")
async def api_resume_bot(bot_id: str, _auth: None = Depends(_verify_token)):
    try:
        agents.get_agent(bot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    from hub import queue_manager
    queue_manager.resume_bot(bot_id)
    return {"status": "resumed", "bot": bot_id}


@app.get("/api/bots/{bot_id}/queue")
async def api_get_bot_queue(bot_id: str, _auth: None = Depends(_verify_token)):
    try:
        agents.get_agent(bot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    from hub import queue_manager
    items = queue_manager.get_bot_queue(bot_id)
    return {
        "bot": bot_id,
        "paused": queue_manager.is_bot_paused(bot_id),
        "queue": items,
    }


# --- SSE streaming ---


@app.get("/api/sessions/{session_id}/stream")
async def api_stream_session(
    session_id: str,
    run_id: Optional[str] = None,
    _auth: None = Depends(_verify_token_or_query),
):
    """SSE endpoint for live run output.

    Streams events for a specific run (via ?run_id=...) or for the latest run
    in the session.  If the run is already finished, replays all stored events
    so the client does not hang indefinitely.

    Each connected client receives its own ordered copy of the full event stream
    — multiple clients do not compete for events.
    """
    session = memory.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    # Resolve the target run
    all_runs = list_runs()
    session_runs = [r for r in all_runs if r.session_id == session_id]
    session_runs.sort(key=lambda r: r.started or "", reverse=True)

    if run_id:
        # Stream a specific run
        target_run = next((r for r in session_runs if r.id == run_id), None)
        if target_run is None:
            # Run not found in this session — check all runs
            target_run = next((r for r in all_runs if r.id == run_id), None)
            if target_run is None:
                raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    else:
        # Stream the latest run in the session
        target_run = session_runs[0] if session_runs else None

    async def event_generator():
        if target_run is None:
            # No runs at all — send idle and close
            yield "event: idle\ndata: no active run\n\n"
            return

        rid = target_run.id
        store = _sse_buffer_for_run(rid)

        if target_run.state == "working":
            # Run is in progress — stream events using event ID cursors.
            # Each client tracks its own last_event_id so multiple clients
            # get independent ordered streams that survive evictions.
            last_event_id = 0
            received_end = False
            gap_sent = False
            while True:
                # Acquire lock only to snapshot; release before yielding.
                with _sse_event_store_lock:
                    s = _sse_event_store.get(rid)
                    if s is None:
                        # Store was cleaned up; fall through to final-state replay
                        break
                    # Check for retention gap: client is behind when its
                    # cursor is less than the highest evicted ID.
                    has_gap = (
                        s.evicted_before_id is not None
                        and s.evicted_before_id > last_event_id
                    )
                    # Snapshot (id, string) pairs after the client's cursor
                    new_events = [
                        (ev_id, ev_str)
                        for ev_id, ev_str in s.events
                        if ev_id > last_event_id
                    ]
                # Yield outside the lock so slow clients don't block producers.
                if has_gap and not gap_sent:
                    yield (
                        f"event: retention_gap\ndata: "
                        f"{json.dumps({'run_id': rid, 'evicted_before_id': s.evicted_before_id})}\n\n"
                    )
                    gap_sent = True
                if new_events:
                    for ev_id, ev_str in new_events:
                        yield ev_str
                    # Advance cursor using the IDs of events in this snapshot,
                    # not from the shared store, so new events arriving between
                    # snapshot and cursor update are never skipped.
                    last_event_id = new_events[-1][0]
                    # Check for end event
                    if any("event: end" in ev_str for _, ev_str in new_events):
                        received_end = True
                        break
                else:
                    try:
                        await asyncio.sleep(0.2)
                    except asyncio.CancelledError:
                        break

            # If we broke out without receiving an end event, replay final state
            if not received_end:
                if target_run.state == "done":
                    yield f"event: complete\ndata: {json.dumps({'run_id': rid, 'state': 'done', 'answer': target_run.answer})}\n\n"
                elif target_run.state == "failed":
                    yield f"event: error\ndata: {json.dumps({'run_id': rid, 'state': 'failed', 'reason': target_run.fail_reason})}\n\n"
                yield "event: end\n\n"
        else:
            # Run already finished — replay all stored events
            with _sse_event_store_lock:
                s = _sse_event_store.get(rid)
                if s is not None:
                    events = [ev_str for _, ev_str in s.events]
                else:
                    events = []
            # Notify about retention gap if events were evicted
            with _sse_event_store_lock:
                s = _sse_event_store.get(rid)
                evicted_before = s.evicted_before_id if s else None
            if evicted_before is not None:
                yield (
                    f"event: retention_gap\ndata: "
                    f"{json.dumps({'run_id': rid, 'evicted_before_id': evicted_before})}\n\n"
                )
            for ev in events:
                yield ev
            # If no stored events, replay the final state from the run record
            if not events:
                if target_run.state == "done":
                    yield f"event: complete\ndata: {json.dumps({'run_id': rid, 'state': 'done', 'answer': target_run.answer})}\n\n"
                elif target_run.state == "failed":
                    yield f"event: error\ndata: {json.dumps({'run_id': rid, 'state': 'failed', 'reason': target_run.fail_reason})}\n\n"
                else:
                    yield f"event: complete\ndata: {json.dumps({'run_id': rid, 'state': target_run.state})}\n\n"
            yield "event: end\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Memories ---


@app.get("/api/memories")
async def api_list_memories(
    agent: Optional[str] = None,
    project: Optional[str] = None,
    q: Optional[str] = None,
    _auth: None = Depends(_verify_token),
):
    memories_list = memory.list_memories(
        agent_id=agent,
        project_path=project,
        search=q,
    )
    return {"memories": memories_list}


@app.post("/api/memories", status_code=201)
async def api_create_memory(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    content = body.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    mem = memory.create_memory(
        content=content,
        project_path=body.get("project_path"),
        session_id=body.get("session_id"),
        agent_id=body.get("agent_id"),
        tags=body.get("tags"),
    )
    return mem


@app.put("/api/memories/{memory_id}")
async def api_update_memory(
    memory_id: str,
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    existing = memory.get_memory(memory_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")
    content = body.get("content")
    # Update content if provided, otherwise just update timestamp
    updated = memory.update_memory(memory_id, content=content)
    # Also allow updating session_id via direct SQL
    if "session_id" in body:
        conn = memory._get_connection()
        conn.execute(
            "UPDATE memories SET session_id = ?, updated_at = ? WHERE id = ?",
            (body["session_id"], updated["updated_at"], memory_id),
        )
        conn.commit()
        updated["session_id"] = body["session_id"]
    return updated


@app.delete("/api/memories/{memory_id}")
async def api_delete_memory(
    memory_id: str,
    _auth: None = Depends(_verify_token),
):
    deleted = memory.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")
    return {"deleted": memory_id}


# --- Providers ---


@app.get("/api/providers")
async def api_list_providers(_auth: None = Depends(_verify_token)):
    """List all registered providers and their availability."""
    provider_list = []
    for pname in providers.list_providers():
        p = providers.get_provider(pname)
        if p:
            provider_list.append({
                "name": p.name,
                "available": p.check_available(),
            })
    return {"providers": provider_list}


# --- Projects ---


@app.get("/api/projects")
async def api_list_projects(
    _auth: None = Depends(_verify_token),
):
    projects = memory.discover_projects()
    return {"projects": projects}


# --- Ollama ---


def _get_ollama_client() -> Optional[ollama.OllamaClient]:
    """Get the Ollama client from config."""
    return ollama.get_ollama_client()


@app.get("/api/ollama/status")
async def api_ollama_status(_auth: None = Depends(_verify_token)):
    """Check if Ollama integration is configured and available."""
    client = _get_ollama_client()
    if client is None:
        return {"enabled": False, "available": False}
    return {
        "enabled": True,
        "available": client.is_available(),
        "base_url": client.base_url,
        "model": client.model,
    }


@app.post("/api/ollama/refine")
async def api_ollama_refine(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Refine a prompt using Ollama for clarity and completeness."""
    client = _get_ollama_client()
    if client is None:
        raise HTTPException(status_code=400, detail="Ollama integration is not configured")

    prompt = body.get("prompt", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    context = body.get("context", "")
    system_instruction = body.get("system_instruction", "")

    refined = client.refine_prompt(
        prompt=prompt,
        context=context or None,
        system_instruction=system_instruction or None,
    )

    return {
        "original": prompt,
        "refined": refined,
        "changed": refined != prompt,
    }


@app.post("/api/ollama/summarize")
async def api_ollama_summarize(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Summarize text using Ollama."""
    client = _get_ollama_client()
    if client is None:
        raise HTTPException(status_code=400, detail="Ollama integration is not configured")

    text = body.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    max_length = body.get("max_length", 500)
    focus = body.get("focus", "")

    summary = client.summarize(
        text=text,
        max_length=max_length,
        focus=focus or None,
    )

    return {"summary": summary}


@app.post("/api/ollama/decompose")
async def api_ollama_decompose(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Decompose a complex task into subtasks using Ollama."""
    client = _get_ollama_client()
    if client is None:
        raise HTTPException(status_code=400, detail="Ollama integration is not configured")

    task = body.get("task", "")
    if not task:
        raise HTTPException(status_code=400, detail="task is required")

    context = body.get("context", "")

    subtasks = client.decompose_task(
        task=task,
        context=context or None,
    )

    return {"subtasks": subtasks}


# --- Obsidian ---


def _get_obsidian_vault() -> Optional[obsidian.ObsidianVault]:
    """Get the Obsidian vault from config."""
    config = load_config()
    obs_cfg = config.get("obsidian", {})
    if not obs_cfg.get("enabled", False):
        return None
    vault_path = obs_cfg.get("vault_path", "")
    if not vault_path:
        return None
    vault = obsidian.ObsidianVault(Path(vault_path))
    return vault if vault.enabled else None


@app.get("/api/obsidian/status")
async def api_obsidian_status(_auth: None = Depends(_verify_token)):
    """Check if Obsidian integration is configured and available."""
    vault = _get_obsidian_vault()
    if vault is None:
        return {"enabled": False, "available": False}
    return {
        "enabled": True,
        "available": vault.is_valid(),
        "vault_path": str(vault.vault_path),
    }


@app.get("/api/obsidian/notes")
async def api_obsidian_list_notes(
    q: Optional[str] = None,
    tag: Optional[str] = None,
    folder: Optional[str] = None,
    limit: int = 50,
    _auth: None = Depends(_verify_token),
):
    """List notes from the Obsidian vault."""
    vault = _get_obsidian_vault()
    if vault is None:
        raise HTTPException(status_code=400, detail="Obsidian integration is not configured")
    notes = vault.list_notes(query=q, tag=tag, folder=folder, limit=limit)
    return {"notes": [note.to_dict() for note in notes]}


@app.get("/api/obsidian/notes/{note_id}")
async def api_obsidian_get_note(
    note_id: str,
    _auth: None = Depends(_verify_token),
):
    """Get a note's content from the Obsidian vault."""
    vault = _get_obsidian_vault()
    if vault is None:
        raise HTTPException(status_code=400, detail="Obsidian integration is not configured")
    content = vault.read_note_content(note_id)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Note '{note_id}' not found")
    note = vault.get_note(note_id)
    return {
        "id": note.note_id if note else note_id,
        "title": note.title if note else note_id,
        "path": note.relative_path if note else note_id,
        "content": content,
    }


@app.post("/api/obsidian/sync", status_code=201)
async def api_obsidian_sync_session(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Write a session summary to the Obsidian vault."""
    vault = _get_obsidian_vault()
    if vault is None:
        raise HTTPException(status_code=400, detail="Obsidian integration is not configured")

    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    # Get session details
    session = memory.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    messages = memory.get_session_messages(session_id)
    title = session.get("title", "Untitled Session")

    note = vault.write_session_summary(session_id, title, messages)
    if note is None:
        raise HTTPException(status_code=500, detail="Failed to write session summary to Obsidian")

    return {"note": note.to_dict()}


# --- Remote Execution ---


@app.get("/api/remote/status")
async def api_remote_status(_auth: None = Depends(_verify_token)):
    """Check remote execution configuration and connectivity."""
    config = load_config()
    targets: List[Dict[str, Any]] = []

    # Check top-level remote config
    top_level = remote.get_remote_config(config)
    if top_level:
        target = remote.RemoteTarget(top_level)
        targets.append({
            "scope": "global",
            "host": top_level.host,
            "user": top_level.user,
            "port": top_level.port,
            "available": target.is_available(),
        })

    # Check per-agent remote configs
    for agent_name, agent_cfg in config.get("agents", {}).items():
        agent_remote = remote.get_agent_remote_config(config, agent_name)
        if agent_remote:
            t = remote.RemoteTarget(agent_remote)
            targets.append({
                "scope": "agent",
                "agent": agent_name,
                "host": agent_remote.host,
                "user": agent_remote.user,
                "port": agent_remote.port,
                "available": t.is_available(),
            })

    return {
        "ssh_available": shutil.which("ssh") is not None,
        "targets": targets,
    }


# --- Git Status ---


@app.get("/api/git/status")
async def api_git_status(
    project: str,
    _auth: None = Depends(_verify_token),
):
    """Get Git status for a project directory."""
    from hub import git_service
    status = git_service.get_git_status(project)
    return status.to_dict()


@app.get("/api/git/worktrees")
async def api_git_worktrees(
    project: str,
    _auth: None = Depends(_verify_token),
):
    """List worktrees for a Git repository."""
    from hub import git_service
    worktrees = git_service.list_worktrees(project)
    return {"worktrees": [wt.to_dict() for wt in worktrees]}


# --- Multi-Agent Coordinator ---


@app.post("/api/coordinator", status_code=201)
async def api_create_coordinator(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Create a new task coordinator for a project."""
    coordinator_id = body.get("coordinator_id") or str(uuid.uuid4())[:8]
    project_dir = body.get("project_dir")
    if not project_dir:
        raise HTTPException(status_code=400, detail="project_dir is required")

    max_concurrency = body.get("max_concurrency", 3)
    worktree_base = body.get("worktree_base")

    coord = coordinator.create_coordinator(
        coordinator_id=coordinator_id,
        project_dir=project_dir,
        max_concurrency=max_concurrency,
        worktree_base=worktree_base,
    )
    return coord.get_summary()


@app.get("/api/coordinator")
async def api_list_coordinators(
    _auth: None = Depends(_verify_token),
):
    """List all active coordinators."""
    return coordinator.list_coordinators()


@app.get("/api/coordinator/{coordinator_id}")
async def api_get_coordinator(
    coordinator_id: str,
    _auth: None = Depends(_verify_token),
):
    """Get a coordinator's current status."""
    coord = coordinator.get_coordinator(coordinator_id)
    if coord is None:
        raise HTTPException(status_code=404, detail=f"Coordinator '{coordinator_id}' not found")
    return coord.get_summary()


@app.delete("/api/coordinator/{coordinator_id}")
async def api_delete_coordinator(
    coordinator_id: str,
    _auth: None = Depends(_verify_token),
):
    """Remove a coordinator and clean up its worktrees."""
    removed = coordinator.remove_coordinator(coordinator_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Coordinator '{coordinator_id}' not found")
    return {"deleted": coordinator_id}


@app.post("/api/coordinator/{coordinator_id}/tasks", status_code=201)
async def api_add_coordinator_task(
    coordinator_id: str,
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Add a task to a coordinator's plan."""
    coord = coordinator.get_coordinator(coordinator_id)
    if coord is None:
        raise HTTPException(status_code=404, detail=f"Coordinator '{coordinator_id}' not found")

    name = body.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    description = body.get("description", "")
    agent = body.get("agent", "vault")
    dependencies = body.get("dependencies", [])

    task_id = coord.add_task(name, description, agent, dependencies)
    task = coord.get_task(task_id)
    return task.to_dict() if task else {"id": task_id}


@app.delete("/api/coordinator/{coordinator_id}/tasks/{task_id}")
async def api_remove_coordinator_task(
    coordinator_id: str,
    task_id: str,
    _auth: None = Depends(_verify_token),
):
    """Remove a pending task from a coordinator's plan."""
    coord = coordinator.get_coordinator(coordinator_id)
    if coord is None:
        raise HTTPException(status_code=404, detail=f"Coordinator '{coordinator_id}' not found")

    removed = coord.remove_task(task_id)
    if not removed:
        raise HTTPException(status_code=400, detail=f"Task '{task_id}' not found or cannot be removed")
    return {"deleted": task_id}


@app.post("/api/coordinator/{coordinator_id}/execute")
async def api_execute_coordinator(
    coordinator_id: str,
    _auth: None = Depends(_verify_token),
):
    """Start executing a coordinator's task plan."""
    coord = coordinator.get_coordinator(coordinator_id)
    if coord is None:
        raise HTTPException(status_code=404, detail=f"Coordinator '{coordinator_id}' not found")
    coord.execute()
    return {"status": "executing", "coordinator_id": coordinator_id}


@app.post("/api/coordinator/{coordinator_id}/cancel")
async def api_cancel_coordinator(
    coordinator_id: str,
    _auth: None = Depends(_verify_token),
):
    """Cancel all tasks in a coordinator."""
    coord = coordinator.get_coordinator(coordinator_id)
    if coord is None:
        raise HTTPException(status_code=404, detail=f"Coordinator '{coordinator_id}' not found")
    coord.cancel_all()
    return {"status": "cancelled", "coordinator_id": coordinator_id}


@app.post("/api/coordinator/{coordinator_id}/tasks/{task_id}/approve")
async def api_approve_task(
    coordinator_id: str,
    task_id: str,
    _auth: None = Depends(_verify_token),
):
    """Approve a task's changes, marking it as completed."""
    coord = coordinator.get_coordinator(coordinator_id)
    if coord is None:
        raise HTTPException(status_code=404, detail=f"Coordinator '{coordinator_id}' not found")

    approved = coord.approve_task(task_id)
    if not approved:
        raise HTTPException(status_code=400, detail=f"Task '{task_id}' not in needs_approval state")
    return {"approved": task_id}


@app.post("/api/coordinator/{coordinator_id}/tasks/{task_id}/reject")
async def api_reject_task(
    coordinator_id: str,
    task_id: str,
    _auth: None = Depends(_verify_token),
):
    """Reject a task's changes, marking it as failed and cleaning up its worktree."""
    coord = coordinator.get_coordinator(coordinator_id)
    if coord is None:
        raise HTTPException(status_code=404, detail=f"Coordinator '{coordinator_id}' not found")

    rejected = coord.reject_task(task_id)
    if not rejected:
        raise HTTPException(status_code=400, detail=f"Task '{task_id}' not in needs_approval state")
    return {"rejected": task_id}


# --- Handoffs ---


@app.post("/api/sessions/{session_id}/handoff", status_code=201)
async def api_handoff(
    session_id: str,
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Hand off a task from one Bot to another within the same session.

    Expects: from_bot, to_bot, message.
    Prevents infinite loops by tracking hop count.
    """
    from_bot = body.get("from_bot", "")
    to_bot = body.get("to_bot", "")
    message = body.get("message", "")
    if not from_bot or not to_bot:
        raise HTTPException(status_code=400, detail="from_bot and to_bot are required")

    # Validate session exists
    session = memory.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    # Validate to_bot exists
    try:
        agents.get_agent(to_bot)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Bot '{to_bot}' not found")

    # Check handoff loop prevention
    max_hops = 5  # Default max hops
    config = load_config()
    max_hops = config.get("max_handoff_hops", 5)

    # Count existing handoffs in this session
    messages = memory.get_session_messages(session_id)
    hop_count = sum(1 for m in messages if m.get("msg_type") == "handoff")
    if hop_count >= max_hops:
        raise HTTPException(
            status_code=400,
            detail=f"Max handoff hops ({max_hops}) reached. Preventing infinite loop."
        )

    # Record handoff message
    now_iso = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    memory.add_message(
        session_id=session_id,
        role="assistant",
        content=f"Handing off to @{to_bot}: {message}",
        bot_id=from_bot,
        msg_type="handoff",
        metadata=f'{{"from": "{from_bot}", "to": "{to_bot}", "hop": {hop_count + 1}, "at": "{now_iso}"}}',
    )

    # Dispatch to the receiving bot via queue manager
    from hub import queue_manager

    def _on_handoff_complete(res):
        finished_iso = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        memory.add_message(
            session_id=session_id,
            role="assistant",
            content=res.raw_output or "Handoff task completed.",
            bot_id=to_bot,
            msg_type="handoff_reply",
            metadata=f'{{"from": "{to_bot}", "run_id": "{res.id}", "at": "{finished_iso}"}}',
        )
        _sse_send_event(res.id, "complete", res.state)

    run = queue_manager.enqueue_task(
        bot_id=to_bot,
        task=message,
        session_id=session_id,
        on_complete=_on_handoff_complete,
    )

    return {
        "status": "dispatched",
        "run_id": run.id,
        "from_bot": from_bot,
        "to_bot": to_bot,
        "session_id": session_id,
        "hop": hop_count + 1,
    }


# --- Templates / Marketplace ---


@app.get("/api/templates")
async def api_list_templates(_auth: None = Depends(_verify_token)):
    """List all available Bot templates."""
    from hub import templates as templates_module
    templates_list = templates_module.list_templates()
    return {"templates": templates_list}


@app.get("/api/templates/{name}")
async def api_get_template(name: str, _auth: None = Depends(_verify_token)):
    """Get a single template by name."""
    from hub import templates as templates_module
    template = templates_module.get_template(name)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
    return template


@app.post("/api/templates/{name}/apply", status_code=201)
async def api_apply_template(
    name: str,
    body: Optional[Dict[str, Any]] = None,
    _auth: None = Depends(_verify_token),
):
    """Create an agent from a template."""
    from hub import templates as templates_module
    body = body or {}
    agent_name = body.get("agent_name")
    try:
        result = templates_module.create_agent_from_template(name, agent_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


# --- Teach a Task ---


@app.post("/api/routines/teach", status_code=201)
async def api_teach_as_routine(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Save a run as a reusable routine.

    Expects: run_id (required), bot_id (required), optional name override.
    """
    run_id = body.get("run_id", "")
    bot_id = body.get("bot_id", "")
    if not run_id or not bot_id:
        raise HTTPException(status_code=400, detail="run_id and bot_id are required")

    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    name = body.get("name", run.task[:50] if run.task else "Saved task")
    routine = memory.create_routine(
        bot_id=bot_id,
        name=name,
        task_text=run.task or "",
        schedule_type="manual",
        schedule_value="",
        enabled=True,
    )
    return routine


# --- Routines ---


@app.get("/api/routines")
async def api_list_routines(
    bot_id: Optional[str] = None,
    _auth: None = Depends(_verify_token),
):
    routines_list = memory.list_routines(bot_id=bot_id)
    return {"routines": routines_list}


@app.post("/api/routines", status_code=201)
async def api_create_routine(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    bot_id = body.get("bot_id", "")
    name = body.get("name", "")
    task_text = body.get("task_text", "")
    if not bot_id or not name or not task_text:
        raise HTTPException(status_code=400, detail="bot_id, name, and task_text are required")
    routine = memory.create_routine(
        bot_id=bot_id,
        name=name,
        task_text=task_text,
        schedule_type=body.get("schedule_type", "interval"),
        schedule_value=body.get("schedule_value", "3600"),
        enabled=body.get("enabled", True),
    )
    return routine


@app.put("/api/routines/{routine_id}")
async def api_update_routine(
    routine_id: str,
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    existing = memory.get_routine(routine_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Routine '{routine_id}' not found")
    updated = memory.update_routine(
        routine_id=routine_id,
        name=body.get("name"),
        task_text=body.get("task_text"),
        schedule_type=body.get("schedule_type"),
        schedule_value=body.get("schedule_value"),
        enabled=body.get("enabled"),
    )
    return updated


@app.delete("/api/routines/{routine_id}")
async def api_delete_routine(
    routine_id: str,
    _auth: None = Depends(_verify_token),
):
    deleted = memory.delete_routine(routine_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Routine '{routine_id}' not found")
    return {"deleted": routine_id}


@app.post("/api/routines/{routine_id}/run-now")
async def api_run_routine_now(
    routine_id: str,
    _auth: None = Depends(_verify_token),
):
    result = routines_engine.run_routine_now(routine_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Routine '{routine_id}' not found")
    return result


# --- Approvals ---


@app.get("/api/approvals")
async def api_list_approvals(
    session_id: Optional[str] = None,
    bot_id: Optional[str] = None,
    status: Optional[str] = None,
    _auth: None = Depends(_verify_token),
):
    approvals_list = memory.list_approvals(
        session_id=session_id,
        bot_id=bot_id,
        status=status,
    )
    return {"approvals": approvals_list}


@app.post("/api/approvals/{approval_id}/approve")
async def api_approve(
    approval_id: str,
    _auth: None = Depends(_verify_token),
):
    existing = memory.get_approval(approval_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found")
    updated = memory.update_approval_status(approval_id, "approved")
    return updated


@app.post("/api/approvals/{approval_id}/deny")
async def api_deny(
    approval_id: str,
    _auth: None = Depends(_verify_token),
):
    existing = memory.get_approval(approval_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found")
    updated = memory.update_approval_status(approval_id, "denied")
    return updated


# --- Auto Review Settings ---


@app.get("/api/auto-review/settings")
async def api_get_auto_review_settings(_auth: None = Depends(_verify_token)):
    """Get auto-review settings."""
    from hub import auto_review
    config = load_config()
    auto_review_cfg = config.get("auto_review", {})
    return {
        "enabled": auto_review_cfg.get("enabled", False),
        "patterns": auto_review_cfg.get("patterns", auto_review.get_patterns()),
    }


@app.put("/api/auto-review/settings")
async def api_update_auto_review_settings(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Update auto-review settings."""
    config = load_config()
    auto_review_cfg = config.get("auto_review", {})
    if "enabled" in body:
        auto_review_cfg["enabled"] = body["enabled"]
    if "patterns" in body:
        auto_review_cfg["patterns"] = body["patterns"]
    config["auto_review"] = auto_review_cfg
    from hub.config import save_config
    save_config(config)
    return {"enabled": auto_review_cfg.get("enabled", False)}


# --- Bot Memory ---


from hub import bot_memory as bot_memory_module


@app.get("/api/bots/{bot_id}/memory")
async def api_get_bot_memory(
    bot_id: str,
    _auth: None = Depends(_verify_token),
):
    """Get the per-Bot memory file content."""
    config = load_config()
    agents_cfg = config.get("agents", {})
    if bot_id not in agents_cfg:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    content = bot_memory_module.read_bot_memory(bot_id)
    return {"content": content}


@app.put("/api/bots/{bot_id}/memory")
async def api_update_bot_memory(
    bot_id: str,
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Update the per-Bot memory file content."""
    config = load_config()
    agents_cfg = config.get("agents", {})
    if bot_id not in agents_cfg:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    content = body.get("content", "")
    bot_memory_module.write_bot_memory(bot_id, content)
    return {"content": content}


@app.post("/api/bots/{bot_id}/memory/propose")
async def api_propose_memory_update(
    bot_id: str,
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Propose a memory update for a bot.

    Saves the previous content for undo, writes the new content,
    and adds a system message to the session.
    Expects: content (required), session_id (required), optional run_id.
    """
    config = load_config()
    agents_cfg = config.get("agents", {})
    if bot_id not in agents_cfg:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    content = body.get("content", "")
    session_id = body.get("session_id", "")
    run_id = body.get("run_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    msg = memory.propose_memory_update(
        bot_id=bot_id,
        session_id=session_id,
        new_content=content,
        run_id=run_id,
    )
    return {"message": msg, "content": content}


@app.post("/api/bots/{bot_id}/memory/undo")
async def api_undo_memory_update(
    bot_id: str,
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Undo a previous memory update by restoring the old content.

    Expects: session_id (required), previous_content (required).
    """
    config = load_config()
    agents_cfg = config.get("agents", {})
    if bot_id not in agents_cfg:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    session_id = body.get("session_id", "")
    previous_content = body.get("previous_content", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    msg = memory.undo_memory_update(
        bot_id=bot_id,
        session_id=session_id,
        previous_content=previous_content,
    )
    return {"message": msg, "content": previous_content}


# --- Static files ---


@app.get("/")
async def serve_index():
    index = _STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "Agent Hub", "status": "running"}


@app.get("/static/{path:path}")
async def serve_static(path: str):
    file_path = _STATIC_DIR / path
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    raise HTTPException(status_code=404, detail="File not found")
