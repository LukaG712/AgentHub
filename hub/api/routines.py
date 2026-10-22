"""Route module: routines."""

from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException

from hub import memory
from hub import routines as routines_engine
from hub.api.core import _verify_token
from hub.runner import Run, agent_status, get_run, list_runs, recover_stale_runs, run_agent, stop_run


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


async def api_list_routines(
    bot_id: Optional[str] = None,
    _auth: None = Depends(_verify_token),
):
    routines_list = memory.list_routines(bot_id=bot_id)
    return {"routines": routines_list}


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


async def api_delete_routine(
    routine_id: str,
    _auth: None = Depends(_verify_token),
):
    deleted = memory.delete_routine(routine_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Routine '{routine_id}' not found")
    return {"deleted": routine_id}


async def api_run_routine_now(
    routine_id: str,
    _auth: None = Depends(_verify_token),
):
    result = routines_engine.run_routine_now(routine_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Routine '{routine_id}' not found")
    return result


# --- Approvals ---



def register(app):
    """Register routines routes with the FastAPI app."""
    app.post("/api/routines/teach", status_code=201)(api_teach_as_routine)
    app.get("/api/routines")(api_list_routines)
    app.post("/api/routines", status_code=201)(api_create_routine)
    app.put("/api/routines/{routine_id}")(api_update_routine)
    app.delete("/api/routines/{routine_id}")(api_delete_routine)
    app.post("/api/routines/{routine_id}/run-now")(api_run_routine_now)
