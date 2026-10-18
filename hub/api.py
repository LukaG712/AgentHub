"""FastAPI application for the agent hub."""

import asyncio
import contextlib
import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from hub import agents, memory, providers, skills
from hub.config import load_config, save_config, validate_name
from hub.runner import (
    run_agent,
    stop_run,
    get_run,
    list_runs,
    agent_status,
    recover_stale_runs,
)

security = HTTPBearer(auto_error=False)

# Static files directory
_STATIC_DIR = Path(__file__).resolve().parent / "static"

# SSE event buffers: maps run_id -> queue.Queue of event strings
_sse_buffers: Dict[str, queue.Queue] = {}
_sse_buffers_lock = threading.Lock()


def _sse_buffer_for_run(run_id: str) -> queue.Queue:
    """Get or create an SSE event buffer for a run."""
    with _sse_buffers_lock:
        if run_id not in _sse_buffers:
            _sse_buffers[run_id] = queue.Queue()
        return _sse_buffers[run_id]


def _sse_remove_buffer(run_id: str) -> None:
    """Remove an SSE event buffer after completion."""
    with _sse_buffers_lock:
        _sse_buffers.pop(run_id, None)


def _sse_send_event(run_id: str, event: str, data: str) -> None:
    """Send an SSE event to the buffer for a run."""
    buf = _sse_buffer_for_run(run_id)
    buf.put(f"event: {event}\ndata: {data}\n\n")


def _get_api_key() -> str:
    key = os.environ.get("HUB_API_KEY", "")
    if not key:
        raise RuntimeError("HUB_API_KEY environment variable is not set. Refusing to start.")
    return key


def _verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> None:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    expected = _get_api_key()
    if credentials.credentials != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown event handler."""
    recover_stale_runs()
    providers.ensure_default_providers()
    yield

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
    agent_list = []
    for name in config.get("agents", {}):
        status = agent_status(name)
        agent_list.append(status)

    validation = _validate_startup()
    return {
        "agents": agent_list,
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
    task = body.get("task", "")
    if not task:
        raise HTTPException(status_code=400, detail="task is required")
    try:
        agents.get_agent(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Run in background thread
    result = []

    def _run():
        result.append(run_agent(name, task))

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # Return immediately with a placeholder
    # The run will be saved by run_agent
    return {"status": "queued", "agent": name, "task": task}


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
    return {"sessions": sessions}


@app.post("/api/sessions", status_code=201)
async def api_create_session(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    title = body.get("title", "")
    project_path = body.get("project_path")
    agent_id = body.get("agent_id")
    session = memory.create_session(
        title=title,
        project_path=project_path,
        agent_id=agent_id,
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

    # Persist user message
    memory.add_message(
        session_id=session_id,
        role="user",
        content=content,
    )

    # Create SSE buffer before starting the run
    run_id_placeholder = []

    def _run():
        result = run_agent(agent_id, content, session_id=session_id)
        run_id_placeholder.append(result.id)
        # Send SSE events
        _sse_send_event(result.id, "start", json.dumps({"run_id": result.id, "state": "working"}))
        if result.state == "done":
            _sse_send_event(result.id, "complete", json.dumps({
                "run_id": result.id,
                "state": "done",
                "answer": result.answer,
            }))
        elif result.state == "failed":
            _sse_send_event(result.id, "error", json.dumps({
                "run_id": result.id,
                "state": "failed",
                "reason": result.fail_reason,
            }))
        else:
            _sse_send_event(result.id, "complete", json.dumps({
                "run_id": result.id,
                "state": result.state,
            }))
        # Signal completion
        _sse_send_event(result.id, "end", "")
        # Clean up buffer after a delay
        time.sleep(5)
        _sse_remove_buffer(result.id)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # Return immediately; client should connect to SSE stream
    # We need to wait a moment for the run to get its ID
    time.sleep(0.2)
    actual_run_id = run_id_placeholder[0] if run_id_placeholder else None

    return {
        "status": "queued",
        "session_id": session_id,
        "agent": agent_id,
        "run_id": actual_run_id,
    }


# --- SSE streaming ---


@app.get("/api/sessions/{session_id}/stream")
async def api_stream_session(
    session_id: str,
    _auth: None = Depends(_verify_token),
):
    """SSE endpoint for live run output.
    
    Finds the latest run for this session and streams its events.
    """
    session = memory.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    # Find the latest run for this session
    all_runs = list_runs()
    session_runs = [r for r in all_runs if r.session_id == session_id]
    session_runs.sort(key=lambda r: r.started or "", reverse=True)
    latest_run = session_runs[0] if session_runs else None

    async def event_generator():
        if latest_run and latest_run.state == "working":
            run_id = latest_run.id
            buf = _sse_buffer_for_run(run_id)
            # Send any buffered events first
            while not buf.empty():
                try:
                    event = buf.get_nowait()
                    yield event
                except queue.Empty:
                    break
            # Wait for new events
            while True:
                try:
                    event = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, buf.get),
                        timeout=300,  # 5 minute timeout
                    )
                    yield event
                    if "event: end" in event:
                        break
                except asyncio.TimeoutError:
                    yield "event: timeout\ndata: stream timeout\n\n"
                    break
        else:
            # No active run; send idle event
            if latest_run:
                yield f"event: idle\ndata: {json.dumps({'run_id': latest_run.id, 'state': latest_run.state})}\n\n"
            else:
                yield "event: idle\ndata: no active run\n\n"

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
