"""Route module: missions.

Provides the REST API for the mission control system:
- CRUD for missions
- Mission lifecycle: planning, execution, validation
- Cancel, resume, pause operations
- Validation results
- Statistics
"""

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from typing import Any, Dict, Optional

from hub.api.core import _verify_token
from hub.mission import analytics as mission_analytics
from hub.mission import controller
from hub.mission import sse as mission_sse
from hub.mission.models import (
    Mission,
    MissionStatus,
    ValidationResult,
    ValidationSeverity,
)
from hub.mission import storage as mission_storage


# ─── Mission CRUD ────────────────────────────────────────────────────────────


async def api_create_mission(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Create a new mission.

    Example body:
    {
        "description": "Add user authentication to the dashboard",
        "target_repository": "/path/to/repo",
        "orchestrator_model": "gpt-4o",
        "worker_model": "gpt-4o-mini",
        "validator_model": "claude-3-sonnet",
        "autonomy_level": "restricted_autonomous",
        "parallel_workers": false,
        "tags": ["feature", "auth"]
    }
    """
    description = body.get("description", "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="description is required")

    target_repository = body.get("target_repository", "").strip()
    if not target_repository:
        raise HTTPException(status_code=400, detail="target_repository is required")

    try:
        mission = controller.create_mission(
            description=description,
            target_repository=target_repository,
            orchestrator_model=body.get("orchestrator_model"),
            worker_model=body.get("worker_model"),
            validator_model=body.get("validator_model"),
            autonomy_level=body.get("autonomy_level", "restricted_autonomous"),
            parallel_workers=body.get("parallel_workers", False),
            created_by=body.get("created_by", "api"),
            tags=body.get("tags"),
        )
        return mission.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_list_missions(
    status: Optional[str] = None,
    target_repository: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    _auth: None = Depends(_verify_token),
):
    """List missions with optional filters."""
    missions = mission_storage.list_missions(
        status=status,
        target_repository=target_repository,
        limit=limit,
        offset=offset,
    )
    return {"missions": [m.to_dict() for m in missions]}


async def api_get_mission(mission_id: str, _auth: None = Depends(_verify_token)):
    """Get a mission by ID with full detail."""
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")

    result = mission.to_dict()
    # Include validation results
    results = mission_storage.get_validation_results(mission_id)
    result["validation_results"] = [r.to_dict() for r in results]
    return result


async def api_delete_mission(mission_id: str, _auth: None = Depends(_verify_token)):
    """Delete a mission."""
    deleted = mission_storage.delete_mission(mission_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Mission not found")
    return {"status": "ok", "message": "Mission deleted"}


# ─── Planning ────────────────────────────────────────────────────────────────


async def api_apply_plan(mission_id: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Apply a plan to a mission, creating milestones and features.

    Example body:
    {
        "milestones": [
            {
                "id": "ms-1",
                "name": "Planning",
                "description": "Analyze requirements",
                "success_criteria": ["Plan documented"],
                "features": [
                    {
                        "name": "Analyze codebase",
                        "description": "Review existing auth patterns",
                        "role": "worker"
                    }
                ]
            }
        ],
        "validation_contract": {
            "description": "Auth feature works correctly",
            "test_commands": ["pytest tests/test_auth.py"],
            "max_severity": "major"
        }
    }
    """
    milestones = body.get("milestones", [])
    if not milestones:
        raise HTTPException(status_code=400, detail="milestones are required")

    try:
        mission = controller.apply_plan(
            mission_id=mission_id,
            milestones=milestones,
            validation_contract=body.get("validation_contract"),
        )
        return mission.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Execution ───────────────────────────────────────────────────────────────


async def api_start_execution(mission_id: str, _auth: None = Depends(_verify_token)):
    """Start executing a planned mission."""
    try:
        mission = controller.start_execution(mission_id)
        return mission.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_update_feature(mission_id: str, feature_id: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Update a feature's status within a mission."""
    status = body.get("status")
    if not status:
        raise HTTPException(status_code=400, detail="status is required")

    try:
        mission = controller.update_feature_status(
            mission_id=mission_id,
            feature_id=feature_id,
            status=status,
            output=body.get("output", ""),
            error=body.get("error", ""),
        )
        return mission.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_complete_milestone(mission_id: str, milestone_id: str, _auth: None = Depends(_verify_token)):
    """Mark a milestone as completed and start the next one."""
    try:
        mission = controller.complete_milestone(mission_id, milestone_id)
        return mission.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_fail_milestone(mission_id: str, milestone_id: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Mark a milestone as failed."""
    error = body.get("error", "Unknown error")
    try:
        mission = controller.fail_milestone(mission_id, milestone_id, error)
        return mission.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Validation ──────────────────────────────────────────────────────────────


async def api_add_validation_result(mission_id: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Add a validation result for a mission."""
    result = ValidationResult(
        mission_id=mission_id,
        milestone_id=body.get("milestone_id"),
        severity=body.get("severity", ValidationSeverity.INFO.value),
        file_path=body.get("file_path"),
        line_number=body.get("line_number"),
        explanation=body.get("explanation", ""),
        suggested_correction=body.get("suggested_correction", ""),
    )
    try:
        saved = controller.add_validation_result(mission_id, result)
        return saved.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_get_validation_results(
    mission_id: str,
    milestone_id: Optional[str] = None,
    severity: Optional[str] = None,
    _auth: None = Depends(_verify_token),
):
    """Get validation results for a mission."""
    results = mission_storage.get_validation_results(
        mission_id=mission_id,
        milestone_id=milestone_id,
        severity=severity,
    )
    return {"results": [r.to_dict() for r in results]}


async def api_complete_validation(mission_id: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Complete the validation phase."""
    passed = body.get("passed", True)
    try:
        mission = controller.complete_validation(mission_id, passed)
        return mission.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Mission Control ─────────────────────────────────────────────────────────


async def api_cancel_mission(mission_id: str, body: Optional[Dict[str, Any]] = None, _auth: None = Depends(_verify_token)):
    """Cancel a running or planning mission."""
    body = body or {}
    reason = body.get("reason", "Cancelled by user")
    try:
        mission = controller.cancel_mission(mission_id, reason)
        return mission.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_resume_mission(mission_id: str, _auth: None = Depends(_verify_token)):
    """Resume a cancelled or paused mission."""
    try:
        mission = controller.resume_mission(mission_id)
        return mission.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_pause_mission(mission_id: str, _auth: None = Depends(_verify_token)):
    """Pause a running mission."""
    try:
        mission = controller.pause_mission(mission_id)
        return mission.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Approval Gates ──────────────────────────────────────────────────────────


async def api_request_approval(mission_id: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Request human approval for a sensitive operation."""
    operation = body.get("operation", "")
    if not operation:
        raise HTTPException(status_code=400, detail="operation is required")
    try:
        mission = controller.request_approval(
            mission_id=mission_id,
            operation=operation,
            details=body.get("details", ""),
        )
        return mission.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_approve_mission(mission_id: str, body: Optional[Dict[str, Any]] = None, _auth: None = Depends(_verify_token)):
    """Approve a pending approval request and resume the mission."""
    body = body or {}
    try:
        mission = controller.approve_mission(
            mission_id=mission_id,
            comment=body.get("comment", ""),
        )
        return mission.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def api_reject_mission(mission_id: str, body: Optional[Dict[str, Any]] = None, _auth: None = Depends(_verify_token)):
    """Reject a pending approval request and fail the mission."""
    body = body or {}
    reason = body.get("reason", "Rejected by user")
    try:
        mission = controller.reject_mission(mission_id, reason)
        return mission.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Statistics ──────────────────────────────────────────────────────────────


async def api_mission_stats(_auth: None = Depends(_verify_token)):
    """Get mission control statistics."""
    return controller.get_stats()


# ─── Logs ─────────────────────────────────────────────────────────────────────


async def api_get_mission_logs(
    mission_id: str,
    level: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    _auth: None = Depends(_verify_token),
):
    """Get execution logs for a mission."""
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    logs = mission_storage.get_mission_logs(
        mission_id=mission_id,
        level=level,
        limit=limit,
        offset=offset,
    )
    return {"logs": logs, "total": len(logs)}


async def api_stream_mission_logs(
    mission_id: str,
    since: Optional[str] = None,
    _auth: None = Depends(_verify_token),
):
    """Stream mission execution logs via Server-Sent Events (SSE).

    Connects to the mission log stream and delivers new entries in real time.
    """
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")

    return StreamingResponse(
        mission_sse.stream_mission_logs(mission_id, since=since),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Analytics ────────────────────────────────────────────────────────────────


async def api_mission_analytics(_auth: None = Depends(_verify_token)):
    """Get aggregated mission analytics."""
    summary = mission_analytics.get_mission_analytics()
    return summary.to_dict()


async def api_mission_timeline(mission_id: str, _auth: None = Depends(_verify_token)):
    """Get the timeline of status transitions for a mission."""
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    timeline = mission_analytics.get_mission_timeline(mission_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="Timeline not found")
    return timeline.to_dict()


async def api_validation_summary(mission_id: str, _auth: None = Depends(_verify_token)):
    """Get a summary of validation results for a mission."""
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission_analytics.get_validation_summary(mission_id)


# ─── Diffs ────────────────────────────────────────────────────────────────────


async def api_get_mission_diff(mission_id: str, _auth: None = Depends(_verify_token)):
    """Get changed files and diffs for a mission.

    Returns the list of artifacts containing file changes produced during
    mission execution.
    """
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")

    # Extract file changes from mission artifacts
    file_changes = []
    for artifact in mission.artifacts:
        if artifact.get("type") == "file_change":
            file_changes.append(artifact)

    return {
        "mission_id": mission_id,
        "file_changes": file_changes,
        "total_changes": len(file_changes),
        "artifacts": mission.artifacts,
    }


# ─── Fix-Revalidate Cycle ────────────────────────────────────────────────────


async def api_start_fix_revalidate(
    mission_id: str,
    body: Optional[Dict[str, Any]] = None,
    _auth: None = Depends(_verify_token),
):
    """Start the fix-revalidate cycle for a failed validation.

    Creates fix features from validation findings and sets the mission
    back to executing so workers can implement the fixes.
    """
    body = body or {}
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")

    # Find the milestone to fix (use the last completed/failed milestone)
    milestone_id = body.get("milestone_id")
    if not milestone_id:
        # Default to the last milestone
        if mission.milestones:
            milestone_id = mission.milestones[-1].id
        else:
            raise HTTPException(status_code=400, detail="No milestones found")

    max_retries = body.get("max_retries", 3)

    try:
        result = controller.start_fix_revalidate(
            mission_id=mission_id,
            milestone_id=milestone_id,
            max_retries=max_retries,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Route Registration ──────────────────────────────────────────────────────


def register(app):
    """Register mission routes with the FastAPI app."""
    # Mission CRUD
    app.post("/api/missions", status_code=201)(api_create_mission)
    app.get("/api/missions")(api_list_missions)
    app.get("/api/missions/{mission_id}")(api_get_mission)
    app.delete("/api/missions/{mission_id}")(api_delete_mission)

    # Planning
    app.post("/api/missions/{mission_id}/plan")(api_apply_plan)

    # Execution
    app.post("/api/missions/{mission_id}/start")(api_start_execution)
    app.post("/api/missions/{mission_id}/features/{feature_id}")(api_update_feature)
    app.post("/api/missions/{mission_id}/milestones/{milestone_id}/complete")(api_complete_milestone)
    app.post("/api/missions/{mission_id}/milestones/{milestone_id}/fail")(api_fail_milestone)

    # Validation
    app.post("/api/missions/{mission_id}/validation")(api_add_validation_result)
    app.get("/api/missions/{mission_id}/validation")(api_get_validation_results)
    app.post("/api/missions/{mission_id}/validation/complete")(api_complete_validation)

    # Mission control
    app.post("/api/missions/{mission_id}/cancel")(api_cancel_mission)
    app.post("/api/missions/{mission_id}/resume")(api_resume_mission)
    app.post("/api/missions/{mission_id}/pause")(api_pause_mission)

    # Approval gates
    app.post("/api/missions/{mission_id}/request-approval")(api_request_approval)
    app.post("/api/missions/{mission_id}/approve")(api_approve_mission)
    app.post("/api/missions/{mission_id}/reject")(api_reject_mission)

    # Statistics
    app.get("/api/missions/stats")(api_mission_stats)

    # Logs
    app.get("/api/missions/{mission_id}/logs")(api_get_mission_logs)
    app.get("/api/missions/{mission_id}/logs/stream")(api_stream_mission_logs)

    # Analytics
    app.get("/api/missions/analytics")(api_mission_analytics)
    app.get("/api/missions/{mission_id}/timeline")(api_mission_timeline)
    app.get("/api/missions/{mission_id}/validation-summary")(api_validation_summary)

    # Diffs
    app.get("/api/missions/{mission_id}/diff")(api_get_mission_diff)

    # Fix-revalidate cycle
    app.post("/api/missions/{mission_id}/fix-revalidate")(api_start_fix_revalidate)
