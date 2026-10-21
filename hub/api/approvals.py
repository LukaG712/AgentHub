"""Route module: approvals."""

from fastapi import Depends, HTTPException
from hub.api.core import _approval_policies, _approval_policies_lock, _verify_token
from datetime import datetime
from hub import feature_store
from hub import memory
from pathlib import Path
from typing import Any, Dict, List, Optional
import threading
import time
import uuid


async def api_list_approvals(
    session_id: Optional[str] = None,
    bot_id: Optional[str] = None,
    status: Optional[str] = None,
    _auth: None = Depends(_verify_token),
):
    approvals_list = memory.list_approvals(
        session_id=session_id,
        bot_id=bot_id,
        status=status,
    )
    return {"approvals": approvals_list}


async def api_approve(
    approval_id: str,
    _auth: None = Depends(_verify_token),
):
    existing = memory.get_approval(approval_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found")
    updated = memory.update_approval_status(approval_id, "approved")
    return updated


async def api_deny(
    approval_id: str,
    _auth: None = Depends(_verify_token),
):
    existing = memory.get_approval(approval_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found")
    updated = memory.update_approval_status(approval_id, "denied")
    return updated


# --- Auto Review Settings ---


async def api_set_approval_policy(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Configure which actions require human approval.

    Example body:
    {
        "enabled": true,
        "require_for": ["external_api", "file_write"],
        "auto_approve_agents": ["vault"]
    }
    """
    with _approval_policies_lock:
        _approval_policies["enabled"] = body.get("enabled", _approval_policies["enabled"])
        _approval_policies["require_for"] = body.get("require_for", [])
        _approval_policies["auto_approve_agents"] = body.get("auto_approve_agents", [])
    # Persist to database
    try:
        feature_store.save_approval_policy(_approval_policies)
    except Exception as e:
        logger.warning(f"Failed to save approval policy: {e}")
    return dict(_approval_policies)


async def api_get_approval_policy(_auth: None = Depends(_verify_token)):
    """Get current approval policy configuration."""
    with _approval_policies_lock:
        return dict(_approval_policies)


async def api_request_approval(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Create a new approval request for a pending action.

    Example body:
    {
        "action": "external_api",
        "description": "Agent wants to call external API",
        "agent": "researcher",
        "details": {"url": "https://api.example.com/data"},
        "timeout_minutes": 30
    }
    """
    action = body.get("action", "").strip()
    if not action:
        raise HTTPException(status_code=400, detail="action is required")

    approval_id = f"appr-{uuid.uuid4().hex[:8]}"
    approval = {
        "id": approval_id,
        "action": action,
        "description": body.get("description", ""),
        "agent": body.get("agent", ""),
        "details": body.get("details", {}),
        "status": "pending",  # pending, approved, denied, expired
        "created_at": datetime.now().isoformat(),
        "resolved_at": None,
        "resolved_by": None,
        "timeout_minutes": body.get("timeout_minutes", 30),
    }

    with _approvals_lock:
        _approvals[approval_id] = approval

    # Persist to database
    try:
        feature_store.save_approval_request(approval)
    except Exception as e:
        logger.warning(f"Failed to save approval request: {e}")

    # Emit webhook event
    _emit_event("approval.pending", {"approval_id": approval_id, "action": action})

    return approval


async def api_list_approvals(
    status: Optional[str] = None,
    agent: Optional[str] = None,
    _auth: None = Depends(_verify_token),
):
    """List approval requests, optionally filtered by status or agent."""
    with _approvals_lock:
        approvals = list(_approvals.values())

    if status:
        approvals = [a for a in approvals if a["status"] == status]
    if agent:
        approvals = [a for a in approvals if a["agent"] == agent]

    # Check for expired approvals
    now = datetime.now()
    for a in approvals:
        if a["status"] == "pending":
            created = datetime.fromisoformat(a["created_at"])
            timeout = a.get("timeout_minutes", 30)
            if (now - created).total_seconds() > timeout * 60:
                a["status"] = "expired"
                a["resolved_at"] = now.isoformat()

    return {"approvals": approvals}


async def api_approve(approval_id: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Approve a pending approval request."""
    with _approvals_lock:
        approval = _approvals.get(approval_id)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")
        if approval["status"] != "pending":
            raise HTTPException(status_code=400, detail=f"Approval is {approval['status']}")

        approval["status"] = "approved"
        approval["resolved_at"] = datetime.now().isoformat()
        approval["resolved_by"] = body.get("user", "api")
        approval["notes"] = body.get("notes", "")

    # Persist to database
    try:
        feature_store.save_approval_request(approval)
    except Exception as e:
        logger.warning(f"Failed to save approval decision: {e}")

    _emit_event("approval.approved", {"approval_id": approval_id, "action": approval["action"]})

    return approval


async def api_deny(approval_id: str, body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Deny a pending approval request."""
    with _approvals_lock:
        approval = _approvals.get(approval_id)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")
        if approval["status"] != "pending":
            raise HTTPException(status_code=400, detail=f"Approval is {approval['status']}")

        approval["status"] = "denied"
        approval["resolved_at"] = datetime.now().isoformat()
        approval["resolved_by"] = body.get("user", "api")
        approval["notes"] = body.get("notes", "")

    # Persist to database
    try:
        feature_store.save_approval_request(approval)
    except Exception as e:
        logger.warning(f"Failed to save approval decision: {e}")

    _emit_event("approval.denied", {"approval_id": approval_id, "action": approval["action"]})

    return approval


async def api_approval_stats(_auth: None = Depends(_verify_token)):
    """Get approval statistics: counts by status and action."""
    with _approvals_lock:
        approvals = list(_approvals.values())

    from collections import Counter
    by_status = Counter(a["status"] for a in approvals)
    by_action = Counter(a["action"] for a in approvals)

    return {
        "total": len(approvals),
        "pending": by_status.get("pending", 0),
        "by_status": dict(by_status),
        "by_action": dict(by_action),
    }


# ─── File Storage ───────────────────────────────────────────────────────────

# In-memory file metadata store
_file_store: Dict[str, Dict[str, Any]] = {}
_file_store_lock = threading.Lock()

# Directory for uploaded files
_UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
_UPLOAD_DIR.mkdir(exist_ok=True)

# Max file size: 50MB
_MAX_FILE_SIZE = 50 * 1024 * 1024



def register(app):
    """Register approvals routes with the FastAPI app."""
    app.get("/api/approvals")(api_list_approvals)
    app.post("/api/approvals/{approval_id}/approve")(api_approve)
    app.post("/api/approvals/{approval_id}/deny")(api_deny)
    app.post("/api/approvals/policy")(api_set_approval_policy)
    app.get("/api/approvals/policy")(api_get_approval_policy)
    app.post("/api/approvals/request", status_code=201)(api_request_approval)
    app.get("/api/approvals")(api_list_approvals)
    app.post("/api/approvals/{approval_id}/approve")(api_approve)
    app.post("/api/approvals/{approval_id}/deny")(api_deny)
    app.get("/api/approvals/stats")(api_approval_stats)
