"""Mission lifecycle controller.

Coordinates the full mission lifecycle:
- Create mission from a natural-language description
- Planning phase: decompose goal into milestones, features, validation contract
- Execution phase: run worker features, then validator
- Validation phase: check results against contract
- Completion: aggregate results
- Recovery: resume from checkpoint
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from hub.mission.models import (
    AutonomyLevel,
    FeatureRole,
    FeatureStatus,
    Mission,
    MissionCheckpoint,
    MissionFeature,
    MissionMilestone,
    MilestoneStatus,
    MissionStatus,
    ValidationContract,
    ValidationResult,
)
from hub.mission import storage as mission_storage

logger = logging.getLogger(__name__)


def _log(mission_id: str, level: str, message: str, source: str = "controller") -> None:
    """Log a mission execution event."""
    try:
        mission_storage.save_mission_log(mission_id, level, message, source)
    except Exception as e:
        logger.warning("Failed to save mission log: %s", e)


# ─── Mission Creation ────────────────────────────────────────────────────────

def create_mission(
    description: str,
    target_repository: str,
    orchestrator_model: Optional[str] = None,
    worker_model: Optional[str] = None,
    validator_model: Optional[str] = None,
    autonomy_level: str = AutonomyLevel.RESTRICTED.value,
    parallel_workers: bool = False,
    created_by: str = "api",
    tags: Optional[list[str]] = None,
) -> Mission:
    """Create a new mission in PLANNING status."""
    if not description.strip():
        raise ValueError("description is required")
    if not target_repository.strip():
        raise ValueError("target_repository is required")

    mission = Mission(
        description=description.strip(),
        target_repository=target_repository.strip(),
        orchestrator_model=orchestrator_model,
        worker_model=worker_model,
        validator_model=validator_model,
        autonomy_level=autonomy_level,
        parallel_workers=parallel_workers,
        created_by=created_by,
        tags=tags or [],
    )
    mission = mission_storage.save_mission(mission)
    logger.info("Mission created: %s", mission.id)
    _log(mission.id, "info", f"Mission created: {description}", "create")
    return mission


# ─── Planning Phase ──────────────────────────────────────────────────────────

def apply_plan(
    mission_id: str,
    milestones: list[dict[str, Any]],
    validation_contract: Optional[dict[str, Any]] = None,
) -> Mission:
    """Apply a planning result to a mission, creating milestones and features.

    This is called after the orchestrator LLM produces a plan.
    """
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise ValueError(f"Mission {mission_id} not found")

    now = datetime.now(timezone.utc).isoformat()
    mission.milestones = []
    for i, ms_data in enumerate(milestones):
        features = []
        for j, f_data in enumerate(ms_data.get("features", [])):
            feature = MissionFeature(
                mission_id=mission_id,
                milestone_id=ms_data.get("id", f"ms-{i}"),
                name=f_data.get("name", f"feature-{j}"),
                description=f_data.get("description", ""),
                role=f_data.get("role", FeatureRole.WORKER.value),
                model_override=f_data.get("model_override"),
                depends_on=f_data.get("depends_on", []),
                order=j,
            )
            features.append(feature)

        milestone = MissionMilestone(
            mission_id=mission_id,
            name=ms_data.get("name", f"milestone-{i}"),
            description=ms_data.get("description", ""),
            success_criteria=ms_data.get("success_criteria", []),
            features=features,
            order=i,
        )
        # Preserve the ID from the plan if provided
        if "id" in ms_data:
            milestone.id = ms_data["id"]
        mission.milestones.append(milestone)

    if validation_contract:
        vc = ValidationContract(
            mission_id=mission_id,
            description=validation_contract.get("description", ""),
            assertions=validation_contract.get("assertions", []),
            test_commands=validation_contract.get("test_commands", []),
            check_paths=validation_contract.get("check_paths", []),
            max_severity=validation_contract.get("max_severity", "major"),
        )
        if "id" in validation_contract:
            vc.id = validation_contract["id"]
        mission.validation_contract = vc

    mission.status = MissionStatus.PLANNING.value
    mission.updated_at = now
    mission = mission_storage.save_mission(mission)
    _save_checkpoint(mission, "Planning complete")
    _log(mission_id, "info", f"Plan applied with {len(mission.milestones)} milestones", "planning")
    logger.info("Plan applied to mission %s with %d milestones", mission_id, len(mission.milestones))
    return mission


# ─── Execution Phase ─────────────────────────────────────────────────────────

def start_execution(mission_id: str) -> Mission:
    """Transition a mission from PLANNING to EXECUTING."""
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise ValueError(f"Mission {mission_id} not found")
    if mission.status != MissionStatus.PLANNING.value:
        raise ValueError(f"Mission {mission_id} is in {mission.status} status, cannot start execution")

    now = datetime.now(timezone.utc).isoformat()
    mission.status = MissionStatus.EXECUTING.value
    mission.started_at = now
    mission.updated_at = now

    # Set first milestone to EXECUTING
    if mission.milestones:
        mission.milestones[0].status = MilestoneStatus.EXECUTING.value
        mission.milestones[0].started_at = now

    mission = mission_storage.save_mission(mission)
    _log(mission_id, "info", "Execution started", "execution")
    logger.info("Mission %s started execution", mission_id)
    return mission


def update_feature_status(
    mission_id: str,
    feature_id: str,
    status: str,
    output: str = "",
    error: str = "",
) -> Mission:
    """Update the status of a feature within a mission."""
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise ValueError(f"Mission {mission_id} not found")

    now = datetime.now(timezone.utc).isoformat()
    for milestone in mission.milestones:
        for feature in milestone.features:
            if feature.id == feature_id:
                feature.status = status
                if output:
                    feature.output = output
                if error:
                    feature.error = error
                if status == FeatureStatus.RUNNING.value and not feature.started_at:
                    feature.started_at = now
                if status in (FeatureStatus.COMPLETED.value, FeatureStatus.FAILED.value):
                    feature.completed_at = now
                break

    mission.updated_at = now
    mission = mission_storage.save_mission(mission)
    _log(mission_id, "info", f"Feature {feature_id} status: {status}", "feature")
    return mission


def complete_milestone(mission_id: str, milestone_id: str) -> Mission:
    """Mark a milestone as completed and start the next one."""
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise ValueError(f"Mission {mission_id} not found")

    now = datetime.now(timezone.utc).isoformat()
    current_ms = None
    for ms in mission.milestones:
        if ms.id == milestone_id:
            current_ms = ms
            break

    if current_ms is None:
        raise ValueError(f"Milestone {milestone_id} not found in mission {mission_id}")

    current_ms.status = MilestoneStatus.COMPLETED.value
    current_ms.completed_at = now

    # Start next milestone
    idx = mission.milestones.index(current_ms)
    if idx + 1 < len(mission.milestones):
        next_ms = mission.milestones[idx + 1]
        next_ms.status = MilestoneStatus.EXECUTING.value
        next_ms.started_at = now
    else:
        # All milestones done — move to validation
        if mission.validation_contract:
            mission.status = MissionStatus.VALIDATING.value
        else:
            mission.status = MissionStatus.COMPLETED.value
            mission.completed_at = now

    mission.updated_at = now
    mission = mission_storage.save_mission(mission)
    _save_checkpoint(mission, f"Milestone {milestone_id} completed")
    _log(mission_id, "info", f"Milestone {current_ms.name} completed", "milestone")
    logger.info("Milestone %s completed in mission %s", milestone_id, mission_id)
    return mission


def fail_milestone(mission_id: str, milestone_id: str, error: str) -> Mission:
    """Mark a milestone as failed."""
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise ValueError(f"Mission {mission_id} not found")

    now = datetime.now(timezone.utc).isoformat()
    for ms in mission.milestones:
        if ms.id == milestone_id:
            ms.status = MilestoneStatus.FAILED.value
            ms.completed_at = now
            break

    mission.status = MissionStatus.FAILED.value
    mission.error = error
    mission.completed_at = now
    mission.updated_at = now
    mission = mission_storage.save_mission(mission)
    _log(mission_id, "error", f"Milestone failed: {error}", "milestone")
    logger.error("Milestone %s failed in mission %s: %s", milestone_id, mission_id, error)
    return mission


# ─── Validation Phase ────────────────────────────────────────────────────────

def add_validation_result(mission_id: str, result: ValidationResult) -> ValidationResult:
    """Add a validation result for a mission."""
    result.mission_id = mission_id
    result = mission_storage.save_validation_result(result)

    # Update mission if there are blocker findings
    mission = mission_storage.get_mission(mission_id)
    if mission:
        all_results = mission_storage.get_validation_results(mission_id)
        blockers = [r for r in all_results if r.severity in ("blocker", "critical") and not r.verified]
        if blockers:
            mission.status = MissionStatus.FAILED.value
            mission.error = f"Validation failed: {len(blockers)} blocker/critical findings"
            mission.updated_at = datetime.now(timezone.utc).isoformat()
            mission_storage.save_mission(mission)

    return result


def complete_validation(mission_id: str, passed: bool) -> Mission:
    """Complete the validation phase."""
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise ValueError(f"Mission {mission_id} not found")

    now = datetime.now(timezone.utc).isoformat()
    if passed:
        mission.status = MissionStatus.COMPLETED.value
        mission.completed_at = now
    else:
        mission.status = MissionStatus.FAILED.value
        mission.error = "Validation failed"
        mission.completed_at = now

    mission.updated_at = now
    mission = mission_storage.save_mission(mission)
    _save_checkpoint(mission, "Validation complete")
    _log(mission_id, "info" if passed else "error", f"Validation {'passed' if passed else 'failed'}", "validation")
    logger.info("Mission %s validation complete: passed=%s", mission_id, passed)
    return mission


# ─── Mission Control ─────────────────────────────────────────────────────────

def cancel_mission(mission_id: str, reason: str = "Cancelled by user") -> Mission:
    """Cancel a running or planning mission."""
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise ValueError(f"Mission {mission_id} not found")
    if mission.status in (MissionStatus.COMPLETED.value, MissionStatus.CANCELLED.value):
        raise ValueError(f"Mission {mission_id} is already {mission.status}")

    now = datetime.now(timezone.utc).isoformat()
    mission.status = MissionStatus.CANCELLED.value
    mission.error = reason
    mission.completed_at = now
    mission.updated_at = now
    mission = mission_storage.save_mission(mission)
    _log(mission_id, "warn", f"Mission cancelled: {reason}", "control")
    logger.info("Mission %s cancelled: %s", mission_id, reason)
    return mission


def resume_mission(mission_id: str) -> Mission:
    """Resume a cancelled or paused mission from its last checkpoint."""
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise ValueError(f"Mission {mission_id} not found")
    if mission.status not in (MissionStatus.CANCELLED.value, MissionStatus.PAUSED.value):
        raise ValueError(f"Mission {mission_id} is in {mission.status} status, cannot resume")

    # Try to restore from checkpoint
    checkpoint = mission_storage.get_latest_checkpoint(mission_id)
    if checkpoint:
        try:
            state = json.loads(checkpoint.state_json)
            restored = Mission.from_dict(state)
            restored.id = mission_id  # Keep the same ID
            restored.status = MissionStatus.PLANNING.value
            restored.error = ""
            restored.completed_at = None
            restored.updated_at = datetime.now(timezone.utc).isoformat()
            mission = mission_storage.save_mission(restored)
            logger.info("Mission %s restored from checkpoint", mission_id)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to restore checkpoint for %s: %s", mission_id, e)

    # If no checkpoint or restore failed, just reset status
    if mission.status in (MissionStatus.CANCELLED.value, MissionStatus.PAUSED.value):
        mission.status = MissionStatus.PLANNING.value
        mission.error = ""
        mission.completed_at = None
        mission.updated_at = datetime.now(timezone.utc).isoformat()
        mission = mission_storage.save_mission(mission)

    _log(mission_id, "info", "Mission resumed", "control")
    return mission


def pause_mission(mission_id: str) -> Mission:
    """Pause a running mission."""
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise ValueError(f"Mission {mission_id} not found")
    if mission.status not in (MissionStatus.EXECUTING.value, MissionStatus.PLANNING.value, MissionStatus.VALIDATING.value):
        raise ValueError(f"Mission {mission_id} is in {mission.status} status, cannot pause")

    mission.status = MissionStatus.PAUSED.value
    mission.updated_at = datetime.now(timezone.utc).isoformat()
    mission = mission_storage.save_mission(mission)
    _save_checkpoint(mission, "Paused by user")
    _log(mission_id, "warn", "Mission paused by user", "control")
    logger.info("Mission %s paused", mission_id)
    return mission


# ─── Approval Gates ──────────────────────────────────────────────────────────

def request_approval(
    mission_id: str,
    operation: str,
    details: str = "",
) -> Mission:
    """Request human approval for a sensitive operation.

    Pauses the mission and sets it to WAITING_APPROVAL status.
    The mission will remain paused until approved or rejected.
    """
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise ValueError(f"Mission {mission_id} not found")

    now = datetime.now(timezone.utc).isoformat()
    mission.status = MissionStatus.WAITING_APPROVAL.value
    mission.error = f"Waiting for approval: {operation}"
    mission.updated_at = now

    # Store approval request in artifacts
    approval_request = {
        "type": "approval_request",
        "operation": operation,
        "details": details,
        "requested_at": now,
        "status": "pending",
    }
    mission.artifacts.append(approval_request)

    mission = mission_storage.save_mission(mission)
    _save_checkpoint(mission, f"Approval requested: {operation}")
    _log(mission_id, "warn", f"Approval requested: {operation}", "approval")
    logger.info("Mission %s waiting for approval: %s", mission_id, operation)
    return mission


def approve_mission(mission_id: str, comment: str = "") -> Mission:
    """Approve a pending approval request and resume the mission."""
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise ValueError(f"Mission {mission_id} not found")
    if mission.status != MissionStatus.WAITING_APPROVAL.value:
        raise ValueError(
            f"Mission {mission_id} is in {mission.status} status, not waiting for approval"
        )

    now = datetime.now(timezone.utc).isoformat()

    # Update the approval request artifact
    for artifact in mission.artifacts:
        if artifact.get("type") == "approval_request" and artifact.get("status") == "pending":
            artifact["status"] = "approved"
            artifact["approved_at"] = now
            artifact["comment"] = comment
            break

    # Determine the previous status from the checkpoint
    checkpoint = mission_storage.get_latest_checkpoint(mission_id)
    previous_status = MissionStatus.EXECUTING.value
    if checkpoint:
        try:
            state = json.loads(checkpoint.state_json)
            # Restore the status before WAITING_APPROVAL
            if state.get("status") in (MissionStatus.EXECUTING.value, MissionStatus.PLANNING.value, MissionStatus.VALIDATING.value):
                previous_status = state["status"]
        except (json.JSONDecodeError, KeyError):
            pass

    mission.status = previous_status
    mission.error = ""
    mission.updated_at = now
    mission = mission_storage.save_mission(mission)
    _log(mission_id, "info", f"Approval granted, resuming from {previous_status}", "approval")
    logger.info("Mission %s approved, resuming from %s", mission_id, previous_status)
    return mission


def reject_mission(mission_id: str, reason: str = "Rejected by user") -> Mission:
    """Reject a pending approval request and fail the mission."""
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise ValueError(f"Mission {mission_id} not found")
    if mission.status != MissionStatus.WAITING_APPROVAL.value:
        raise ValueError(
            f"Mission {mission_id} is in {mission.status} status, not waiting for approval"
        )

    now = datetime.now(timezone.utc).isoformat()

    # Update the approval request artifact
    for artifact in mission.artifacts:
        if artifact.get("type") == "approval_request" and artifact.get("status") == "pending":
            artifact["status"] = "rejected"
            artifact["rejected_at"] = now
            artifact["reason"] = reason
            break

    mission.status = MissionStatus.FAILED.value
    mission.error = f"Approval rejected: {reason}"
    mission.completed_at = now
    mission.updated_at = now
    mission = mission_storage.save_mission(mission)
    _log(mission_id, "error", f"Approval rejected: {reason}", "approval")
    logger.info("Mission %s approval rejected: %s", mission_id, reason)
    return mission


def needs_approval(mission: Mission, operation: str) -> bool:
    """Check if an operation requires approval based on the mission's autonomy level.

    Returns True if the operation should trigger an approval gate.
    """
    autonomy = mission.autonomy_level

    if autonomy == AutonomyLevel.FULL.value:
        return False
    if autonomy == AutonomyLevel.SUPERVISED.value:
        return True

    # Restricted autonomous: only sensitive operations need approval
    sensitive_operations = {
        "git_push", "deploy", "delete_branch", "force_push",
        "install_package", "system_command", "network_request",
    }
    return operation in sensitive_operations


# ─── Checkpoints ─────────────────────────────────────────────────────────────

def _save_checkpoint(mission: Mission, description: str) -> MissionCheckpoint:
    """Save a checkpoint for mission recovery."""
    checkpoint = MissionCheckpoint(
        mission_id=mission.id,
        state_json=json.dumps(mission.to_dict()),
        description=description,
    )
    return mission_storage.save_checkpoint(checkpoint)


# ─── Statistics ──────────────────────────────────────────────────────────────

def get_stats() -> dict[str, Any]:
    """Get mission control statistics."""
    return mission_storage.get_mission_stats()


# ─── Fix-Revalidate Cycle ────────────────────────────────────────────────────

MAX_FIX_RETRIES = 3


def create_fix_features(
    mission_id: str,
    milestone_id: str,
    validation_results: Optional[list[ValidationResult]] = None,
) -> Mission:
    """Create fix features from validation findings.

    When validation fails, this creates new worker features to address
    the findings. Each unverified blocker/critical/major finding becomes
    a fix feature.

    Args:
        mission_id: The mission to fix.
        milestone_id: The milestone that failed validation.
        validation_results: Specific results to fix. If None, fetches from storage.

    Returns:
        The updated mission with new fix features.
    """
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise ValueError(f"Mission {mission_id} not found")

    if validation_results is None:
        validation_results = mission_storage.get_validation_results(mission_id)

    # Find the target milestone
    target_ms = None
    for ms in mission.milestones:
        if ms.id == milestone_id:
            target_ms = ms
            break

    if target_ms is None:
        raise ValueError(f"Milestone {milestone_id} not found in mission {mission_id}")

    # Filter to unverified findings that need fixes
    fixable = [
        r for r in validation_results
        if not r.verified and r.severity in ("blocker", "critical", "major")
    ]

    if not fixable:
        _log(mission_id, "info", "No fixable findings", "fix_revalidate")
        return mission

    # Check retry count
    retry_count = 0
    for artifact in mission.artifacts:
        if artifact.get("type") == "fix_retry_count":
            retry_count = artifact.get("count", 0)
            break

    if retry_count >= MAX_FIX_RETRIES:
        _log(
            mission_id, "error",
            f"Max fix retries ({MAX_FIX_RETRIES}) exceeded",
            "fix_revalidate",
        )
        mission.status = MissionStatus.FAILED.value
        mission.error = f"Fix-revalidate cycle exceeded {MAX_FIX_RETRIES} retries"
        mission.completed_at = datetime.now(timezone.utc).isoformat()
        mission.updated_at = mission.completed_at
        mission_storage.save_mission(mission)
        return mission

    # Create fix features
    now = datetime.now(timezone.utc).isoformat()
    for result in fixable:
        feature = MissionFeature(
            mission_id=mission_id,
            milestone_id=milestone_id,
            name=f"Fix: {result.explanation[:80]}",
            description=f"Address validation finding: {result.explanation}",
            role=FeatureRole.WORKER.value,
            output=result.suggested_correction,
        )
        target_ms.features.append(feature)
        _log(
            mission_id, "info",
            f"Fix feature created: {feature.name}",
            "fix_revalidate",
        )

    # Update retry count
    retry_count += 1
    found = False
    for artifact in mission.artifacts:
        if artifact.get("type") == "fix_retry_count":
            artifact["count"] = retry_count
            found = True
            break
    if not found:
        mission.artifacts.append({"type": "fix_retry_count", "count": retry_count})

    # Set milestone back to executing for the fix features
    target_ms.status = MilestoneStatus.EXECUTING.value
    target_ms.completed_at = None
    mission.status = MissionStatus.EXECUTING.value
    mission.error = ""
    mission.updated_at = now

    mission_storage.save_mission(mission)
    _log(
        mission_id, "info",
        f"Created {len(fixable)} fix features (retry {retry_count}/{MAX_FIX_RETRIES})",
        "fix_revalidate",
    )
    return mission


def start_fix_revalidate(
    mission_id: str,
    milestone_id: str,
    max_retries: int = MAX_FIX_RETRIES,
) -> dict[str, Any]:
    """Start the fix-revalidate cycle for a failed validation.

    This is the main entry point for the fix-revalidate loop:
    1. Create fix features from validation findings
    2. Workers implement the fixes
    3. Re-run validation
    4. Repeat until passed or max retries exceeded

    Args:
        mission_id: The mission to fix.
        milestone_id: The milestone that failed validation.
        max_retries: Maximum number of fix-revalidate iterations.

    Returns:
        A dict with the cycle result: status, retry count, and final mission.
    """
    global MAX_FIX_RETRIES
    original_max = MAX_FIX_RETRIES
    MAX_FIX_RETRIES = max_retries

    result = {
        "mission_id": mission_id,
        "milestone_id": milestone_id,
        "status": "unknown",
        "retry_count": 0,
        "fix_features_created": 0,
    }

    try:
        # Step 1: Create fix features
        mission = create_fix_features(mission_id, milestone_id)
        result["retry_count"] = 0

        for artifact in mission.artifacts:
            if artifact.get("type") == "fix_retry_count":
                result["retry_count"] = artifact.get("count", 0)
                break

        # Count new fix features
        target_ms = None
        for ms in mission.milestones:
            if ms.id == milestone_id:
                target_ms = ms
                break

        if target_ms:
            fix_features = [
                f for f in target_ms.features
                if f.name.startswith("Fix:") and f.status == FeatureStatus.PENDING.value
            ]
            result["fix_features_created"] = len(fix_features)

        if mission.status == MissionStatus.FAILED.value:
            result["status"] = "max_retries_exceeded"
        else:
            result["status"] = "fix_features_created"
            _log(
                mission_id, "info",
                f"Fix-revalidate cycle started: {result['fix_features_created']} fix features",
                "fix_revalidate",
            )

    finally:
        MAX_FIX_RETRIES = original_max

    result["mission"] = mission.to_dict()
    return result
