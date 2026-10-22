"""Route module: agent harness (Specs, Droids, Skills, Hooks, Environments).

REST API endpoints for Phase 11 components:
- Specs: Research-before-implementation plans
- Droids: Custom subagent definitions
- Skills: Reusable workflow packages
- Hooks: Event-driven lifecycle automation
- Environments: Reusable sandbox definitions
"""

from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException

from hub.api.core import _verify_token
from hub.mission import droids as droids_module
from hub.mission import environments as env_module
from hub.mission import hooks as hooks_module
from hub.mission import skills as skills_module
from hub.mission import spec_mode

# ─── Specs ───────────────────────────────────────────────────────────────────


async def api_create_spec(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Create a new spec (research plan)."""
    try:
        spec = spec_mode.create_spec(
            title=body.get("title", ""),
            description=body.get("description", ""),
            target_repository=body.get("target_repository", ""),
            created_by=body.get("created_by", "api"),
            model_override=body.get("model_override"),
        )
        return spec.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_list_specs(
    status: Optional[str] = None,
    target_repository: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    _auth: None = Depends(_verify_token),
):
    """List specs with optional filters."""
    specs = spec_mode.list_specs(
        status=status,
        target_repository=target_repository,
        limit=limit,
        offset=offset,
    )
    return {"specs": [s.to_dict() for s in specs]}


async def api_get_spec(spec_id: str, _auth: None = Depends(_verify_token)):
    """Get a spec by ID."""
    spec = spec_mode.get_spec(spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Spec not found")
    return spec.to_dict()


async def api_research_spec(spec_id: str, _auth: None = Depends(_verify_token)):
    """Run the research phase for a spec."""
    try:
        spec = spec_mode.research_spec(spec_id)
        return spec.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_approve_spec(spec_id: str, _auth: None = Depends(_verify_token)):
    """Approve a spec for implementation."""
    try:
        spec = spec_mode.approve_spec(spec_id)
        return spec.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_reject_spec(spec_id: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Reject a spec with feedback."""
    feedback = body.get("feedback", "").strip()
    if not feedback:
        raise HTTPException(status_code=400, detail="feedback is required")
    try:
        spec = spec_mode.reject_spec(spec_id, feedback)
        return spec.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_convert_spec(spec_id: str, _auth: None = Depends(_verify_token)):
    """Convert an approved spec to a mission."""
    try:
        mission = spec_mode.convert_spec_to_mission(spec_id, created_by="api")
        return mission.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_delete_spec(spec_id: str, _auth: None = Depends(_verify_token)):
    """Delete a spec."""
    deleted = spec_mode.delete_spec(spec_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Spec not found")
    return {"status": "ok"}


async def api_get_spec_stats(_auth: None = Depends(_verify_token)):
    """Get spec statistics."""
    return spec_mode.get_spec_stats()


# ─── Droids ──────────────────────────────────────────────────────────────────


async def api_list_droids(_auth: None = Depends(_verify_token)):
    """List all available droids (built-in and custom)."""
    all_droids = droids_module.discover_droids()
    stored = droids_module.list_stored_droids()
    result = []
    seen = set()
    for d in all_droids:
        if d.name not in seen:
            result.append(d.to_dict())
            seen.add(d.name)
    return {"droids": result}


async def api_get_droid(droid_name: str, _auth: None = Depends(_verify_token)):
    """Get a droid by name."""
    droid = droids_module.get_droid(droid_name)
    if droid is None:
        droid = droids_module.get_stored_droid(droid_name)
    if droid is None:
        raise HTTPException(status_code=404, detail="Droid not found")
    return droid.to_dict()


async def api_create_droid(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Create a custom droid."""
    try:
        droid = droids_module.create_droid(
            name=body.get("name", ""),
            description=body.get("description", ""),
            system_prompt=body.get("system_prompt", ""),
            model=body.get("model"),
            allowed_tools=body.get("allowed_tools"),
            denied_tools=body.get("denied_tools"),
        )
        return droid.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_delete_droid(droid_name: str, _auth: None = Depends(_verify_token)):
    """Delete a custom droid."""
    try:
        deleted = droids_module.delete_stored_droid(droid_name)
        if not deleted:
            raise HTTPException(status_code=404, detail="Droid not found")
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_invoke_droid(droid_name: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Invoke a droid to perform a task."""
    try:
        result = droids_module.invoke_droid(
            name=droid_name,
            task=body.get("task", ""),
            context=body.get("context"),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Skills ──────────────────────────────────────────────────────────────────


async def api_list_skills(_auth: None = Depends(_verify_token)):
    """List all available skills."""
    discovered = skills_module.discover_skills()
    stored = skills_module.list_stored_skills()
    result = []
    seen = set()
    for s in discovered:
        if s.name not in seen:
            result.append(s.to_dict())
            seen.add(s.name)
    for s in stored:
        if s.name not in seen:
            result.append(s.to_dict())
            seen.add(s.name)
    return {"skills": result}


async def api_get_skill(skill_name: str, _auth: None = Depends(_verify_token)):
    """Get a skill by name."""
    skill = skills_module.get_skill(skill_name)
    if skill is None:
        skill = skills_module.get_stored_skill(skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill.to_dict()


async def api_create_skill(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Create a new skill."""
    try:
        skill = skills_module.create_skill(
            name=body.get("name", ""),
            description=body.get("description", ""),
            instructions=body.get("instructions", ""),
            triggers=body.get("triggers"),
            user_invocable=body.get("user_invocable", False),
        )
        return skill.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_delete_skill(skill_name: str, _auth: None = Depends(_verify_token)):
    """Delete a skill."""
    deleted = skills_module.delete_stored_skill(skill_name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"status": "ok"}


async def api_invoke_skill(skill_name: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Invoke a skill for a task."""
    try:
        result = skills_module.invoke_skill(
            name=skill_name,
            task=body.get("task", ""),
            context=body.get("context"),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_match_skills(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Match skills to a task description."""
    task = body.get("task", "")
    matched = skills_module.match_skills(task)
    return {"matched_skills": [s.to_dict() for s in matched]}


# ─── Hooks ───────────────────────────────────────────────────────────────────


async def api_list_hooks(
    event: Optional[str] = None,
    _auth: None = Depends(_verify_token),
):
    """List hooks with optional event filter."""
    hooks = hooks_module.list_hooks(event=event)
    return {"hooks": [h.to_dict() for h in hooks]}


async def api_get_hook(hook_id: str, _auth: None = Depends(_verify_token)):
    """Get a hook by ID."""
    hook = hooks_module.get_hook(hook_id)
    if hook is None:
        raise HTTPException(status_code=404, detail="Hook not found")
    return hook.to_dict()


async def api_create_hook(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Create a new hook."""
    try:
        hook = hooks_module.create_hook(
            name=body.get("name", ""),
            event=body.get("event", ""),
            hook_type=body.get("hook_type", "script"),
            target=body.get("target", ""),
            description=body.get("description", ""),
            env_vars=body.get("env_vars"),
            can_block=body.get("can_block", False),
            timeout=body.get("timeout", 30),
        )
        return hook.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_delete_hook(hook_id: str, _auth: None = Depends(_verify_token)):
    """Delete a hook."""
    deleted = hooks_module.delete_hook(hook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Hook not found")
    return {"status": "ok"}


async def api_test_hook(hook_id: str, body: Optional[Dict[str, Any]] = None, _auth: None = Depends(_verify_token)):
    """Test a hook (dry-run)."""
    try:
        result = hooks_module.test_hook(hook_id, context=body)
        return result.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_get_hook_executions(hook_id: str, limit: int = 50, _auth: None = Depends(_verify_token)):
    """Get execution history for a hook."""
    executions = hooks_module.get_hook_executions(hook_id, limit=limit)
    return {"executions": [e.to_dict() for e in executions]}


# ─── Environments ────────────────────────────────────────────────────────────


async def api_list_environments(_auth: None = Depends(_verify_token)):
    """List all environments."""
    envs = env_module.list_environments()
    return {"environments": [e.to_dict() for e in envs]}


async def api_get_environment(env_id: str, _auth: None = Depends(_verify_token)):
    """Get an environment by ID."""
    env = env_module.get_environment(env_id)
    if env is None:
        raise HTTPException(status_code=404, detail="Environment not found")
    return env.to_dict()


async def api_create_environment(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Create a new environment."""
    try:
        env = env_module.create_environment(
            name=body.get("name", ""),
            repository=body.get("repository", ""),
            description=body.get("description", ""),
            branch=body.get("branch", "main"),
            python_version=body.get("python_version", ""),
            node_version=body.get("node_version", ""),
            dependencies=body.get("dependencies"),
            setup_commands=body.get("setup_commands"),
            build_command=body.get("build_command", ""),
            test_command=body.get("test_command", ""),
            env_var_keys=body.get("env_var_keys"),
            required_services=body.get("required_services"),
            health_check_command=body.get("health_check_command", ""),
        )
        return env.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_delete_environment(env_id: str, _auth: None = Depends(_verify_token)):
    """Delete an environment."""
    deleted = env_module.delete_environment(env_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Environment not found")
    return {"status": "ok"}


async def api_validate_environment(env_id: str, _auth: None = Depends(_verify_token)):
    """Validate an environment (health check)."""
    try:
        result = env_module.validate_environment(env_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Registration ────────────────────────────────────────────────────────────


def register(app):
    """Register all agent harness routes."""

    # Specs
    app.add_api_route("/api/specs", api_create_spec, methods=["POST"])
    app.add_api_route("/api/specs", api_list_specs, methods=["GET"])
    app.add_api_route("/api/specs/stats", api_get_spec_stats, methods=["GET"])
    app.add_api_route("/api/specs/{spec_id}", api_get_spec, methods=["GET"])
    app.add_api_route("/api/specs/{spec_id}", api_delete_spec, methods=["DELETE"])
    app.add_api_route("/api/specs/{spec_id}/research", api_research_spec, methods=["POST"])
    app.add_api_route("/api/specs/{spec_id}/approve", api_approve_spec, methods=["POST"])
    app.add_api_route("/api/specs/{spec_id}/reject", api_reject_spec, methods=["POST"])
    app.add_api_route("/api/specs/{spec_id}/convert", api_convert_spec, methods=["POST"])

    # Droids
    app.add_api_route("/api/droids", api_list_droids, methods=["GET"])
    app.add_api_route("/api/droids", api_create_droid, methods=["POST"])
    app.add_api_route("/api/droids/{droid_name}", api_get_droid, methods=["GET"])
    app.add_api_route("/api/droids/{droid_name}", api_delete_droid, methods=["DELETE"])
    app.add_api_route("/api/droids/{droid_name}/invoke", api_invoke_droid, methods=["POST"])

    # Skills
    app.add_api_route("/api/skills", api_list_skills, methods=["GET"])
    app.add_api_route("/api/skills", api_create_skill, methods=["POST"])
    app.add_api_route("/api/skills/match", api_match_skills, methods=["POST"])
    app.add_api_route("/api/skills/{skill_name}", api_get_skill, methods=["GET"])
    app.add_api_route("/api/skills/{skill_name}", api_delete_skill, methods=["DELETE"])
    app.add_api_route("/api/skills/{skill_name}/invoke", api_invoke_skill, methods=["POST"])

    # Hooks
    app.add_api_route("/api/hooks", api_list_hooks, methods=["GET"])
    app.add_api_route("/api/hooks", api_create_hook, methods=["POST"])
    app.add_api_route("/api/hooks/{hook_id}", api_get_hook, methods=["GET"])
    app.add_api_route("/api/hooks/{hook_id}", api_delete_hook, methods=["DELETE"])
    app.add_api_route("/api/hooks/{hook_id}/test", api_test_hook, methods=["POST"])
    app.add_api_route("/api/hooks/{hook_id}/executions", api_get_hook_executions, methods=["GET"])

    # Environments
    app.add_api_route("/api/environments", api_list_environments, methods=["GET"])
    app.add_api_route("/api/environments", api_create_environment, methods=["POST"])
    app.add_api_route("/api/environments/{env_id}", api_get_environment, methods=["GET"])
    app.add_api_route("/api/environments/{env_id}", api_delete_environment, methods=["DELETE"])
    app.add_api_route("/api/environments/{env_id}/validate", api_validate_environment, methods=["POST"])
