"""FastAPI application for the agent hub."""

import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from hub import agents, skills
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


app = FastAPI(title="Agent Hub")


@app.on_event("startup")
async def startup():
    """Recover stale runs on startup."""
    recover_stale_runs()


@app.get("/api/status")
async def api_status(_auth: None = Depends(_verify_token)):
    config = load_config()
    agent_list = []
    for name in config.get("agents", {}):
        status = agent_status(name)
        agent_list.append(status)
    return {"agents": agent_list}


# --- Agents ---


@app.get("/api/agents")
async def api_list_agents(_auth: None = Depends(_verify_token)):
    config = load_config()
    result = []
    for name, data in config.get("agents", {}).items():
        entry = {"name": name}
        for key in ("title", "description", "runner", "project_dir", "skills", "guidelines"):
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
        )
        return {"name": name, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/agents/{name}")
async def api_update_agent(name: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    allowed = {"title", "description", "runner", "project_dir", "skills", "guidelines"}
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
