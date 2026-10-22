"""Plugin system for dynamic provider loading.

Loads Python modules from a configurable plugins directory at startup,
allowing new providers to be added without modifying core code.

Directory structure:
    plugins/
        my_provider/
            __init__.py      # Required, can be empty
            provider.py       # Must contain a Provider class
            manifest.json     # Optional metadata (name, version, description)

Each provider module must export a class that follows the provider interface:
    - name: str — unique provider identifier
    - check_available() -> bool — whether the provider is ready
    - run(task: str, **kwargs) -> str — execute a task synchronously
    - async_run(task: str, **kwargs) -> str — execute a task asynchronously

Configuration:
    PLUGINS_DIR: Path to plugins directory (default: "plugins" relative to working dir)
    PLUGINS_ENABLED: Set to "false" to disable plugin loading (default: true)

Usage:
    from hub.plugins import load_plugins, list_plugins, get_plugin
    load_plugins()  # Called at startup
    providers = list_plugins()  # List loaded plugin names
    plugin = get_plugin("my_provider")  # Get a specific plugin
"""

import importlib
import importlib.util
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


# ─── Configuration ───────────────────────────────────────────────────────────

_PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"
_PLUGINS_ENABLED = os.environ.get("PLUGINS_ENABLED", "true").lower() != "false"

# ─── State ───────────────────────────────────────────────────────────────────

_loaded_plugins: Dict[str, Any] = {}
_plugin_lock = threading.Lock()
_plugin_manifests: Dict[str, Dict[str, Any]] = {}


# ─── Provider Interface ──────────────────────────────────────────────────────

def _is_valid_provider(cls: Type) -> bool:
    """Check if a class implements the provider interface."""
    required = {"name", "check_available", "run"}
    if not hasattr(cls, "name"):
        return False
    if not hasattr(cls, "check_available"):
        return False
    if not hasattr(cls, "run"):
        return False
    return True


# ─── Manifest Loading ────────────────────────────────────────────────────────

def _load_manifest(plugin_dir: Path) -> Dict[str, Any]:
    """Load manifest.json if it exists."""
    manifest_path = plugin_dir / "manifest.json"
    if manifest_path.exists():
        try:
            with open(manifest_path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to load manifest for {plugin_dir.name}: {e}")
    return {"name": plugin_dir.name, "version": "0.0.1", "description": ""}


# ─── Plugin Loading ──────────────────────────────────────────────────────────

def load_plugins(plugins_dir: Optional[Path] = None) -> List[str]:
    """Load all plugins from the plugins directory.

    Args:
        plugins_dir: Override the default plugins directory.

    Returns:
        List of successfully loaded plugin names.
    """
    global _loaded_plugins, _plugin_manifests

    if not _PLUGINS_ENABLED:
        logger.info("Plugin loading is disabled")
        return []

    plugins_dir = plugins_dir or _PLUGINS_DIR
    if not plugins_dir.exists():
        logger.info(f"Plugins directory not found: {plugins_dir}")
        return []

    loaded = []
    with _plugin_lock:
        for plugin_dir in sorted(plugins_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            if plugin_dir.name.startswith(("_", ".")):
                continue
            if not (plugin_dir / "__init__.py").exists():
                continue

            plugin_name = plugin_name = plugin_dir.name
            logger.info(f"Loading plugin: {plugin_name}")

            try:
                # Load manifest
                manifest = _load_manifest(plugin_dir)
                _plugin_manifests[plugin_name] = manifest

                # Add to path temporarily for import
                if str(plugin_dir.parent) not in sys.path:
                    sys.path.insert(0, str(plugin_dir.parent))

                # Import the module
                module_path = plugin_dir / "provider.py"
                if not module_path.exists():
                    logger.warning(f"No provider.py in {plugin_name}, skipping")
                    continue

                spec = importlib.util.spec_from_file_location(
                    f"plugins.{plugin_name}.provider",
                    module_path,
                )
                if spec is None or spec.loader is None:
                    logger.warning(f"Could not load spec for {plugin_name}")
                    continue

                module = importlib.util.module_from_spec(spec)
                sys.modules[f"plugins.{plugin_name}.provider"] = module
                spec.loader.exec_module(module)

                # Find provider class
                provider_class = None
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and _is_valid_provider(attr):
                        provider_class = attr
                        break

                if provider_class is None:
                    logger.warning(f"No valid provider class found in {plugin_name}")
                    continue

                # Register the provider
                _loaded_plugins[plugin_name] = {
                    "class": provider_class,
                    "module": module,
                    "manifest": manifest,
                }
                loaded.append(plugin_name)
                logger.info(f"Loaded plugin: {plugin_name} (v{manifest.get('version', '0.0.1')})")

            except Exception as e:
                logger.error(f"Failed to load plugin {plugin_name}: {e}", exc_info=True)

    return loaded


def list_plugins() -> List[Dict[str, Any]]:
    """List all loaded plugins with their metadata.

    Returns:
        List of dicts with name, version, description, and class info.
    """
    result = []
    for name, info in _loaded_plugins.items():
        manifest = info.get("manifest", {})
        result.append({
            "name": name,
            "version": manifest.get("version", "0.0.1"),
            "description": manifest.get("description", ""),
            "class_name": info["class"].__name__,
        })
    return result


def get_plugin(name: str) -> Optional[Dict[str, Any]]:
    """Get a loaded plugin by name.

    Args:
        name: Plugin name (directory name).

    Returns:
        Dict with class, module, and manifest, or None if not found.
    """
    return _loaded_plugins.get(name)


def get_provider_class(name: str) -> Optional[Type]:
    """Get a provider class from a plugin.

    Args:
        name: Plugin name.

    Returns:
        Provider class or None.
    """
    plugin = _loaded_plugins.get(name)
    if plugin:
        return plugin["class"]
    return None


def register_plugin_provider(name: str, provider_class: Type, manifest: Optional[Dict] = None):
    """Programmatically register a plugin provider (for testing).

    Args:
        name: Plugin name.
        provider_class: Provider class.
        manifest: Optional manifest dict.
    """
    if not _is_valid_provider(provider_class):
        raise ValueError(f"{provider_class} does not implement the provider interface")

    with _plugin_lock:
        _loaded_plugins[name] = {
            "class": provider_class,
            "module": None,
            "manifest": manifest or {"name": name, "version": "0.0.1", "description": ""},
        }
        _plugin_manifests[name] = _loaded_plugins[name]["manifest"]


def unregister_plugin(name: str) -> bool:
    """Unregister a plugin.

    Args:
        name: Plugin name.

    Returns:
        True if the plugin was found and removed.
    """
    with _plugin_lock:
        if name in _loaded_plugins:
            del _loaded_plugins[name]
            _plugin_manifests.pop(name, None)
            return True
        return False


# ─── Hot Reload Support ──────────────────────────────────────────────────────

def reload_plugin(name: str) -> bool:
    """Reload a plugin from disk.

    Args:
        name: Plugin name.

    Returns:
        True if the plugin was reloaded successfully.
    """
    plugin_dir = _PLUGINS_DIR / name
    if not plugin_dir.exists():
        return False

    # Unregister old version
    unregister_plugin(name)

    # Reload
    loaded = load_plugins(plugin_dir.parent)
    return name in loaded


# ─── API Endpoints Helper ────────────────────────────────────────────────────

def create_plugin_routes(app):
    """Add plugin management routes to a FastAPI app.

    Args:
        app: FastAPI application instance.
    """

    @app.get("/api/plugins")
    async def list_plugin_routes():
        """List all loaded plugins."""
        return {"plugins": list_plugins()}

    @app.get("/api/plugins/{name}")
    async def get_plugin_route(name: str):
        """Get plugin details."""
        plugin = get_plugin(name)
        if plugin is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")

        manifest = plugin.get("manifest", {})
        return {
            "name": name,
            "version": manifest.get("version", "0.0.1"),
            "description": manifest.get("description", ""),
            "class_name": plugin["class"].__name__,
        }

    @app.post("/api/plugins/{name}/reload")
    async def reload_plugin_route(name: str):
        """Reload a plugin from disk."""
        success = reload_plugin(name)
        if success:
            return {"status": "reloaded", "name": name}
        else:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found or could not be reloaded")
