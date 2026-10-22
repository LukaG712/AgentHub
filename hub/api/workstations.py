"""Route module: workstations.

Provides the REST API for workstation management:
- CRUD for workstations
- Lifecycle operations (start, stop, destroy)
- Health checks and resource usage
- Terminal and desktop access
- Network policy management
"""

from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Query

from hub.api.core import _verify_token
from hub.workstation import (
    Workstation,
    WorkstationConfig,
    WorkstationStatus,
    create_workstation,
    destroy_workstation,
    exec_in_workstation,
    get_workstation,
    get_workstation_health,
    get_workstation_logs,
    get_workstation_stats,
    list_workstations,
    network_policy,
    start_workstation,
    stop_workstation,
    storage,
)
from hub.workstation import access as access_module

# ─── Workstation CRUD ────────────────────────────────────────────────────────


async def api_create_workstation(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Create a new workstation.

    Example body:
    {
        "name": "Research agent workstation",
        "description": "Isolated environment for web research",
        "config": {
            "image": "python:3.11-slim",
            "cpu_limit": 1.0,
            "memory_limit": "512m",
            "allowed_hosts": ["api.openai.com", "google.com"],
            "enable_terminal": true,
            "enable_desktop": false
        },
        "agent_name": "researcher",
        "tags": ["research", "production"]
    }
    """
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    # Parse config
    config_data = body.get("config", {})
    config = WorkstationConfig(
        image=config_data.get("image", "python:3.11-slim"),
        cpu_limit=config_data.get("cpu_limit", 1.0),
        memory_limit=config_data.get("memory_limit", "512m"),
        disk_limit=config_data.get("disk_limit", "10g"),
        env_vars=config_data.get("env_vars", {}),
        volumes=config_data.get("volumes", []),
        network_name=config_data.get("network_name", "evershade-workstations"),
        allowed_hosts=config_data.get("allowed_hosts", []),
        dns_servers=config_data.get("dns_servers", []),
        enable_terminal=config_data.get("enable_terminal", True),
        enable_desktop=config_data.get("enable_desktop", False),
        desktop_type=config_data.get("desktop_type", "novnc"),
        labels=config_data.get("labels", {}),
        extra_hosts=config_data.get("extra_hosts", {}),
        command=config_data.get("command"),
    )

    ws = create_workstation(
        name=name,
        description=body.get("description", ""),
        config=config,
        created_by=body.get("created_by", "api"),
        agent_name=body.get("agent_name", ""),
        workflow_run_id=body.get("workflow_run_id", ""),
        tags=body.get("tags", []),
    )

    if ws is None:
        raise HTTPException(status_code=500, detail="Failed to create workstation")

    if ws.status == WorkstationStatus.ERROR.value:
        raise HTTPException(status_code=500, detail=ws.error)

    return ws.to_dict()


async def api_get_workstation(workstation_id: str, _auth: None = Depends(_verify_token)):
    """Get a workstation by ID."""
    ws = get_workstation(workstation_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workstation not found")
    return ws.to_dict()


async def api_list_workstations(
    status: Optional[str] = Query(None),
    agent_name: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _auth: None = Depends(_verify_token),
):
    """List workstations with optional filtering."""
    workstations = list_workstations(
        status=status,
        agent_name=agent_name,
        limit=limit,
        offset=offset,
    )
    return {
        "workstations": [ws.to_dict() for ws in workstations],
        "total": len(workstations),
    }


# ─── Lifecycle Operations ────────────────────────────────────────────────────


async def api_start_workstation(workstation_id: str, _auth: None = Depends(_verify_token)):
    """Start a workstation."""
    ws = start_workstation(workstation_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workstation not found")
    if ws.status == WorkstationStatus.ERROR.value:
        raise HTTPException(status_code=500, detail=ws.error)
    return ws.to_dict()


async def api_stop_workstation(
    workstation_id: str,
    timeout: int = Query(30, ge=1, le=120),
    _auth: None = Depends(_verify_token),
):
    """Stop a running workstation."""
    ws = stop_workstation(workstation_id, timeout=timeout)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workstation not found")
    return ws.to_dict()


async def api_destroy_workstation(
    workstation_id: str,
    force: bool = Query(False),
    _auth: None = Depends(_verify_token),
):
    """Destroy a workstation and remove its container."""
    ws = destroy_workstation(workstation_id, force=force)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workstation not found")
    return ws.to_dict()


# ─── Health & Monitoring ─────────────────────────────────────────────────────


async def api_workstation_health(workstation_id: str, _auth: None = Depends(_verify_token)):
    """Get health and resource usage of a workstation."""
    ws = get_workstation(workstation_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workstation not found")

    health = get_workstation_health(workstation_id)
    if health is None:
        raise HTTPException(status_code=500, detail="Failed to get health")

    return health


async def api_workstation_logs(
    workstation_id: str,
    tail: int = Query(100, ge=1, le=1000),
    _auth: None = Depends(_verify_token),
):
    """Get container logs for a workstation."""
    logs = get_workstation_logs(workstation_id, tail=tail)
    if logs is None:
        raise HTTPException(status_code=404, detail="Workstation not found or has no container")
    return {"logs": logs}


async def api_workstation_stats(_auth: None = Depends(_verify_token)):
    """Get workstation statistics."""
    return get_workstation_stats()


# ─── Execution ───────────────────────────────────────────────────────────────


async def api_exec_command(workstation_id: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Execute a command inside a running workstation.

    Example body:
    {
        "command": "pip install requests"
    }
    """
    command = body.get("command", "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="command is required")

    result = exec_in_workstation(workstation_id, command)
    if result is None:
        raise HTTPException(status_code=404, detail="Workstation not found or not running")

    return result


# ─── Network Policy ──────────────────────────────────────────────────────────


async def api_get_network_policy(workstation_id: str, _auth: None = Depends(_verify_token)):
    """Get the network policy for a workstation."""
    policy = network_policy.get_policy(workstation_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Workstation not found")
    return policy


async def api_update_network_policy(
    workstation_id: str,
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Update the network policy for a workstation.

    Example body:
    {
        "allowed_hosts": ["api.openai.com", "google.com", "github.com"]
    }
    """
    allowed_hosts = body.get("allowed_hosts", [])

    # Validate hosts
    for host in allowed_hosts:
        is_allowed, reason = network_policy.validate_host(host)
        if not is_allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Host '{host}' is not allowed: {reason}",
            )

    success = network_policy.apply_policy(workstation_id, allowed_hosts)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to apply network policy")

    return {"status": "applied", "allowed_hosts": allowed_hosts}


async def api_validate_host(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Validate whether a host is allowed for workstation access.

    Example body:
    {
        "host": "api.openai.com"
    }
    """
    host = body.get("host", "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="host is required")

    is_allowed, reason = network_policy.validate_host(host)
    return {"host": host, "allowed": is_allowed, "reason": reason}


# ─── Access ──────────────────────────────────────────────────────────────────


async def api_get_access_info(workstation_id: str, _auth: None = Depends(_verify_token)):
    """Get access information for a workstation (without VNC password)."""
    info = access_module.get_access_info(workstation_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Workstation not found")
    return info


async def api_get_vnc_password(workstation_id: str, _auth: None = Depends(_verify_token)):
    """Get the VNC password for a workstation (requires elevated privileges)."""
    password = access_module.get_vnc_password(workstation_id)
    if password is None:
        raise HTTPException(status_code=404, detail="VNC password not available")
    return {"vnc_password": password}


# ─── Route Registration ──────────────────────────────────────────────────────


def register(app):
    """Register workstation routes with the FastAPI app."""
    app.add_api_route("/api/workstations", api_create_workstation, methods=["POST"], tags=["workstations"])
    app.add_api_route("/api/workstations", api_list_workstations, methods=["GET"], tags=["workstations"])
    app.add_api_route("/api/workstations/stats", api_workstation_stats, methods=["GET"], tags=["workstations"])
    app.add_api_route("/api/workstations/{workstation_id}", api_get_workstation, methods=["GET"], tags=["workstations"])
    app.add_api_route("/api/workstations/{workstation_id}/start", api_start_workstation, methods=["POST"], tags=["workstations"])
    app.add_api_route("/api/workstations/{workstation_id}/stop", api_stop_workstation, methods=["POST"], tags=["workstations"])
    app.add_api_route("/api/workstations/{workstation_id}/destroy", api_destroy_workstation, methods=["POST"], tags=["workstations"])
    app.add_api_route("/api/workstations/{workstation_id}/health", api_workstation_health, methods=["GET"], tags=["workstations"])
    app.add_api_route("/api/workstations/{workstation_id}/logs", api_workstation_logs, methods=["GET"], tags=["workstations"])
    app.add_api_route("/api/workstations/{workstation_id}/exec", api_exec_command, methods=["POST"], tags=["workstations"])
    app.add_api_route("/api/workstations/{workstation_id}/policy", api_get_network_policy, methods=["GET"], tags=["workstations"])
    app.add_api_route("/api/workstations/{workstation_id}/policy", api_update_network_policy, methods=["PUT"], tags=["workstations"])
    app.add_api_route("/api/workstations/validate-host", api_validate_host, methods=["POST"], tags=["workstations"])
    app.add_api_route("/api/workstations/{workstation_id}/access", api_get_access_info, methods=["GET"], tags=["workstations"])
    app.add_api_route("/api/workstations/{workstation_id}/vnc-password", api_get_vnc_password, methods=["GET"], tags=["workstations"])
