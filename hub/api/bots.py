"""Route module: bots."""

from fastapi import Depends, HTTPException
from hub.api.core import _verify_token
from hub import agents
from hub import bot_memory
from hub import memory
from hub.config import load_config, save_config, set_primary_bot, validate_name
from typing import Any, Dict, List, Optional


async def api_pause_bot(bot_id: str, _auth: None = Depends(_verify_token)):
    try:
        agents.get_agent(bot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    from hub import queue_manager
    queue_manager.pause_bot(bot_id)
    return {"status": "paused", "bot": bot_id}


async def api_resume_bot(bot_id: str, _auth: None = Depends(_verify_token)):
    try:
        agents.get_agent(bot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    from hub import queue_manager
    queue_manager.resume_bot(bot_id)
    return {"status": "resumed", "bot": bot_id}


async def api_get_bot_queue(bot_id: str, _auth: None = Depends(_verify_token)):
    try:
        agents.get_agent(bot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    from hub import queue_manager
    items = queue_manager.get_bot_queue(bot_id)
    return {
        "bot": bot_id,
        "paused": queue_manager.is_bot_paused(bot_id),
        "queue": items,
    }


# --- SSE streaming ---


async def api_get_bot_memory(
    bot_id: str,
    _auth: None = Depends(_verify_token),
):
    """Get the per-Bot memory file content."""
    config = load_config()
    agents_cfg = config.get("agents", {})
    if bot_id not in agents_cfg:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    content = bot_memory.read_bot_memory(bot_id)
    return {"content": content}


async def api_update_bot_memory(
    bot_id: str,
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Update the per-Bot memory file content."""
    config = load_config()
    agents_cfg = config.get("agents", {})
    if bot_id not in agents_cfg:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    content = body.get("content", "")
    bot_memory.write_bot_memory(bot_id, content)
    return {"content": content}


async def api_propose_memory_update(
    bot_id: str,
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Propose a memory update for a bot.

    Saves the previous content for undo, writes the new content,
    and adds a system message to the session.
    Expects: content (required), session_id (required), optional run_id.
    """
    config = load_config()
    agents_cfg = config.get("agents", {})
    if bot_id not in agents_cfg:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    content = body.get("content", "")
    session_id = body.get("session_id", "")
    run_id = body.get("run_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    msg = memory.propose_memory_update(
        bot_id=bot_id,
        session_id=session_id,
        new_content=content,
        run_id=run_id,
    )
    return {"message": msg, "content": content}


async def api_undo_memory_update(
    bot_id: str,
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Undo a previous memory update by restoring the old content.

    Expects: session_id (required), previous_content (required).
    """
    config = load_config()
    agents_cfg = config.get("agents", {})
    if bot_id not in agents_cfg:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    session_id = body.get("session_id", "")
    previous_content = body.get("previous_content", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    msg = memory.undo_memory_update(
        bot_id=bot_id,
        session_id=session_id,
        previous_content=previous_content,
    )
    return {"message": msg, "content": previous_content}


# --- Built-in App: Task Manager ---



def register(app):
    """Register bots routes with the FastAPI app."""
    app.post("/api/bots/{bot_id}/pause")(api_pause_bot)
    app.post("/api/bots/{bot_id}/resume")(api_resume_bot)
    app.get("/api/bots/{bot_id}/queue")(api_get_bot_queue)
    app.get("/api/bots/{bot_id}/memory")(api_get_bot_memory)
    app.put("/api/bots/{bot_id}/memory")(api_update_bot_memory)
    app.post("/api/bots/{bot_id}/memory/propose")(api_propose_memory_update)
    app.post("/api/bots/{bot_id}/memory/undo")(api_undo_memory_update)
