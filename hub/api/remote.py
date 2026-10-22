"""Route module: remote."""

import shutil
from typing import Any, Dict, List, Optional

from fastapi import Depends

from hub import remote
from hub.api.core import _verify_token
from hub.config import load_config, save_config, set_primary_bot, validate_name


async def api_remote_status(_auth: None = Depends(_verify_token)):
    """Check remote execution configuration and connectivity."""
    config = load_config()
    targets: List[Dict[str, Any]] = []

    # Check top-level remote config
    top_level = remote.get_remote_config(config)
    if top_level:
        target = remote.RemoteTarget(top_level)
        targets.append({
            "scope": "global",
            "host": top_level.host,
            "user": top_level.user,
            "port": top_level.port,
            "available": target.is_available(),
        })

    # Check per-agent remote configs
    for agent_name, agent_cfg in config.get("agents", {}).items():
        agent_remote = remote.get_agent_remote_config(config, agent_name)
        if agent_remote:
            t = remote.RemoteTarget(agent_remote)
            targets.append({
                "scope": "agent",
                "agent": agent_name,
                "host": agent_remote.host,
                "user": agent_remote.user,
                "port": agent_remote.port,
                "available": t.is_available(),
            })

    return {
        "ssh_available": shutil.which("ssh") is not None,
        "targets": targets,
    }


# --- Git Status ---



def register(app):
    """Register remote routes with the FastAPI app."""
    app.get("/api/remote/status")(api_remote_status)
