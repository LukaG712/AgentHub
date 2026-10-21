"""Route module: memories."""

from fastapi import Depends, HTTPException
from hub.api.core import _verify_token
from hub import memory
from typing import Any, Dict, List, Optional
import time


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


async def api_delete_memory(
    memory_id: str,
    _auth: None = Depends(_verify_token),
):
    deleted = memory.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")
    return {"deleted": memory_id}


# --- Providers ---



def register(app):
    """Register memories routes with the FastAPI app."""
    app.get("/api/memories")(api_list_memories)
    app.post("/api/memories", status_code=201)(api_create_memory)
    app.put("/api/memories/{memory_id}")(api_update_memory)
    app.delete("/api/memories/{memory_id}")(api_delete_memory)
