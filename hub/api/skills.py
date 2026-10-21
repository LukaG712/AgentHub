"""Route module: skills."""

from fastapi import Depends, HTTPException
from hub.api.core import _verify_token
from hub import skills
from typing import Any, Dict, List, Optional


async def api_list_skills(_auth: None = Depends(_verify_token)):
    skill_list = skills.list_skills()
    for s in skill_list:
        s["used_by"] = skills.skill_usage(s["name"])
    return {"skills": skill_list}


async def api_get_skill(name: str, _auth: None = Depends(_verify_token)):
    skill_path = skills._skill_path(name)
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    content = skill_md.read_text(encoding="utf-8")
    return {"name": name, "content": content, "used_by": skills.skill_usage(name)}


async def api_create_skill(name: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    content = body.get("content", "")
    description = body.get("description", "")
    try:
        result = skills.create_skill(name, description=description, content=content)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_update_skill(name: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    content = body.get("content", "")
    description = body.get("description", "")
    try:
        result = skills.update_skill(name, description=description, content=content)
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")


async def api_delete_skill(name: str, _auth: None = Depends(_verify_token)):
    try:
        skills.delete_skill(name)
        return {"deleted": name}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")


# --- Agent Skills ---



def register(app):
    """Register skills routes with the FastAPI app."""
    app.get("/api/skills")(api_list_skills)
    app.get("/api/skills/{name}")(api_get_skill)
    app.post("/api/skills/{name}", status_code=201)(api_create_skill)
    app.put("/api/skills/{name}")(api_update_skill)
    app.delete("/api/skills/{name}")(api_delete_skill)
