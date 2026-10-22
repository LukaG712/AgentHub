"""Plugin registry API routes for Greenie."""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from hub.plugins import plugin_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plugins", tags=["Plugins"])


@router.get("/")
async def list_plugins():
    """List all installed plugins."""
    plugins = plugin_registry.list_all()
    return {"plugins": [p.to_dict() for p in plugins]}


@router.post("/")
async def install_plugin(data: Dict[str, Any]):
    """Install a new plugin."""
    name = data.get("name")
    source = data.get("source")
    if not name or not source:
        raise HTTPException(status_code=400, detail="name and source are required")
    plugin_type = data.get("type", "tool")
    description = data.get("description", "")
    version = data.get("version", "1.0.0")
    config = data.get("config", {})
    plugin = plugin_registry.install(name, source, plugin_type, description, version, config)
    return {"plugin": plugin.to_dict()}


@router.get("/{plugin_id}")
async def get_plugin(plugin_id: str):
    """Get a plugin by ID."""
    plugin = plugin_registry.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id} not found")
    return {"plugin": plugin.to_dict()}


@router.patch("/{plugin_id}")
async def update_plugin(plugin_id: str, data: Dict[str, Any]):
    """Update a plugin's configuration or enabled state."""
    plugin = plugin_registry.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id} not found")

    if "enabled" in data:
        if data["enabled"]:
            plugin_registry.enable(plugin_id)
        else:
            plugin_registry.disable(plugin_id)

    if "config" in data:
        plugin_registry.update_config(plugin_id, data["config"])

    plugin = plugin_registry.get(plugin_id)
    return {"plugin": plugin.to_dict()}


@router.delete("/{plugin_id}")
async def uninstall_plugin(plugin_id: str):
    """Uninstall a plugin."""
    if not plugin_registry.uninstall(plugin_id):
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id} not found")
    return {"message": f"Plugin {plugin_id} uninstalled"}


@router.get("/types")
async def list_plugin_types():
    """List available plugin types."""
    return {
        "types": [
            {"type": "tool", "description": "Adds a tool callable by agents"},
            {"type": "resource", "description": "Provides a data resource"},
            {"type": "prompt", "description": "Adds a prompt template"},
            {"type": "integration", "description": "Integrates with an external service"},
        ]
    }


def register(app):
    """Register plugin routes with the FastAPI app."""
    app.include_router(router)
