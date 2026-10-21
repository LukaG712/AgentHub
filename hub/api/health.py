"""Route module: health."""

from fastapi import Depends, HTTPException
from starlette.responses import JSONResponse
from hub.api.core import (
    _analytics,
    _api_versions,
    _audit_log,
    _circuit_breakers,
    _dag_definitions,
    _deployments,
    _feature_flags,
    _message_bus,
    _response_cache,
    _templates,
    _tenants,
    _validate_startup,
    _verify_token,
    _webhooks,
)
from hub import llm_providers as llm_module
from hub import memory
from hub import ollama
from hub import providers
from hub import routines as routines_engine
from hub.config import load_config, save_config, set_primary_bot, validate_name
from hub.runner import Run, agent_status, get_run, list_runs, recover_stale_runs, run_agent, stop_run
from pathlib import Path
from typing import Any, Dict, List, Optional
import asyncio
import httpx
import time


async def api_Ecton_health():
    """Check if the Ecton service is reachable."""
    import os
    import httpx
    base_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/health")
            return {"service": "Ecton", "status": "ok" if resp.status_code == 200 else "error", "url": base_url}
    except Exception as e:
        return {"service": "Ecton", "status": "unreachable", "error": str(e), "url": base_url}


async def api_Spectra_health():
    """Check if the Spectra service is reachable."""
    import os
    import httpx
    base_url = os.environ.get("Spectra_URL", "http://localhost:3000").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/health")
            return {"service": "Spectra", "status": "ok" if resp.status_code == 200 else "error", "url": base_url}
    except Exception as e:
        return {"service": "Spectra", "status": "unreachable", "error": str(e), "url": base_url}


async def api_integration_health():
    """Check health of all integrated services."""
    import asyncio
    Ecton_task = asyncio.create_task(api_Ecton_health())
    Spectra_task = asyncio.create_task(api_Spectra_health())
    Ecton_status, Spectra_status = await asyncio.gather(Ecton_task, Spectra_task)
    return {
        "Evershade Valley": {"status": "ok", "version": "1.0.3"},
        "Ecton": Ecton_status,
        "Spectra": Spectra_status,
    }


# ─── Spectra proxy endpoints ──────────────────────────────────────────────


async def api_health():
    """Health check endpoint — unauthenticated, safe for systemd/load balancer.

    Reports service status, database connectivity, downstream services,
    memory usage, and feature store sizes for comprehensive self-diagnostics.
    """
    import sys
    import tracemalloc

    health = {
        "status": "ok",
        "version": "1.0.3",
        "service": "Evershade Valley",
    }

    # Database status
    db_status = {"status": "ok"}
    try:
        from hub.memory import _DB_PATH as evershade_valley_db
        db_path = Path(evershade_valley_db)
        if db_path.exists():
            db_status["file"] = str(db_path)
            db_status["size_bytes"] = db_path.stat().st_size
        else:
            db_status["status"] = "not_found"
            db_status["message"] = "Database file not yet created"
    except Exception as e:
        db_status["status"] = "error"
        db_status["error"] = str(e)
    health["database"] = db_status

    # Downstream services
    downstream = {}
    import httpx
    for service_name, env_var, default_url in [
        ("Ecton", "Ecton_URL", "http://localhost:8000"),
        ("Spectra", "Spectra_URL", "http://localhost:3000"),
    ]:
        base_url = os.environ.get(env_var, default_url).rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{base_url}/health")
                downstream[service_name] = {
                    "status": "ok" if resp.status_code == 200 else "error",
                    "url": base_url,
                }
        except Exception:
            downstream[service_name] = {"status": "unreachable", "url": base_url}
    health["downstream"] = downstream

    # Memory usage
    mem_info = {}
    try:
        mem_info["rss_bytes"] = os.popen(f"ps -o rss= -p {os.getpid()}").read().strip() or "unknown"
    except Exception:
        pass
    health["memory"] = mem_info

    # Feature store sizes
    stores = {}
    try:
        from hub.api import (
            _webhooks, _analytics_events, _rate_limit_store,
            _audit_log, _templates, _approvals, _file_uploads,
            _roles, _users, _response_cache, _message_bus_topics,
            _feature_flags, _deployments, _circuit_breakers,
            _api_versions, _dag_definitions, _tenants,
        )
        stores["webhooks"] = len(_webhooks)
        stores["analytics_events"] = len(_analytics_events)
        stores["rate_limits"] = len(_rate_limit_store)
        stores["audit_log"] = len(_audit_log)
        stores["templates"] = len(_templates)
        stores["approvals"] = len(_approvals)
        stores["file_uploads"] = len(_file_uploads)
        stores["roles"] = len(_roles)
        stores["users"] = len(_users)
        stores["response_cache"] = len(_response_cache)
        stores["message_bus_topics"] = len(_message_bus_topics)
        stores["feature_flags"] = len(_feature_flags)
        stores["deployments"] = len(_deployments)
        stores["circuit_breakers"] = len(_circuit_breakers)
        stores["api_versions"] = len(_api_versions)
        stores["dag_definitions"] = len(_dag_definitions)
        stores["tenants"] = len(_tenants)
    except Exception:
        pass
    health["stores"] = stores

    # Observability status
    observability = {}
    if tracing_module is not None:
        observability["tracing"] = "enabled"
    else:
        observability["tracing"] = "disabled"
    if metrics_module is not None:
        observability["metrics"] = "enabled"
    else:
        observability["metrics"] = "disabled"
    health["observability"] = observability

    # Cluster status
    try:
        from hub import cluster as cluster_module
        health["cluster"] = cluster_module.cluster.status()
    except Exception:
        health["cluster"] = {"available": False, "message": "Cluster module not available"}

    # Marketplace status
    try:
        from hub import marketplace as marketplace_module
        health["marketplace"] = marketplace_module.registry.get_stats()
    except Exception:
        health["marketplace"] = {"available": False, "message": "Marketplace module not available"}

    return health


# ─── Readiness Check ─────────────────────────────────────────────────────────

async def api_ready():
    """Readiness check — verifies SQLite connectivity and config validity."""
    issues = []
    # Check SQLite connectivity
    try:
        memory.get_connection()
        memory.close_connection()
    except Exception as e:
        issues.append({"component": "database", "error": str(e)})
    # Check config validity
    try:
        config = load_config()
        if not config.get("agents"):
            issues.append({"component": "config", "warning": "No agents configured"})
    except Exception as e:
        issues.append({"component": "config", "error": str(e)})

    ready = len([i for i in issues if "error" in i]) == 0
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"ready": ready, "issues": issues},
    )


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


async def api_list_projects(
    _auth: None = Depends(_verify_token),
):
    projects = memory.discover_projects()
    return {"projects": projects}


# --- Ollama ---


def _get_ollama_client() -> Optional[ollama.OllamaClient]:
    """Get the Ollama client from config."""
    return ollama.get_ollama_client()



def register(app):
    """Register health routes with the FastAPI app."""
    app.get("/api/integration/Ecton/health")(api_Ecton_health)
    app.get("/api/integration/Spectra/health")(api_Spectra_health)
    app.get("/api/integration/health")(api_integration_health)
    app.get("/api/health")(api_health)
    app.get("/api/ready")(api_ready)
    app.get("/api/ready")(api_ready)
    app.get("/api/status")(api_status)
    app.post("/api/primary-bot")(api_set_primary_bot)
    app.get("/api/providers")(api_list_providers)
    app.get("/api/projects")(api_list_projects)
