"""Spec Mode — read-only research phase before implementation.

Inspired by Factory Droid's Spec Mode, this module provides a research-first
workflow where the agent analyzes the repository, proposes a concrete
implementation plan, and requires human approval before any code changes.

Key concepts:
- Spec: A research plan with findings, proposed changes, and validation criteria.
- Spec is read-only: No code is modified during the research phase.
- Approval gate: Human must approve before execution begins.
- Persistent spec store: Specs are stored for queryable history.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

import json
import os
import sqlite3
import threading
from pathlib import Path

from hub.mission.models import Mission, MissionMilestone, MissionFeature, ValidationContract
from hub.mission import storage as mission_storage


# ─── Models ──────────────────────────────────────────────────────────────────


class SpecStatus(str, Enum):
    DRAFT = "draft"
    RESEARCHING = "researching"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONVERTED = "converted"  # Converted to a mission


@dataclass
class SpecFinding:
    """A single research finding from repository analysis."""
    category: str = ""  # e.g., "architecture", "dependency", "convention"
    title: str = ""
    description: str = ""
    files: list[str] = field(default_factory=list)
    relevance: str = "high"  # high, medium, low


@dataclass
class SpecProposal:
    """Proposed implementation plan."""
    summary: str = ""
    steps: list[str] = field(default_factory=list)
    estimated_effort: str = ""  # e.g., "2-4 hours"
    risks: list[str] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    new_files: list[str] = field(default_factory=list)


@dataclass
class Spec:
    """A complete spec (research plan) for a development task."""
    id: str = field(default_factory=lambda: f"spec-{uuid4().hex[:8]}")
    title: str = ""
    description: str = ""
    target_repository: str = ""
    status: str = SpecStatus.DRAFT.value
    # Research findings
    findings: list[dict[str, Any]] = field(default_factory=list)
    # Implementation proposal
    proposal: Optional[dict[str, Any]] = None
    # Validation criteria derived from research
    validation_criteria: list[str] = field(default_factory=list)
    # Feedback from reviewer (on rejection)
    feedback: str = ""
    # Linked mission ID (after approval and conversion)
    mission_id: Optional[str] = None
    # Model used for research
    model_used: Optional[str] = None
    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Spec":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ─── Storage ─────────────────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_SPEC_DB_PATH = os.environ.get("GREENIE_SPEC_DB_PATH", str(_DATA_DIR / "specs.db"))

_db_lock = threading.Lock()


def _get_connection() -> sqlite3.Connection:
    """Get a new database connection with WAL mode."""
    db_dir = Path(_SPEC_DB_PATH).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_SPEC_DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema() -> None:
    """Initialize the specs database schema."""
    conn = _get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS specs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                target_repository TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                findings_json TEXT NOT NULL DEFAULT '[]',
                proposal_json TEXT,
                validation_criteria_json TEXT NOT NULL DEFAULT '[]',
                feedback TEXT NOT NULL DEFAULT '',
                mission_id TEXT,
                model_used TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_specs_status ON specs(status);
            CREATE INDEX IF NOT EXISTS idx_specs_repo ON specs(target_repository);
        """)
        conn.commit()
    finally:
        conn.close()


_init_schema()


def _row_to_spec(row: sqlite3.Row) -> Spec:
    """Convert a database row to a Spec."""
    return Spec(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        target_repository=row["target_repository"],
        status=row["status"],
        findings=json.loads(row["findings_json"]),
        proposal=json.loads(row["proposal_json"]) if row["proposal_json"] else None,
        validation_criteria=json.loads(row["validation_criteria_json"]),
        feedback=row["feedback"],
        mission_id=row["mission_id"],
        model_used=row["model_used"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        created_by=row["created_by"],
    )


def save_spec(spec: Spec) -> Spec:
    """Save or update a spec."""
    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO specs
                   (id, title, description, target_repository, status, findings_json,
                    proposal_json, validation_criteria_json, feedback, mission_id,
                    model_used, created_at, updated_at, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    spec.id, spec.title, spec.description, spec.target_repository,
                    spec.status, json.dumps(spec.findings),
                    json.dumps(spec.proposal) if spec.proposal else None,
                    json.dumps(spec.validation_criteria),
                    spec.feedback, spec.mission_id, spec.model_used,
                    spec.created_at, spec.updated_at, spec.created_by,
                ),
            )
            conn.commit()
            return spec
        finally:
            conn.close()


def get_spec(spec_id: str) -> Optional[Spec]:
    """Get a spec by ID."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM specs WHERE id = ?", (spec_id,)
        ).fetchone()
        return _row_to_spec(row) if row else None
    finally:
        conn.close()


def list_specs(
    status: Optional[str] = None,
    target_repository: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Spec]:
    """List specs with optional filters."""
    conn = _get_connection()
    try:
        query = "SELECT * FROM specs WHERE 1=1"
        params: list[Any] = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if target_repository:
            query += " AND target_repository = ?"
            params.append(target_repository)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [_row_to_spec(r) for r in rows]
    finally:
        conn.close()


def delete_spec(spec_id: str) -> bool:
    """Delete a spec."""
    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.execute("DELETE FROM specs WHERE id = ?", (spec_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def get_spec_stats() -> dict[str, Any]:
    """Get spec statistics."""
    conn = _get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM specs").fetchone()[0]
        draft = conn.execute("SELECT COUNT(*) FROM specs WHERE status = 'draft'").fetchone()[0]
        researching = conn.execute("SELECT COUNT(*) FROM specs WHERE status = 'researching'").fetchone()[0]
        ready = conn.execute("SELECT COUNT(*) FROM specs WHERE status = 'ready_for_review'").fetchone()[0]
        approved = conn.execute("SELECT COUNT(*) FROM specs WHERE status = 'approved'").fetchone()[0]
        rejected = conn.execute("SELECT COUNT(*) FROM specs WHERE status = 'rejected'").fetchone()[0]
        converted = conn.execute("SELECT COUNT(*) FROM specs WHERE status = 'converted'").fetchone()[0]
        return {
            "total_specs": total,
            "draft": draft,
            "researching": researching,
            "ready_for_review": ready,
            "approved": approved,
            "rejected": rejected,
            "converted": converted,
        }
    finally:
        conn.close()


# ─── Controller ──────────────────────────────────────────────────────────────


def create_spec(
    title: str,
    description: str,
    target_repository: str,
    created_by: str = "api",
    model_override: Optional[str] = None,
) -> Spec:
    """Create a new spec and start the research phase.

    Args:
        title: Short title for the spec.
        description: Natural-language description of the desired outcome.
        target_repository: Path or URL of the target repository.
        created_by: User or system creating the spec.
        model_override: Optional model to use for research.

    Returns:
        The created Spec with DRAFT status.
    """
    if not title.strip():
        raise ValueError("title is required")
    if not description.strip():
        raise ValueError("description is required")
    if not target_repository.strip():
        raise ValueError("target_repository is required")

    spec = Spec(
        title=title.strip(),
        description=description.strip(),
        target_repository=target_repository.strip(),
        status=SpecStatus.DRAFT.value,
        created_by=created_by,
        model_used=model_override,
    )
    save_spec(spec)
    return spec


def research_spec(spec_id: str) -> Spec:
    """Run the research phase for a spec.

    Analyzes the repository, produces findings, and creates an implementation
    proposal. Uses repo_intelligence for analysis and the planner for proposal.

    Args:
        spec_id: The spec to research.

    Returns:
        The updated Spec with findings and proposal.

    Raises:
        ValueError: If the spec is not found or not in DRAFT status.
    """
    spec = get_spec(spec_id)
    if spec is None:
        raise ValueError(f"Spec {spec_id} not found")
    if spec.status != SpecStatus.DRAFT.value:
        raise ValueError(f"Spec must be in DRAFT status, currently {spec.status}")

    spec.status = SpecStatus.RESEARCHING.value
    save_spec(spec)

    # Use repo intelligence to analyze the target repository
    findings = []
    proposal = None
    validation_criteria = []

    try:
        from hub.mission.repo_intelligence import analyze_repository
        repo_info = analyze_repository(spec.target_repository)

        findings = [
            {"category": "structure", "title": "Repository Structure",
             "description": repo_info.get("structure_summary", ""),
             "files": repo_info.get("entry_points", []), "relevance": "high"},
            {"category": "framework", "title": "Detected Frameworks",
             "description": ", ".join(repo_info.get("frameworks", [])),
             "files": [], "relevance": "high"},
            {"category": "conventions", "title": "Project Conventions",
             "description": repo_info.get("conventions_summary", ""),
             "files": repo_info.get("convention_files", []), "relevance": "medium"},
        ]

        # Build proposal from repo info
        proposal = {
            "summary": f"Implementation plan for: {spec.title}",
            "steps": [f"Analyze {spec.target_repository} structure and conventions"],
            "estimated_effort": "TBD",
            "risks": [],
            "affected_files": repo_info.get("relevant_files", []),
            "new_files": [],
        }

        validation_criteria = [
            "All existing tests pass after changes",
            "Code follows project conventions",
            "No regressions in existing functionality",
        ]

    except Exception as e:
        # Fallback if repo intelligence fails
        findings = [{"category": "error", "title": "Analysis Failed",
                     "description": str(e), "files": [], "relevance": "high"}]
        proposal = {
            "summary": f"Manual plan needed for: {spec.title}",
            "steps": ["Review repository manually", "Create implementation plan"],
            "estimated_effort": "TBD",
            "risks": ["Repository analysis failed"],
            "affected_files": [],
            "new_files": [],
        }
        validation_criteria = ["Verify changes manually"]

    spec.findings = findings
    spec.proposal = proposal
    spec.validation_criteria = validation_criteria
    spec.status = SpecStatus.READY_FOR_REVIEW.value
    spec.updated_at = datetime.now(timezone.utc).isoformat()
    save_spec(spec)
    return spec


def approve_spec(spec_id: str) -> Spec:
    """Approve a spec for implementation.

    Args:
        spec_id: The spec to approve.

    Returns:
        The updated Spec with APPROVED status.
    """
    spec = get_spec(spec_id)
    if spec is None:
        raise ValueError(f"Spec {spec_id} not found")
    if spec.status != SpecStatus.READY_FOR_REVIEW.value:
        raise ValueError(f"Spec must be ready for review, currently {spec.status}")

    spec.status = SpecStatus.APPROVED.value
    spec.updated_at = datetime.now(timezone.utc).isoformat()
    save_spec(spec)
    return spec


def reject_spec(spec_id: str, feedback: str) -> Spec:
    """Reject a spec with feedback.

    Args:
        spec_id: The spec to reject.
        feedback: Explanation of why the spec is rejected.

    Returns:
        The updated Spec with REJECTED status.
    """
    spec = get_spec(spec_id)
    if spec is None:
        raise ValueError(f"Spec {spec_id} not found")
    if spec.status not in (SpecStatus.READY_FOR_REVIEW.value, SpecStatus.REJECTED.value):
        raise ValueError(f"Spec must be ready for review or rejected, currently {spec.status}")

    spec.status = SpecStatus.REJECTED.value
    spec.feedback = feedback
    spec.updated_at = datetime.now(timezone.utc).isoformat()
    save_spec(spec)
    return spec


def convert_spec_to_mission(spec_id: str, created_by: str = "api") -> Mission:
    """Convert an approved spec into a Mission.

    Creates a mission from the spec's proposal and validation criteria.

    Args:
        spec_id: The approved spec to convert.
        created_by: User creating the mission.

    Returns:
        The created Mission.

    Raises:
        ValueError: If the spec is not found or not approved.
    """
    spec = get_spec(spec_id)
    if spec is None:
        raise ValueError(f"Spec {spec_id} not found")
    if spec.status != SpecStatus.APPROVED.value:
        raise ValueError(f"Spec must be approved, currently {spec.status}")

    # Create mission from spec
    from hub.mission import controller as mission_controller

    description = f"[From Spec: {spec.title}] {spec.description}"

    mission = mission_controller.create_mission(
        description=description,
        target_repository=spec.target_repository,
        created_by=created_by,
    )

    # If the spec has validation criteria, create a validation contract
    if spec.validation_criteria:
        vc = ValidationContract(
            mission_id=mission.id,
            description=f"Validation criteria from spec {spec.id}",
            assertions=[
                {"assertion": criterion, "type": "manual"}
                for criterion in spec.validation_criteria
            ],
        )
        mission.validation_contract = vc
        mission_storage.save_mission(mission)

    # Update spec with mission link
    spec.mission_id = mission.id
    spec.status = SpecStatus.CONVERTED.value
    spec.updated_at = datetime.now(timezone.utc).isoformat()
    save_spec(spec)

    return mission
