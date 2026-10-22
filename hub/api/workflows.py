"""Route module: workflows.

Provides the REST API for the workflow engine:
- CRUD for workflow definitions
- Execute workflows and track runs
- Approve/deny approval gates
- Webhook triggers
- Statistics
"""

from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Request
from typing import Any, Dict, List, Optional

from hub.api.core import _verify_token
from hub.workflow import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStep,
    WorkflowTrigger,
    StepType,
    TriggerType,
    RunStatus,
    storage,
    execute_workflow,
    resolve_approval,
    handle_webhook,
)


# ─── Workflow Definitions ───────────────────────────────────────────────────


async def api_create_workflow(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Create a new workflow definition.

    Example body:
    {
        "name": "Daily research digest",
        "description": "Search for news and summarize",
        "steps": [
            {
                "name": "Search news",
                "step_type": "service",
                "service": "trapper",
                "task": "SEARCH: latest AI news"
            },
            {
                "name": "Summarize",
                "step_type": "service",
                "service": "slinker",
                "task": "Summarize the research findings"
            }
        ],
        "triggers": [
            {
                "trigger_type": "schedule",
                "cron": "0 9 * * *",
                "enabled": true
            }
        ]
    }
    """
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    steps_data = body.get("steps", [])
    steps = []
    for i, s in enumerate(steps_data):
        step = WorkflowStep(
            name=s.get("name", f"step-{i}"),
            step_type=s.get("step_type", StepType.AGENT.value),
            agent=s.get("agent", ""),
            service=s.get("service", ""),
            task=s.get("task", ""),
            approval_description=s.get("approval_description", ""),
            approval_timeout_minutes=s.get("approval_timeout_minutes", 30),
            condition=s.get("condition"),
            notify_channel=s.get("notify_channel", ""),
            notify_message=s.get("notify_message", ""),
            order=s.get("order", i),
            depends_on=s.get("depends_on", []),
            on_failure=s.get("on_failure", "stop"),
            config=s.get("config", {}),
        )
        steps.append(step)

    triggers_data = body.get("triggers", [])
    triggers = []
    for t in triggers_data:
        trigger = WorkflowTrigger(
            trigger_type=t.get("trigger_type", TriggerType.SCHEDULE.value),
            cron=t.get("cron", ""),
            webhook_secret=t.get("webhook_secret", ""),
            webhook_path=t.get("webhook_path", ""),
            watch_paths=t.get("watch_paths", []),
            enabled=t.get("enabled", True),
            config=t.get("config", {}),
        )
        triggers.append(trigger)

    wf = WorkflowDefinition(
        name=name,
        description=body.get("description", ""),
        steps=steps,
        triggers=triggers,
        enabled=body.get("enabled", True),
        timeout_minutes=body.get("timeout_minutes", 0),
        created_by=body.get("created_by", "api"),
        tags=body.get("tags", []),
    )

    saved = storage.save_workflow_definition(wf)
    return saved.to_dict()


async def api_list_workflows(
    limit: int = 50,
    offset: int = 0,
    _auth: None = Depends(_verify_token),
):
    """List all workflow definitions."""
    workflows = storage.list_workflow_definitions(limit=limit, offset=offset)
    return {"workflows": [wf.to_dict() for wf in workflows]}


async def api_get_workflow(workflow_id: str, _auth: None = Depends(_verify_token)):
    """Get a workflow definition by ID."""
    wf = storage.get_workflow_definition(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf.to_dict()


async def api_update_workflow(workflow_id: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Update a workflow definition."""
    wf = storage.get_workflow_definition(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Update fields
    if "name" in body:
        wf.name = body["name"]
    if "description" in body:
        wf.description = body["description"]
    if "enabled" in body:
        wf.enabled = body["enabled"]
    if "timeout_minutes" in body:
        wf.timeout_minutes = body["timeout_minutes"]
    if "tags" in body:
        wf.tags = body["tags"]

    # Update steps if provided
    if "steps" in body:
        steps = []
        for i, s in enumerate(body["steps"]):
            step = WorkflowStep.from_dict(s) if isinstance(s, dict) else WorkflowStep()
            step.order = s.get("order", i) if isinstance(s, dict) else i
            steps.append(step)
        wf.steps = steps

    # Update triggers if provided
    if "triggers" in body:
        triggers = []
        for t in body["triggers"]:
            trigger = WorkflowTrigger.from_dict(t) if isinstance(t, dict) else WorkflowTrigger()
            triggers.append(trigger)
        wf.triggers = triggers

    wf.updated_at = datetime.now(timezone.utc).isoformat()
    saved = storage.save_workflow_definition(wf)
    return saved.to_dict()


async def api_delete_workflow(workflow_id: str, _auth: None = Depends(_verify_token)):
    """Delete a workflow definition."""
    deleted = storage.delete_workflow_definition(workflow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"status": "ok", "message": "Workflow deleted"}


# ─── Workflow Runs ──────────────────────────────────────────────────────────


async def api_run_workflow(workflow_id: str, body: Optional[Dict[str, Any]] = None, _auth: None = Depends(_verify_token)):
    """Execute a workflow immediately.

    Example body (optional):
    {
        "trigger_data": {"custom_key": "value"},
        "started_by": "user"
    }
    """
    wf = storage.get_workflow_definition(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if not wf.enabled:
        raise HTTPException(status_code=400, detail="Workflow is disabled")
    if not wf.steps:
        raise HTTPException(status_code=400, detail="Workflow has no steps")

    body = body or {}
    run = await execute_workflow(
        wf,
        trigger_type="manual",
        trigger_data=body.get("trigger_data", {}),
        started_by=body.get("started_by", "api"),
    )
    return run.to_dict()


async def api_list_runs(
    workflow_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    _auth: None = Depends(_verify_token),
):
    """List workflow runs with optional filters."""
    runs = storage.list_workflow_runs(
        workflow_id=workflow_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"runs": [r.to_dict() for r in runs]}


async def api_get_run(run_id: str, _auth: None = Depends(_verify_token)):
    """Get a workflow run by ID."""
    run = storage.get_workflow_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.to_dict()


async def api_cancel_run(run_id: str, _auth: None = Depends(_verify_token)):
    """Cancel a running workflow."""
    run = storage.get_workflow_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in (RunStatus.RUNNING.value, RunStatus.WAITING_APPROVAL.value, RunStatus.PENDING.value):
        raise HTTPException(status_code=400, detail=f"Cannot cancel run with status {run.status}")

    run.status = RunStatus.CANCELLED.value
    run.completed_at = datetime.now(timezone.utc).isoformat()
    storage.save_workflow_run(run)
    return run.to_dict()


async def api_delete_run(run_id: str, _auth: None = Depends(_verify_token)):
    """Delete a workflow run."""
    deleted = storage.delete_workflow_run(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"status": "ok", "message": "Run deleted"}


# ─── Workflow Approvals ─────────────────────────────────────────────────────


async def api_list_approvals(
    run_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    _auth: None = Depends(_verify_token),
):
    """List workflow approvals."""
    approvals = storage.list_workflow_approvals(run_id=run_id, status=status, limit=limit)
    return {"approvals": [a.to_dict() for a in approvals]}


async def api_approve_workflow(run_id: str, _auth: None = Depends(_verify_token)):
    """Approve a pending workflow approval, resuming execution."""
    # Update the approval record
    approvals = storage.list_workflow_approvals(run_id=run_id, status="pending", limit=1)
    if not approvals:
        raise HTTPException(status_code=404, detail="No pending approval found for this run")

    approval = approvals[0]
    approval.status = "approved"
    approval.resolved_at = datetime.now(timezone.utc).isoformat()
    approval.resolved_by = "api"
    storage.save_workflow_approval(approval)

    # Resume execution
    resolved = await resolve_approval(run_id, approved=True)
    if not resolved:
        # Execution may have already moved past the approval
        pass

    return {"status": "approved", "approval": approval.to_dict()}


async def api_deny_workflow(run_id: str, _auth: None = Depends(_verify_token)):
    """Deny a pending workflow approval, failing the step."""
    approvals = storage.list_workflow_approvals(run_id=run_id, status="pending", limit=1)
    if not approvals:
        raise HTTPException(status_code=404, detail="No pending approval found for this run")

    approval = approvals[0]
    approval.status = "denied"
    approval.resolved_at = datetime.now(timezone.utc).isoformat()
    approval.resolved_by = "api"
    storage.save_workflow_approval(approval)

    # Resume execution (will fail the step)
    resolved = await resolve_approval(run_id, approved=False)

    return {"status": "denied", "approval": approval.to_dict()}


# ─── Webhook Trigger ────────────────────────────────────────────────────────


async def api_webhook_trigger(request: Request, _auth: None = Depends(_verify_token)):
    """Handle a webhook trigger.

    The webhook path is determined by the request path.
    Signature verification is done via the X-Webhook-Signature header.
    """
    path = request.url.path
    signature = request.headers.get("X-Webhook-Signature", "")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    result = await handle_webhook(path, body, signature or None)

    if "error" in result:
        status = result.pop("status", 500)
        raise HTTPException(status_code=status, detail=result["error"])

    return result


# ─── Statistics ──────────────────────────────────────────────────────────────


async def api_workflow_stats(_auth: None = Depends(_verify_token)):
    """Get workflow engine statistics."""
    return storage.get_workflow_stats()


# ─── Route Registration ─────────────────────────────────────────────────────


def register(app):
    """Register workflow routes with the FastAPI app."""
    # Workflow definitions
    app.post("/api/workflows", status_code=201)(api_create_workflow)
    app.get("/api/workflows")(api_list_workflows)
    app.get("/api/workflows/{workflow_id}")(api_get_workflow)
    app.put("/api/workflows/{workflow_id}")(api_update_workflow)
    app.delete("/api/workflows/{workflow_id}")(api_delete_workflow)

    # Workflow runs
    app.post("/api/workflows/{workflow_id}/run", status_code=201)(api_run_workflow)
    app.get("/api/workflows/runs")(api_list_runs)
    app.get("/api/workflows/runs/{run_id}")(api_get_run)
    app.post("/api/workflows/runs/{run_id}/cancel")(api_cancel_run)
    app.delete("/api/workflows/runs/{run_id}")(api_delete_run)

    # Approvals
    app.get("/api/workflows/approvals")(api_list_approvals)
    app.post("/api/workflows/runs/{run_id}/approve")(api_approve_workflow)
    app.post("/api/workflows/runs/{run_id}/deny")(api_deny_workflow)

    # Webhook trigger
    app.post("/api/workflows/webhook/{path:path}")(api_webhook_trigger)

    # Statistics
    app.get("/api/workflows/stats")(api_workflow_stats)
