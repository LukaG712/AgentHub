"""Route module: ollama."""

from fastapi import Depends, HTTPException
from hub.api.core import _verify_token
from hub import obsidian
from hub.config import load_config, save_config, set_primary_bot, validate_name
from pathlib import Path
from typing import Any, Dict, List, Optional


async def api_ollama_status(_auth: None = Depends(_verify_token)):
    """Check if Ollama integration is configured and available."""
    client = _get_ollama_client()
    if client is None:
        return {"enabled": False, "available": False}
    return {
        "enabled": True,
        "available": client.is_available(),
        "base_url": client.base_url,
        "model": client.model,
    }


async def api_ollama_refine(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Refine a prompt using Ollama for clarity and completeness."""
    client = _get_ollama_client()
    if client is None:
        raise HTTPException(status_code=400, detail="Ollama integration is not configured")

    prompt = body.get("prompt", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    context = body.get("context", "")
    system_instruction = body.get("system_instruction", "")

    refined = client.refine_prompt(
        prompt=prompt,
        context=context or None,
        system_instruction=system_instruction or None,
    )

    return {
        "original": prompt,
        "refined": refined,
        "changed": refined != prompt,
    }


async def api_ollama_summarize(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Summarize text using Ollama."""
    client = _get_ollama_client()
    if client is None:
        raise HTTPException(status_code=400, detail="Ollama integration is not configured")

    text = body.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    max_length = body.get("max_length", 500)
    focus = body.get("focus", "")

    summary = client.summarize(
        text=text,
        max_length=max_length,
        focus=focus or None,
    )

    return {"summary": summary}


async def api_ollama_decompose(
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Decompose a complex task into subtasks using Ollama."""
    client = _get_ollama_client()
    if client is None:
        raise HTTPException(status_code=400, detail="Ollama integration is not configured")

    task = body.get("task", "")
    if not task:
        raise HTTPException(status_code=400, detail="task is required")

    context = body.get("context", "")

    subtasks = client.decompose_task(
        task=task,
        context=context or None,
    )

    return {"subtasks": subtasks}


# --- Obsidian ---


def _get_obsidian_vault() -> Optional[obsidian.ObsidianVault]:
    """Get the Obsidian vault from config."""
    config = load_config()
    obs_cfg = config.get("obsidian", {})
    if not obs_cfg.get("enabled", False):
        return None
    vault_path = obs_cfg.get("vault_path", "")
    if not vault_path:
        return None
    vault = obsidian.ObsidianVault(Path(vault_path))
    return vault if vault.enabled else None



def register(app):
    """Register ollama routes with the FastAPI app."""
    app.get("/api/ollama/status")(api_ollama_status)
    app.post("/api/ollama/refine")(api_ollama_refine)
    app.post("/api/ollama/summarize")(api_ollama_summarize)
    app.post("/api/ollama/decompose")(api_ollama_decompose)
