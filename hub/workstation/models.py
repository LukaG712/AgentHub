"""Workstation data models.

Defines the core entities for the workstation system:
- Workstation: An isolated container environment for agent execution.
- WorkstationConfig: Configuration for creating a workstation (image, resources, etc.).
- WorkstationAccess: Access information (terminal, desktop, ports).
- WorkstationStatus: Lifecycle status enum.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class WorkstationStatus(str, Enum):
    PENDING = "pending"
    CREATING = "creating"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    DESTROYED = "destroyed"


class AccessType(str, Enum):
    TTY = "tty"              # Live terminal via WebSocket
    VNC = "vnc"              # Desktop via VNC
    NO_VNC = "novnc"         # Desktop via noVNC (browser)


@dataclass
class WorkstationAccess:
    """Access information for a running workstation."""
    terminal_url: Optional[str] = None       # WebSocket URL for TTY
    desktop_url: Optional[str] = None        # URL for VNC/noVNC desktop
    access_type: str = AccessType.TTY.value  # tty, vnc, novnc
    vnc_password: Optional[str] = None       # VNC password (if applicable)
    exposed_ports: list[dict[str, Any]] = field(default_factory=list)
    # Example: [{"container_port": 8080, "host_port": 31000}]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkstationAccess":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class WorkstationConfig:
    """Configuration for creating a workstation."""
    # Docker image to use (default: python:3.11-slim)
    image: str = "python:3.11-slim"
    # Resource limits
    cpu_limit: float = 1.0          # CPU cores (e.g., 0.5, 1.0, 2.0)
    memory_limit: str = "512m"      # Memory limit (e.g., "256m", "1g")
    disk_limit: str = "10g"         # Disk space limit
    # Environment variables to inject
    env_vars: dict[str, str] = field(default_factory=dict)
    # Volume mounts: [{"source": "/host/path", "target": "/container/path", "read_only": false}]
    volumes: list[dict[str, Any]] = field(default_factory=list)
    # Network configuration
    network_name: str = "evershade-workstations"
    allowed_hosts: list[str] = field(default_factory=list)  # Allowlist of hostnames/IPs
    dns_servers: list[str] = field(default_factory=list)
    # Access configuration
    enable_terminal: bool = True
    enable_desktop: bool = False
    desktop_type: str = "novnc"     # vnc or novnc
    # Labels for identification
    labels: dict[str, str] = field(default_factory=dict)
    # Extra Docker run options
    extra_hosts: dict[str, str] = field(default_factory=dict)
    command: Optional[str] = None   # Override container entrypoint command

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkstationConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Workstation:
    """An isolated container environment for agent execution."""
    id: str = field(default_factory=lambda: f"ws-{uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    status: str = WorkstationStatus.PENDING.value
    # Container info
    container_id: str = ""
    container_name: str = ""
    # Configuration
    config: WorkstationConfig = field(default_factory=WorkstationConfig)
    # Access info (populated when running)
    access: Optional[WorkstationAccess] = None
    # Resource usage snapshot
    cpu_percent: float = 0.0
    memory_usage_bytes: int = 0
    disk_usage_bytes: int = 0
    # Lifecycle timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None
    destroyed_at: Optional[str] = None
    # Error info
    error: str = ""
    # Metadata
    created_by: str = ""
    agent_name: str = ""            # Associated agent (if any)
    workflow_run_id: str = ""       # Associated workflow run (if any)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "container_id": self.container_id,
            "container_name": self.container_name,
            "config": self.config.to_dict(),
            "access": self.access.to_dict() if self.access else None,
            "cpu_percent": self.cpu_percent,
            "memory_usage_bytes": self.memory_usage_bytes,
            "disk_usage_bytes": self.disk_usage_bytes,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "destroyed_at": self.destroyed_at,
            "error": self.error,
            "created_by": self.created_by,
            "agent_name": self.agent_name,
            "workflow_run_id": self.workflow_run_id,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Workstation":
        config_data = data.get("config", {})
        config = WorkstationConfig.from_dict(config_data) if config_data else WorkstationConfig()

        access_data = data.get("access")
        access = WorkstationAccess.from_dict(access_data) if access_data else None

        return cls(
            id=data.get("id", cls.__dataclass_fields__["id"].default_factory()),
            name=data.get("name", ""),
            description=data.get("description", ""),
            status=data.get("status", WorkstationStatus.PENDING.value),
            container_id=data.get("container_id", ""),
            container_name=data.get("container_name", ""),
            config=config,
            access=access,
            cpu_percent=data.get("cpu_percent", 0.0),
            memory_usage_bytes=data.get("memory_usage_bytes", 0),
            disk_usage_bytes=data.get("disk_usage_bytes", 0),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            started_at=data.get("started_at"),
            stopped_at=data.get("stopped_at"),
            destroyed_at=data.get("destroyed_at"),
            error=data.get("error", ""),
            created_by=data.get("created_by", ""),
            agent_name=data.get("agent_name", ""),
            workflow_run_id=data.get("workflow_run_id", ""),
            tags=data.get("tags", []),
        )
