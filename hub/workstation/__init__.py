"""Workstation module — isolated container environments for agents.

Provides container-based workstations where agents run with their own
filesystem, network, and tools. Each workstation is a Docker container
with lifecycle management, network policies, and human access options.

Submodules:
- models: Workstation data models (Workstation, WorkstationConfig, etc.)
- driver: Docker SDK-based container driver
- storage: SQLite persistence for workstation state
- lifecycle: Create, start, stop, destroy, health check operations
- network_policy: Default-deny network with allowlist management
- access: Terminal (TTY) and desktop (VNC/noVNC) access setup
"""

from hub.workstation.models import (
    Workstation,
    WorkstationConfig,
    WorkstationStatus,
    WorkstationAccess,
)

__all__ = [
    "Workstation",
    "WorkstationConfig",
    "WorkstationStatus",
    "WorkstationAccess",
    "storage",
    "create_workstation",
    "start_workstation",
    "stop_workstation",
    "destroy_workstation",
    "get_workstation_health",
    "list_workstations",
    "get_workstation",
    "get_workstation_logs",
    "exec_in_workstation",
    "get_workstation_stats",
]


def __getattr__(name):
    """Lazy import to avoid circular dependencies."""
    if name == "storage":
        import hub.workstation.storage as storage
        return storage
    elif name == "driver":
        import hub.workstation.driver as driver
        return driver
    elif name == "network_policy":
        import hub.workstation.network_policy as network_policy
        return network_policy
    elif name == "access":
        import hub.workstation.access as access
        return access
    elif name == "lifecycle":
        import hub.workstation.lifecycle as lifecycle
        return lifecycle
    elif name in ("create_workstation", "start_workstation", "stop_workstation",
                  "destroy_workstation", "get_workstation_health", "list_workstations",
                  "get_workstation", "get_workstation_logs", "exec_in_workstation",
                  "get_workstation_stats"):
        import hub.workstation.lifecycle as lifecycle
        return getattr(lifecycle, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
