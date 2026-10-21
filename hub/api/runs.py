"""Route module: runs."""

from fastapi import Depends, HTTPException
from hub.api.core import _verify_token
from hub.runner import Run, agent_status, get_run, list_runs, recover_stale_runs, run_agent, stop_run
from typing import Any, Dict, List, Optional


async def api_list_runs(
    agent: Optional[str] = None,
    state: Optional[str] = None,
    _auth: None = Depends(_verify_token),
):
    runs = list_runs(agent=agent, state=state)
    return {"runs": [r.to_dict() for r in runs]}


async def api_get_run(run_id: str, _auth: None = Depends(_verify_token)):
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run.to_dict()


async def api_stop_run(run_id: str, _auth: None = Depends(_verify_token)):
    run = stop_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run.to_dict()


# --- Sessions ---



def register(app):
    """Register runs routes with the FastAPI app."""
    app.get("/api/runs")(api_list_runs)
    app.get("/api/runs/{run_id}")(api_get_run)
    app.post("/api/runs/{run_id}/stop")(api_stop_run)
