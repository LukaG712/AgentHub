"""Route module: app."""

from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException

from hub import app as app_module
from hub.api.core import _verify_token


async def api_list_tasks(_auth: None = Depends(_verify_token)):
    """List all tasks."""
    from hub import app as app_module
    tasks = app_module.list_tasks()
    return {"tasks": tasks}


async def api_create_task(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Create a new task."""
    from hub import app as app_module
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    description = body.get("description", "")
    task = app_module.create_task(title, description)
    return task


async def api_update_task(task_id: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Update a task (toggle done, edit title/description)."""
    from hub import app as app_module
    task = app_module.update_task(task_id, **body)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


async def api_delete_task(task_id: str, _auth: None = Depends(_verify_token)):
    """Delete a task."""
    from hub import app as app_module
    if not app_module.delete_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": True}


# --- Static files ---



def register(app):
    """Register app routes with the FastAPI app."""
    app.get("/api/app/tasks")(api_list_tasks)
    app.post("/api/app/tasks")(api_create_task)
    app.patch("/api/app/tasks/{task_id}")(api_update_task)
    app.delete("/api/app/tasks/{task_id}")(api_delete_task)
