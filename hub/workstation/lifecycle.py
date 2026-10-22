"""Workstation lifecycle management.

Orchestrates the container driver and storage layer to manage the full
lifecycle of workstations: create, start, stop, destroy, and health checks.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from hub.workstation.models import (
    Workstation,
    WorkstationAccess,
    WorkstationConfig,
    WorkstationStatus,
)
from hub.workstation import driver, storage
from hub.workstation import network_policy
from hub.workstation import access as access_module

logger = logging.getLogger(__name__)


def create_workstation(
    name: str,
    description: str = "",
    config: Optional[WorkstationConfig] = None,
    created_by: str = "api",
    agent_name: str = "",
    workflow_run_id: str = "",
    tags: Optional[list[str]] = None,
) -> Optional[Workstation]:
    """Create a new workstation and its Docker container.

    Returns the Workstation object on success, None on failure.
    """
    if config is None:
        config = WorkstationConfig()

    # Create the workstation record
    ws = Workstation(
        name=name,
        description=description,
        status=WorkstationStatus.CREATING.value,
        config=config,
        created_by=created_by,
        agent_name=agent_name,
        workflow_run_id=workflow_run_id,
        tags=tags or [],
    )

    # Persist the initial state
    storage.save_workstation(ws)
    logger.info(f"Creating workstation '{ws.id}' ({name})")

    try:
        # Ensure the network exists
        if not driver.ensure_network(config.network_name):
            # Network creation failed — continue anyway, container may use default network
            logger.warning(f"Could not ensure network '{config.network_name}' — using default")

        # Pull the image if needed
        if not driver.pull_image(config.image):
            ws.status = WorkstationStatus.ERROR.value
            ws.error = f"Failed to pull image '{config.image}'"
            storage.save_workstation(ws)
            return ws

        # Apply network policy (DNS allowlist)
        if config.allowed_hosts:
            network_policy.apply_policy(ws.id, config.allowed_hosts)

        # Create the Docker container
        container_id = driver.create_container(ws, config)
        if container_id is None:
            ws.status = WorkstationStatus.ERROR.value
            ws.error = "Failed to create Docker container"
            storage.save_workstation(ws)
            return ws

        ws.container_id = container_id
        ws.status = WorkstationStatus.PENDING.value
        storage.save_workstation(ws)
        logger.info(f"Workstation '{ws.id}' container created: {container_id[:12]}")

        return ws

    except Exception as e:
        ws.status = WorkstationStatus.ERROR.value
        ws.error = str(e)
        storage.save_workstation(ws)
        logger.error(f"Failed to create workstation '{ws.id}': {e}")
        return ws


def start_workstation(workstation_id: str) -> Optional[Workstation]:
    """Start a workstation container.

    Returns the updated Workstation on success, None if not found.
    """
    ws = storage.get_workstation(workstation_id)
    if ws is None:
        logger.error(f"Workstation '{workstation_id}' not found")
        return None

    if ws.status == WorkstationStatus.RUNNING.value:
        logger.info(f"Workstation '{workstation_id}' is already running")
        return ws

    try:
        ws.status = WorkstationStatus.CREATING.value
        storage.update_workstation_status(workstation_id, WorkstationStatus.CREATING.value)

        # Start the container
        if not driver.start_container(ws.container_id):
            ws.status = WorkstationStatus.ERROR.value
            ws.error = "Failed to start Docker container"
            storage.save_workstation(ws)
            return ws

        # Update status to running
        now = datetime.now(timezone.utc).isoformat()
        ws.status = WorkstationStatus.RUNNING.value
        ws.started_at = now
        ws.error = ""

        # Setup access (terminal, desktop)
        ws.access = access_module.setup_access(ws)
        storage.save_workstation(ws)

        # Apply network policy if configured
        if ws.config.allowed_hosts:
            network_policy.apply_policy(ws.id, ws.config.allowed_hosts)

        logger.info(f"Workstation '{workstation_id}' started")
        return ws

    except Exception as e:
        ws.status = WorkstationStatus.ERROR.value
        ws.error = str(e)
        storage.save_workstation(ws)
        logger.error(f"Failed to start workstation '{workstation_id}': {e}")
        return ws


def stop_workstation(workstation_id: str, timeout: int = 30) -> Optional[Workstation]:
    """Stop a running workstation container.

    Returns the updated Workstation on success, None if not found.
    """
    ws = storage.get_workstation(workstation_id)
    if ws is None:
        logger.error(f"Workstation '{workstation_id}' not found")
        return None

    if ws.status == WorkstationStatus.STOPPED.value:
        logger.info(f"Workstation '{workstation_id}' is already stopped")
        return ws

    try:
        if not driver.stop_container(ws.container_id, timeout=timeout):
            ws.error = "Failed to stop Docker container"
            storage.save_workstation(ws)
            return ws

        ws.status = WorkstationStatus.STOPPED.value
        ws.stopped_at = datetime.now(timezone.utc).isoformat()
        ws.access = None
        storage.save_workstation(ws)

        logger.info(f"Workstation '{workstation_id}' stopped")
        return ws

    except Exception as e:
        ws.error = str(e)
        storage.save_workstation(ws)
        logger.error(f"Failed to stop workstation '{workstation_id}': {e}")
        return ws


def destroy_workstation(workstation_id: str, force: bool = False) -> Optional[Workstation]:
    """Destroy a workstation and remove its Docker container.

    Returns the updated Workstation on success, None if not found.
    """
    ws = storage.get_workstation(workstation_id)
    if ws is None:
        logger.error(f"Workstation '{workstation_id}' not found")
        return None

    if ws.status == WorkstationStatus.DESTROYED.value:
        logger.info(f"Workstation '{workstation_id}' is already destroyed")
        return ws

    try:
        # Stop the container first if running
        if ws.status == WorkstationStatus.RUNNING.value:
            driver.stop_container(ws.container_id, timeout=10)

        # Remove the container
        if ws.container_id:
            driver.remove_container(ws.container_id, force=force)

        # Clean up network policy
        network_policy.remove_policy(ws.id)

        ws.status = WorkstationStatus.DESTROYED.value
        ws.destroyed_at = datetime.now(timezone.utc).isoformat()
        ws.access = None
        storage.save_workstation(ws)

        logger.info(f"Workstation '{workstation_id}' destroyed")
        return ws

    except Exception as e:
        ws.error = str(e)
        storage.save_workstation(ws)
        logger.error(f"Failed to destroy workstation '{workstation_id}': {e}")
        return ws


def get_workstation_health(workstation_id: str) -> Optional[dict[str, Any]]:
    """Get the health and resource usage of a running workstation.

    Returns a dict with status, cpu, memory, and access info, or None if not found.
    """
    ws = storage.get_workstation(workstation_id)
    if ws is None:
        return None

    if not ws.container_id:
        return {
            "status": ws.status,
            "running": False,
            "error": "No container ID",
        }

    # Inspect the container
    info = driver.inspect_container(ws.container_id)
    if info is None:
        return {
            "status": ws.status,
            "running": False,
            "error": "Failed to inspect container",
        }

    # Update resource usage in storage
    ws.cpu_percent = info.get("cpu_percent", 0.0)
    ws.memory_usage_bytes = info.get("memory_usage_bytes", 0)
    storage.save_workstation(ws)

    return {
        "status": info["status"],
        "running": info["running"],
        "cpu_percent": ws.cpu_percent,
        "memory_usage_bytes": ws.memory_usage_bytes,
        "disk_usage_bytes": ws.disk_usage_bytes,
        "access": ws.access.to_dict() if ws.access else None,
        "container_id": ws.container_id[:12] if ws.container_id else "",
    }


def list_workstations(
    status: Optional[str] = None,
    agent_name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Workstation]:
    """List workstations with optional filtering."""
    return storage.list_workstations(
        status=status,
        agent_name=agent_name,
        limit=limit,
        offset=offset,
    )


def get_workstation(workstation_id: str) -> Optional[Workstation]:
    """Get a workstation by ID."""
    return storage.get_workstation(workstation_id)


def get_workstation_logs(workstation_id: str, tail: int = 100) -> Optional[str]:
    """Get the logs of a workstation container."""
    ws = storage.get_workstation(workstation_id)
    if ws is None or not ws.container_id:
        return None
    return driver.get_container_logs(ws.container_id, tail=tail)


def exec_in_workstation(workstation_id: str, command: str) -> Optional[dict[str, Any]]:
    """Execute a command inside a running workstation container."""
    ws = storage.get_workstation(workstation_id)
    if ws is None or not ws.container_id:
        return None
    if ws.status != WorkstationStatus.RUNNING.value:
        return {"exit_code": -1, "stdout": "", "stderr": "Workstation is not running"}
    return driver.exec_in_container(ws.container_id, command)


def get_workstation_stats() -> dict[str, Any]:
    """Get workstation statistics."""
    total = storage.count_workstations()
    running = storage.count_workstations(WorkstationStatus.RUNNING.value)
    stopped = storage.count_workstations(WorkstationStatus.STOPPED.value)
    error = storage.count_workstations(WorkstationStatus.ERROR.value)
    destroyed = storage.count_workstations(WorkstationStatus.DESTROYED.value)

    return {
        "total": total,
        "running": running,
        "stopped": stopped,
        "error": error,
        "destroyed": destroyed,
        "docker_available": driver.is_docker_available(),
    }
