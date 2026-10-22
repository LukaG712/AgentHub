"""Mission control data models.

Defines the core entities for the Factory-inspired mission system:
- Mission: Top-level entity for a development task with milestones.
- MissionMilestone: Grouped set of features with success criteria.
- MissionFeature: Individual unit of work within a milestone.
- ValidationContract: Testable behavioral assertions defining completion.
- ValidationResult: Independent review findings.
- MissionCheckpoint: Snapshot of mission state for recovery.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class MissionStatus(str, Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"


class MilestoneStatus(str, Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"


class FeatureStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class FeatureRole(str, Enum):
    WORKER = "worker"
    VALIDATOR = "validator"


class ValidationSeverity(str, Enum):
    BLOCKER = "blocker"
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class AutonomyLevel(str, Enum):
    SUPERVISED = "supervised"           # All operations require approval
    RESTRICTED = "restricted_autonomous"  # Only sensitive operations require approval
    FULL = "full_autonomous"            # No approval gates


@dataclass
class ValidationContract:
    """Testable behavioral assertions defining mission completion."""
    id: str = field(default_factory=lambda: f"vc-{uuid4().hex[:8]}")
    mission_id: str = ""
    # Natural language description of what should be verified
    description: str = ""
    # List of testable assertions
    assertions: list[dict[str, Any]] = field(default_factory=list)
    # Commands to run for deterministic checks
    test_commands: list[str] = field(default_factory=list)
    # Files or patterns to check
    check_paths: list[str] = field(default_factory=list)
    # Minimum severity level to pass (findings above this fail validation)
    max_severity: str = ValidationSeverity.MAJOR.value
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ValidationContract":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ValidationResult:
    """Independent review finding."""
    id: str = field(default_factory=lambda: f"vr-{uuid4().hex[:8]}")
    mission_id: str = ""
    milestone_id: Optional[str] = None
    severity: str = ValidationSeverity.INFO.value
    # Affected file path
    file_path: Optional[str] = None
    # Line number in the file
    line_number: Optional[int] = None
    # Human-readable explanation
    explanation: str = ""
    # Suggested correction
    suggested_correction: str = ""
    # Whether the finding has been verified and addressed
    verified: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ValidationResult":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class MissionFeature:
    """Individual unit of work within a milestone."""
    id: str = field(default_factory=lambda: f"feat-{uuid4().hex[:8]}")
    mission_id: str = ""
    milestone_id: str = ""
    name: str = ""
    description: str = ""
    role: str = FeatureRole.WORKER.value
    # Assigned model for this feature (optional override)
    model_override: Optional[str] = None
    status: str = FeatureStatus.PENDING.value
    # Output/result of the feature
    output: str = ""
    # Error message if failed
    error: str = ""
    # Which features must complete before this one
    depends_on: list[str] = field(default_factory=list)
    # Order within milestone
    order: int = 0
    # Timestamps
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MissionFeature":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class MissionMilestone:
    """Grouped set of features with success criteria."""
    id: str = field(default_factory=lambda: f"ms-{uuid4().hex[:8]}")
    mission_id: str = ""
    name: str = ""
    description: str = ""
    status: str = MilestoneStatus.PLANNING.value
    # Success criteria for this milestone
    success_criteria: list[str] = field(default_factory=list)
    # Features in this milestone
    features: list[MissionFeature] = field(default_factory=list)
    # Order of milestones
    order: int = 0
    # Timestamps
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mission_id": self.mission_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "success_criteria": self.success_criteria,
            "features": [f.to_dict() for f in self.features],
            "order": self.order,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MissionMilestone":
        features = [MissionFeature.from_dict(f) for f in data.get("features", [])]
        return cls(
            id=data.get("id", cls.__dataclass_fields__["id"].default_factory()),
            mission_id=data.get("mission_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            status=data.get("status", MilestoneStatus.PLANNING.value),
            success_criteria=data.get("success_criteria", []),
            features=features,
            order=data.get("order", 0),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class MissionCheckpoint:
    """Snapshot of mission state for recovery."""
    id: str = field(default_factory=lambda: f"chk-{uuid4().hex[:8]}")
    mission_id: str = ""
    # JSON snapshot of full mission state
    state_json: str = ""
    # Description of what was completed at this checkpoint
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MissionCheckpoint":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Mission:
    """Top-level entity for a development task."""
    id: str = field(default_factory=lambda: f"mission-{uuid4().hex[:8]}")
    description: str = ""
    # Target repository path or URL
    target_repository: str = ""
    status: str = MissionStatus.PLANNING.value
    # Model preferences per role
    orchestrator_model: Optional[str] = None
    worker_model: Optional[str] = None
    validator_model: Optional[str] = None
    # Autonomy level
    autonomy_level: str = AutonomyLevel.RESTRICTED.value
    # Milestones
    milestones: list[MissionMilestone] = field(default_factory=list)
    # Validation contract
    validation_contract: Optional[ValidationContract] = None
    # Artifacts produced during execution
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    # Error message if failed
    error: str = ""
    # Whether to execute worker steps in parallel within a milestone
    parallel_workers: bool = False
    # Timestamps
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "target_repository": self.target_repository,
            "status": self.status,
            "orchestrator_model": self.orchestrator_model,
            "worker_model": self.worker_model,
            "validator_model": self.validator_model,
            "autonomy_level": self.autonomy_level,
            "milestones": [m.to_dict() for m in self.milestones],
            "validation_contract": self.validation_contract.to_dict() if self.validation_contract else None,
            "artifacts": self.artifacts,
            "error": self.error,
            "parallel_workers": self.parallel_workers,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Mission":
        milestones = [MissionMilestone.from_dict(m) for m in data.get("milestones", [])]
        validation_contract = None
        if data.get("validation_contract"):
            validation_contract = ValidationContract.from_dict(data["validation_contract"])
        return cls(
            id=data.get("id", cls.__dataclass_fields__["id"].default_factory()),
            description=data.get("description", ""),
            target_repository=data.get("target_repository", ""),
            status=data.get("status", MissionStatus.PLANNING.value),
            orchestrator_model=data.get("orchestrator_model"),
            worker_model=data.get("worker_model"),
            validator_model=data.get("validator_model"),
            autonomy_level=data.get("autonomy_level", AutonomyLevel.RESTRICTED.value),
            milestones=milestones,
            validation_contract=validation_contract,
            artifacts=data.get("artifacts", []),
            error=data.get("error", ""),
            parallel_workers=data.get("parallel_workers", False),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            created_by=data.get("created_by", ""),
            tags=data.get("tags", []),
        )
