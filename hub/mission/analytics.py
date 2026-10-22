"""Mission-specific analytics and metrics.

Tracks mission-level statistics: success/failure rates, time spent in each
lifecycle stage, validation findings summary, retry counts, and model usage.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from hub.mission import storage as mission_storage
from hub.mission.models import Mission, MissionStatus, ValidationSeverity

logger = logging.getLogger(__name__)


@dataclass
class MissionAnalyticsSummary:
    """Aggregated analytics for all missions."""
    total_missions: int = 0
    completed_missions: int = 0
    failed_missions: int = 0
    cancelled_missions: int = 0
    success_rate: float = 0.0
    avg_planning_duration_seconds: float = 0.0
    avg_execution_duration_seconds: float = 0.0
    avg_validation_duration_seconds: float = 0.0
    avg_total_duration_seconds: float = 0.0
    total_validation_findings: int = 0
    findings_by_severity: dict[str, int] = field(default_factory=dict)
    missions_by_autonomy: dict[str, int] = field(default_factory=dict)
    missions_by_repository: dict[str, int] = field(default_factory=dict)
    retry_counts: dict[str, int] = field(default_factory=dict)
    model_usage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_missions": self.total_missions,
            "completed_missions": self.completed_missions,
            "failed_missions": self.failed_missions,
            "cancelled_missions": self.cancelled_missions,
            "success_rate": round(self.success_rate, 2),
            "avg_planning_duration_seconds": round(self.avg_planning_duration_seconds, 1),
            "avg_execution_duration_seconds": round(self.avg_execution_duration_seconds, 1),
            "avg_validation_duration_seconds": round(self.avg_validation_duration_seconds, 1),
            "avg_total_duration_seconds": round(self.avg_total_duration_seconds, 1),
            "total_validation_findings": self.total_validation_findings,
            "findings_by_severity": self.findings_by_severity,
            "missions_by_autonomy": self.missions_by_autonomy,
            "missions_by_repository": self.missions_by_repository,
            "retry_counts": self.retry_counts,
            "model_usage": self.model_usage,
        }


@dataclass
class MissionTimeline:
    """Timeline of status transitions for a single mission."""
    mission_id: str = ""
    transitions: list[dict[str, Any]] = field(default_factory=list)
    stage_durations: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "transitions": self.transitions,
            "stage_durations": {k: round(v, 1) for k, v in self.stage_durations.items()},
        }


def _parse_timestamp(ts: Optional[str]) -> Optional[datetime]:
    """Parse an ISO format timestamp."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _duration_seconds(start: Optional[str], end: Optional[str]) -> Optional[float]:
    """Calculate duration in seconds between two ISO timestamps."""
    start_dt = _parse_timestamp(start)
    end_dt = _parse_timestamp(end)
    if start_dt is None or end_dt is None:
        return None
    return (end_dt - start_dt).total_seconds()


def get_mission_analytics() -> MissionAnalyticsSummary:
    """Compute aggregated analytics for all missions.

    Analyzes mission data to produce success rates, average durations,
    validation findings distribution, and other key metrics.
    """
    summary = MissionAnalyticsSummary()

    # Get all missions
    missions = mission_storage.list_missions(limit=1000)
    summary.total_missions = len(missions)

    if not missions:
        return summary

    # Count by status
    status_counts: dict[str, int] = {}
    autonomy_counts: dict[str, int] = {}
    repo_counts: dict[str, int] = {}
    model_counts: dict[str, int] = {}

    planning_durations = []
    execution_durations = []
    validation_durations = []
    total_durations = []

    for mission in missions:
        # Status counts
        status_counts[mission.status] = status_counts.get(mission.status, 0) + 1

        # Autonomy distribution
        autonomy_counts[mission.autonomy_level] = autonomy_counts.get(mission.autonomy_level, 0) + 1

        # Repository distribution
        repo_counts[mission.target_repository] = repo_counts.get(mission.target_repository, 0) + 1

        # Model usage
        if mission.orchestrator_model:
            model = f"orchestrator:{mission.orchestrator_model}"
            model_counts[model] = model_counts.get(model, 0) + 1
        if mission.worker_model:
            model = f"worker:{mission.worker_model}"
            model_counts[model] = model_counts.get(model, 0) + 1
        if mission.validator_model:
            model = f"validator:{mission.validator_model}"
            model_counts[model] = model_counts.get(model, 0) + 1

        # Duration calculations
        created_dt = _parse_timestamp(mission.created_at)
        started_dt = _parse_timestamp(mission.started_at)
        completed_dt = _parse_timestamp(mission.completed_at)

        if created_dt and started_dt:
            planning_dur = (started_dt - created_dt).total_seconds()
            planning_durations.append(planning_dur)

        if started_dt and completed_dt:
            exec_dur = (completed_dt - started_dt).total_seconds()
            execution_durations.append(exec_dur)

        if created_dt and completed_dt:
            total_dur = (completed_dt - created_dt).total_seconds()
            total_durations.append(total_dur)

        # Validation findings per mission
        vr = mission_storage.get_validation_results(mission.id)
        summary.total_validation_findings += len(vr)
        for result in vr:
            sev = result.severity
            summary.findings_by_severity[sev] = summary.findings_by_severity.get(sev, 0) + 1

    summary.completed_missions = status_counts.get("completed", 0)
    summary.failed_missions = status_counts.get("failed", 0)
    summary.cancelled_missions = status_counts.get("cancelled", 0)

    # Success rate: completed / (completed + failed)
    finished = summary.completed_missions + summary.failed_missions
    if finished > 0:
        summary.success_rate = summary.completed_missions / finished

    # Average durations
    if planning_durations:
        summary.avg_planning_duration_seconds = sum(planning_durations) / len(planning_durations)
    if execution_durations:
        summary.avg_execution_duration_seconds = sum(execution_durations) / len(execution_durations)
    if total_durations:
        summary.avg_total_duration_seconds = sum(total_durations) / len(total_durations)

    summary.missions_by_autonomy = autonomy_counts
    summary.missions_by_repository = repo_counts
    summary.model_usage = model_counts

    return summary


def get_mission_timeline(mission_id: str) -> Optional[MissionTimeline]:
    """Get the timeline of status transitions for a mission.

    Reconstructs the timeline from checkpoints and mission state.
    """
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        return None

    timeline = MissionTimeline(mission_id=mission_id)

    # Build transitions from timestamps
    transitions = []

    created_dt = _parse_timestamp(mission.created_at)
    if created_dt:
        transitions.append({
            "status": MissionStatus.PLANNING.value,
            "timestamp": mission.created_at,
            "description": "Mission created",
        })

    started_dt = _parse_timestamp(mission.started_at)
    if started_dt:
        transitions.append({
            "status": MissionStatus.EXECUTING.value,
            "timestamp": mission.started_at,
            "description": "Execution started",
        })

    # Milestone transitions
    for ms in mission.milestones:
        if ms.started_at:
            transitions.append({
                "status": ms.status,
                "timestamp": ms.started_at,
                "description": f"Milestone '{ms.name}' started",
                "milestone_id": ms.id,
            })
        if ms.completed_at:
            transitions.append({
                "status": ms.status,
                "timestamp": ms.completed_at,
                "description": f"Milestone '{ms.name}' completed",
                "milestone_id": ms.id,
            })

    completed_dt = _parse_timestamp(mission.completed_at)
    if completed_dt:
        transitions.append({
            "status": mission.status,
            "timestamp": mission.completed_at,
            "description": f"Mission {mission.status}",
        })

    # Sort by timestamp
    transitions.sort(key=lambda t: t.get("timestamp", ""))
    timeline.transitions = transitions

    # Calculate stage durations
    if created_dt and started_dt:
        timeline.stage_durations["planning"] = (started_dt - created_dt).total_seconds()
    if started_dt and completed_dt:
        timeline.stage_durations["execution"] = (completed_dt - started_dt).total_seconds()
    if created_dt and completed_dt:
        timeline.stage_durations["total"] = (completed_dt - created_dt).total_seconds()

    return timeline


def get_validation_summary(mission_id: str) -> dict[str, Any]:
    """Get a summary of validation results for a mission.

    Returns counts by severity, top findings, and pass/fail status.
    """
    results = mission_storage.get_validation_results(mission_id)

    severity_counts: dict[str, int] = {}
    file_counts: dict[str, int] = {}
    for r in results:
        severity_counts[r.severity] = severity_counts.get(r.severity, 0) + 1
        if r.file_path:
            file_counts[r.file_path] = file_counts.get(r.file_path, 0) + 1

    # Determine if validation passed based on max severity
    has_blocker = severity_counts.get(ValidationSeverity.BLOCKER.value, 0) > 0
    has_critical = severity_counts.get(ValidationSeverity.CRITICAL.value, 0) > 0

    return {
        "mission_id": mission_id,
        "total_findings": len(results),
        "severity_counts": severity_counts,
        "files_affected": len(file_counts),
        "top_files": dict(sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:10]),
        "has_blockers": has_blocker,
        "has_criticals": has_critical,
        "passed": not (has_blocker or has_critical),
    }


def get_recent_missions(
    limit: int = 10,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Get recent missions with key metrics.

    Returns a list of missions with their duration, status, and validation summary.
    """
    missions = mission_storage.list_missions(status=status, limit=limit)
    result = []

    for mission in missions:
        duration = _duration_seconds(mission.created_at, mission.completed_at or mission.started_at)
        vr = mission_storage.get_validation_results(mission.id)

        result.append({
            "id": mission.id,
            "description": mission.description,
            "status": mission.status,
            "target_repository": mission.target_repository,
            "autonomy_level": mission.autonomy_level,
            "milestone_count": len(mission.milestones),
            "validation_findings": len(vr),
            "duration_seconds": round(duration, 1) if duration else None,
            "created_at": mission.created_at,
            "completed_at": mission.completed_at,
        })

    return result
