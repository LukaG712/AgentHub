"""Route module: obsidian."""

from fastapi import Depends, HTTPException
from hub.api.core import _verify_token
from hub import memory
from typing import Any, Dict, List, Optional


async def api_obsidian_status(_auth: None = Depends(_verify_token)):
    """Check if Obsidian integration is configured and available."""
    vault = _get_obsidian_vault()
    if vault is None:
        return {"enabled": False, "available": False}
    return {
        "enabled": True,
        "available": vault.is_valid(),
        "vault_path": str(vault.vault_path),
    }


async def api_obsidian_list_notes(
    q: Optional[str] = None,
    tag: Optional[str] = None,
    folder: Optional[str] = None,
    limit: int = 50,
    _auth: None = Depends(_verify_token),
):
    """List notes from the Obsidian vault."""
    vault = _get_obsidian_vault()
    if vault is None:
        raise HTTPException(status_code=400, detail="Obsidian integration is not configured")
    notes = vault.list_notes(query=q, tag=tag, folder=folder, limit=limit)
    return {"notes": [note.to_dict() for note in notes]}


async def api_obsidian_get_note(
    note_id: str,
    _auth: None = Depends(_verify_token),
):
    """Get a note's content from the Obsidian vault."""
    vault = _get_obsidian_vault()
    if vault is None:
        raise HTTPException(status_code=400, detail="Obsidian integration is not configured")
    content = vault.read_note_content(note_id)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Note '{note_id}' not found")
    note = vault.get_note(note_id)
    return {
        "id": note.note_id if note else note_id,
        "title": note.title if note else note_id,
        "path": note.relative_path if note else note_id,
        "content": content,
    }


async def api_obsidian_sync_session(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Write a session summary to the Obsidian vault."""
    vault = _get_obsidian_vault()
    if vault is None:
        raise HTTPException(status_code=400, detail="Obsidian integration is not configured")

    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    # Get session details
    session = memory.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    messages = memory.get_session_messages(session_id)
    title = session.get("title", "Untitled Session")

    note = vault.write_session_summary(session_id, title, messages)
    if note is None:
        raise HTTPException(status_code=500, detail="Failed to write session summary to Obsidian")

    return {"note": note.to_dict()}


# --- Remote Execution ---



def register(app):
    """Register obsidian routes with the FastAPI app."""
    app.get("/api/obsidian/status")(api_obsidian_status)
    app.get("/api/obsidian/notes")(api_obsidian_list_notes)
    app.get("/api/obsidian/notes/{note_id}")(api_obsidian_get_note)
    app.post("/api/obsidian/sync", status_code=201)(api_obsidian_sync_session)
