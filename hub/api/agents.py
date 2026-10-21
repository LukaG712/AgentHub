"""Route module: agents."""

from fastapi import Depends, HTTPException
from hub.api.core import _verify_token
from hub import agents
from hub import skills
from hub.config import load_config, save_config, set_primary_bot, validate_name
from typing import Any, Dict, List, Optional


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


async def api_get_agent(name: str, _auth: None = Depends(_verify_token)):
    try:
        data = agents.get_agent(name)
        return {"name": name, **data}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")


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


async def api_delete_agent(name: str, _auth: None = Depends(_verify_token)):
    try:
        agents.delete_agent_by_name(name)
        return {"deleted": name}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")


# --- Skills ---


async def api_enable_skill(agent: str, skill: str, _auth: None = Depends(_verify_token)):
    try:
        skills.enable_skill(agent, skill)
        skills.sync_agent(agent)
        return {"agent": agent, "skill": skill, "enabled": True}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


async def api_disable_skill(agent: str, skill: str, _auth: None = Depends(_verify_token)):
    try:
        skills.disable_skill(agent, skill)
        skills.sync_agent(agent)
        return {"agent": agent, "skill": skill, "enabled": False}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Runs ---


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



def register(app):
    """Register agents routes with the FastAPI app."""
    app.get("/api/agents")(api_list_agents)
    app.post("/api/agents/generate", status_code=201)(api_generate_agent)
    app.get("/api/agents/{name}")(api_get_agent)
    app.post("/api/agents/{name}", status_code=201)(api_create_agent)
    app.put("/api/agents/{name}")(api_update_agent)
    app.delete("/api/agents/{name}")(api_delete_agent)
    app.post("/api/agents/{agent}/skills/{skill}")(api_enable_skill)
    app.delete("/api/agents/{agent}/skills/{skill}")(api_disable_skill)
    app.post("/api/agents/{name}/runs", status_code=201)(api_dispatch_run)
