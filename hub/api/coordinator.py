"""Route module: coordinator."""

from fastapi import Depends, HTTPException
from hub.api.core import _verify_token
from hub import coordinator
from typing import Any, Dict, List, Optional
import uuid


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


async def api_list_coordinators(
    _auth: None = Depends(_verify_token),
):
    """List all active coordinators."""
    return coordinator.list_coordinators()


async def api_get_coordinator(
    coordinator_id: str,
    _auth: None = Depends(_verify_token),
):
    """Get a coordinator's current status."""
    coord = coordinator.get_coordinator(coordinator_id)
    if coord is None:
        raise HTTPException(status_code=404, detail=f"Coordinator '{coordinator_id}' not found")
    return coord.get_summary()


async def api_delete_coordinator(
    coordinator_id: str,
    _auth: None = Depends(_verify_token),
):
    """Remove a coordinator and clean up its worktrees."""
    removed = coordinator.remove_coordinator(coordinator_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Coordinator '{coordinator_id}' not found")
    return {"deleted": coordinator_id}


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



def register(app):
    """Register coordinator routes with the FastAPI app."""
    app.post("/api/coordinator", status_code=201)(api_create_coordinator)
    app.get("/api/coordinator")(api_list_coordinators)
    app.get("/api/coordinator/{coordinator_id}")(api_get_coordinator)
    app.delete("/api/coordinator/{coordinator_id}")(api_delete_coordinator)
    app.post("/api/coordinator/{coordinator_id}/tasks", status_code=201)(api_add_coordinator_task)
    app.delete("/api/coordinator/{coordinator_id}/tasks/{task_id}")(api_remove_coordinator_task)
    app.post("/api/coordinator/{coordinator_id}/execute")(api_execute_coordinator)
    app.post("/api/coordinator/{coordinator_id}/cancel")(api_cancel_coordinator)
    app.post("/api/coordinator/{coordinator_id}/tasks/{task_id}/approve")(api_approve_task)
    app.post("/api/coordinator/{coordinator_id}/tasks/{task_id}/reject")(api_reject_task)
