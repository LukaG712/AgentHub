"""Workflow engine data models.

Defines the core entities for the workflow system:
- WorkflowDefinition: A reusable workflow template with steps and triggers.
- WorkflowStep: An individual step within a workflow (agent task, service call, approval gate).
- WorkflowRun: An execution instance of a workflow definition.
- WorkflowTrigger: Conditions that start a workflow (schedule, webhook, file change).
- WorkflowApproval: Human-in-the-loop approval request within a workflow run.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class StepType(str, Enum):
    AGENT = "agent"           # Run a Greenie agent
    SERVICE = "service"       # Call an external service (Trapper, Slinker, etc.)
    APPROVAL = "approval"     # Wait for human approval
    CONDITION = "condition"   # Conditional branch
    NOTIFY = "notify"         # Send notification via Poltergeist
    WORKSTATION = "workstation"  # Create/manage an agent workstation
    # Mission control step types
    PLANNER = "planner"       # Mission orchestrator planning step
    WORKER = "worker"         # Mission worker execution step
    VALIDATOR = "validator"   # Independent validation step
    MILESTONE = "milestone"   # Milestone boundary marker


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TriggerType(str, Enum):
    SCHEDULE = "schedule"     # Cron-based schedule
    WEBHOOK = "webhook"       # HTTP webhook trigger
    FILE_CHANGE = "file_change"  # File system watch


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass
class WorkflowStep:
    """A single step in a workflow definition."""
    id: str = field(default_factory=lambda: f"step-{uuid4().hex[:8]}")
    name: str = ""
    step_type: str = StepType.AGENT.value
    # For AGENT steps: agent name
    agent: str = ""
    # For SERVICE steps: service name and task
    service: str = ""
    task: str = ""
    # For APPROVAL steps: description and timeout
    approval_description: str = ""
    approval_timeout_minutes: int = 30
    # For CONDITION steps: condition expression (simple key-value check)
    condition: Optional[dict] = None
    # For NOTIFY steps: channel and message template
    notify_channel: str = ""
    notify_message: str = ""
    # Ordering
    order: int = 0
    # Which steps must complete before this one (dependencies)
    depends_on: list[str] = field(default_factory=list)
    # Whether to continue workflow if this step fails
    on_failure: str = "stop"  # stop, continue
    # Extra config
    config: dict[str, Any] = field(default_factory=dict)
    # Mission control fields
    role: str = ""  # orchestrator, worker, validator
    model_override: Optional[str] = None  # Specific model for this step
    milestone_id: str = ""  # Which milestone this step belongs to

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowStep":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class WorkflowTrigger:
    """A trigger that starts a workflow."""
    id: str = field(default_factory=lambda: f"trig-{uuid4().hex[:8]}")
    trigger_type: str = TriggerType.SCHEDULE.value
    # For SCHEDULE: cron expression
    cron: str = ""
    # For WEBHOOK: secret token for verification
    webhook_secret: str = ""
    webhook_path: str = ""
    # For FILE_CHANGE: paths to watch
    watch_paths: list[str] = field(default_factory=list)
    # Whether trigger is active
    enabled: bool = True
    # Extra config
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowTrigger":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class WorkflowDefinition:
    """A reusable workflow definition (template)."""
    id: str = field(default_factory=lambda: f"wf-{uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)
    triggers: list[WorkflowTrigger] = field(default_factory=list)
    # Whether the workflow is enabled
    enabled: bool = True
    # Max execution time in minutes (0 = unlimited)
    timeout_minutes: int = 0
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "triggers": [t.to_dict() for t in self.triggers],
            "enabled": self.enabled,
            "timeout_minutes": self.timeout_minutes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowDefinition":
        steps = [WorkflowStep.from_dict(s) for s in data.get("steps", [])]
        triggers = [WorkflowTrigger.from_dict(t) for t in data.get("triggers", [])]
        return cls(
            id=data.get("id", cls.__dataclass_fields__["id"].default_factory()),
            name=data.get("name", ""),
            description=data.get("description", ""),
            steps=steps,
            triggers=triggers,
            enabled=data.get("enabled", True),
            timeout_minutes=data.get("timeout_minutes", 0),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            created_by=data.get("created_by", ""),
            tags=data.get("tags", []),
        )


@dataclass
class WorkflowStepRun:
    """Execution record for a single step in a workflow run."""
    id: str = field(default_factory=lambda: f"sr-{uuid4().hex[:8]}")
    step_id: str = ""
    step_name: str = ""
    status: str = StepStatus.PENDING.value
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    # Output/result of the step
    output: str = ""
    # Error message if failed
    error: str = ""
    # Approval result if applicable
    approval_result: Optional[str] = None
    # Duration in seconds
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowStepRun":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class WorkflowApproval:
    """Human-in-the-loop approval request."""
    id: str = field(default_factory=lambda: f"appr-{uuid4().hex[:8]}")
    run_id: str = ""
    step_id: str = ""
    description: str = ""
    status: str = ApprovalStatus.PENDING.value
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = None
    resolved_by: str = ""
    timeout_minutes: int = 30
    # Context data for the approver
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowApproval":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class WorkflowRun:
    """An execution instance of a workflow definition."""
    id: str = field(default_factory=lambda: f"run-{uuid4().hex[:8]}")
    workflow_id: str = ""
    workflow_name: str = ""
    status: str = RunStatus.PENDING.value
    # Which trigger started this run
    trigger_type: str = ""
    trigger_data: dict[str, Any] = field(default_factory=dict)
    # Step execution records
    step_runs: list[WorkflowStepRun] = field(default_factory=list)
    # Current step index being executed
    current_step_index: int = 0
    # Timestamps
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    # Total duration in seconds
    duration_seconds: float = 0.0
    # Error message if failed
    error: str = ""
    # Metadata
    started_by: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "trigger_type": self.trigger_type,
            "trigger_data": self.trigger_data,
            "step_runs": [s.to_dict() for s in self.step_runs],
            "current_step_index": self.current_step_index,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "started_by": self.started_by,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowRun":
        step_runs = [WorkflowStepRun.from_dict(s) for s in data.get("step_runs", [])]
        return cls(
            id=data.get("id", cls.__dataclass_fields__["id"].default_factory()),
            workflow_id=data.get("workflow_id", ""),
            workflow_name=data.get("workflow_name", ""),
            status=data.get("status", RunStatus.PENDING.value),
            trigger_type=data.get("trigger_type", ""),
            trigger_data=data.get("trigger_data", {}),
            step_runs=step_runs,
            current_step_index=data.get("current_step_index", 0),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            duration_seconds=data.get("duration_seconds", 0.0),
            error=data.get("error", ""),
            started_by=data.get("started_by", ""),
            tags=data.get("tags", []),
        )
