"""Automation engine for event-driven mission creation.

Handles GitHub webhooks, schedule-based triggers, idempotency,
rate limiting, and an action registry.
"""

import hashlib
import hmac
import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from hub.mission import controller
from hub.mission.models import Mission

logger = logging.getLogger(__name__)

# Idempotency store: event_hash -> (mission_id, timestamp)
_idempotency_store: dict[str, tuple[str, float]] = {}
_idempotency_ttl = 300  # 5 minutes

# Rate limiting: source -> list of timestamps
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_rate_limit_max = 10  # max requests per window
_rate_limit_window = 60  # seconds

# Schedule-based triggers
ScheduleTrigger = Callable[[], dict[str, Any]]
_schedule_triggers: list[dict[str, Any]] = []

# Webhook secret for HMAC verification
_webhook_secret: Optional[str] = None


def set_webhook_secret(secret: str) -> None:
    """Set the GitHub webhook secret for HMAC signature verification."""
    global _webhook_secret
    _webhook_secret = secret


def verify_webhook_signature(payload_bytes: bytes, signature: str) -> bool:
    """Verify a GitHub webhook HMAC signature.

    Returns True if the signature is valid, False otherwise.
    If no webhook secret is configured, skips verification.
    """
    if not _webhook_secret:
        logger.warning("No webhook secret configured, skipping signature verification")
        return True

    if not signature:
        return False

    # GitHub uses sha256=hex_signature format
    if not signature.startswith("sha256="):
        return False

    expected = hmac.new(
        _webhook_secret.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature[7:])


def handle_github_webhook(payload: dict[str, Any], signature: Optional[str] = None) -> dict[str, Any]:
    """Handle a GitHub webhook event and potentially create a mission.

    Supports: issues, pull_requests, check_suite, status events.
    """
    # Rate limiting
    source = payload.get("sender", {}).get("login", "unknown")
    if not _check_rate_limit(source):
        logger.warning("Rate limit exceeded for source: %s", source)
        return {"status": "rate_limited", "source": source}

    # Idempotency check
    event_type = payload.get("action", "")
    event_id = payload.get("id", "")
    event_obj = payload.get("issue") or payload.get("pull_request") or payload.get("check_suite") or {}
    event_title = event_obj.get("title", "")
    event_number = event_obj.get("number", "")

    event_hash = _compute_event_hash(event_type, event_id, event_title, event_number)
    if event_hash in _idempotency_store:
        existing_mission_id, timestamp = _idempotency_store[event_hash]
        if time.time() - timestamp < _idempotency_ttl:
            logger.info("Duplicate event, existing mission: %s", existing_mission_id)
            return {"status": "duplicate", "mission_id": existing_mission_id}
        else:
            # Entry expired, remove it
            del _idempotency_store[event_hash]

    # Parse event type
    event_name = payload.get("X-GitHub-Event", "")
    if not event_name:
        # Try to infer from payload structure
        if "issue" in payload:
            event_name = "issues"
        elif "pull_request" in payload:
            event_name = "pull_request"
        elif "check_suite" in payload:
            event_name = "check_suite"

    # Dispatch to handler
    if event_name == "issues" and event_type in ("opened", "labeled"):
        return _handle_issue_event(payload, event_hash)
    elif event_name == "pull_request" and event_type in ("opened", "synchronize"):
        return _handle_pr_event(payload, event_hash)
    elif event_name == "check_suite" and event_type == "completed":
        return _handle_check_suite_event(payload, event_hash)

    return {"status": "ignored", "event": event_name}


def _handle_issue_event(payload: dict[str, Any], event_hash: str) -> dict[str, Any]:
    """Handle a GitHub issue event."""
    issue = payload.get("issue", {})
    repo = payload.get("repository", {}).get("full_name", "unknown")
    title = issue.get("title", "")
    body = issue.get("body", "")
    labels = [l.get("name", "") for l in issue.get("labels", [])]

    # Create mission from issue
    description = f"GitHub Issue #{issue.get('number', '?')}: {title}\n\n{body}"
    target_repo = repo

    try:
        mission = controller.create_mission(
            description=description,
            target_repository=target_repo,
            created_by="github_webhook",
            tags=["github", "issue"] + labels,
        )
        _idempotency_store[event_hash] = (mission.id, time.time())
        logger.info("Mission created from GitHub issue: %s", mission.id)
        return {"status": "created", "mission_id": mission.id}
    except ValueError as e:
        logger.error("Failed to create mission from issue: %s", e)
        return {"status": "error", "error": str(e)}


def _handle_pr_event(payload: dict[str, Any], event_hash: str) -> dict[str, Any]:
    """Handle a GitHub pull request event."""
    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {}).get("full_name", "unknown")
    title = pr.get("title", "")
    body = pr.get("body", "")

    description = f"GitHub PR #{pr.get('number', '?')}: {title}\n\n{body}"
    target_repo = repo

    try:
        mission = controller.create_mission(
            description=description,
            target_repository=target_repo,
            created_by="github_webhook",
            tags=["github", "pr"],
        )
        _idempotency_store[event_hash] = (mission.id, time.time())
        logger.info("Mission created from GitHub PR: %s", mission.id)
        return {"status": "created", "mission_id": mission.id}
    except ValueError as e:
        logger.error("Failed to create mission from PR: %s", e)
        return {"status": "error", "error": str(e)}


def _handle_check_suite_event(payload: dict[str, Any], event_hash: str) -> dict[str, Any]:
    """Handle a GitHub check suite event (CI failure)."""
    check = payload.get("check_suite", {})
    repo = payload.get("repository", {}).get("full_name", "unknown")
    status = check.get("status", "")
    conclusion = check.get("conclusion", "")

    if conclusion != "failure":
        return {"status": "ignored", "reason": "check suite passed"}

    description = f"CI failure in {repo}: Check suite {check.get('id', '?')} concluded with {conclusion}"
    target_repo = repo

    try:
        mission = controller.create_mission(
            description=description,
            target_repository=target_repo,
            created_by="github_webhook",
            tags=["github", "ci_failure"],
        )
        _idempotency_store[event_hash] = (mission.id, time.time())
        logger.info("Mission created from CI failure: %s", mission.id)
        return {"status": "created", "mission_id": mission.id}
    except ValueError as e:
        logger.error("Failed to create mission from CI failure: %s", e)
        return {"status": "error", "error": str(e)}


def _compute_event_hash(event_type: str, event_id: str, title: str, number: str) -> str:
    """Compute a hash for idempotency checking."""
    raw = f"{event_type}:{event_id}:{title}:{number}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _check_rate_limit(source: str) -> bool:
    """Check if a source is within rate limits."""
    now = time.time()
    # Clean old entries
    _rate_limit_store[source] = [
        t for t in _rate_limit_store[source] if now - t < _rate_limit_window
    ]
    if len(_rate_limit_store[source]) >= _rate_limit_max:
        return False
    _rate_limit_store[source].append(now)
    return True


def cleanup_idempotency_store() -> int:
    """Clean expired entries from the idempotency store.

    Returns the number of entries removed.
    """
    now = time.time()
    expired_keys = [
        k for k, (_, ts) in _idempotency_store.items()
        if now - ts > _idempotency_ttl
    ]
    for k in expired_keys:
        del _idempotency_store[k]
    if expired_keys:
        logger.info("Cleaned %d expired idempotency entries", len(expired_keys))
    return len(expired_keys)


# ─── Schedule-based Triggers ─────────────────────────────────────────────────

def register_schedule_trigger(
    name: str,
    cron_expression: str,
    action: ScheduleTrigger,
    enabled: bool = True,
) -> None:
    """Register a schedule-based trigger.

    Args:
        name: Unique name for the trigger.
        cron_expression: Cron expression (e.g., "0 2 * * *" for daily at 2 AM).
        action: Callable that returns a dict with mission creation params.
        enabled: Whether the trigger is active.
    """
    # Check for duplicate names
    for trigger in _schedule_triggers:
        if trigger["name"] == name:
            raise ValueError(f"Schedule trigger '{name}' already registered")

    _schedule_triggers.append({
        "name": name,
        "cron": cron_expression,
        "action": action,
        "enabled": enabled,
        "last_run": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info("Schedule trigger registered: %s (cron: %s)", name, cron_expression)


def remove_schedule_trigger(name: str) -> bool:
    """Remove a schedule trigger by name."""
    for i, trigger in enumerate(_schedule_triggers):
        if trigger["name"] == name:
            _schedule_triggers.pop(i)
            logger.info("Schedule trigger removed: %s", name)
            return True
    return False


def get_schedule_triggers() -> list[dict[str, Any]]:
    """List all registered schedule triggers."""
    return [
        {
            "name": t["name"],
            "cron": t["cron"],
            "enabled": t["enabled"],
            "last_run": t["last_run"],
            "created_at": t["created_at"],
        }
        for t in _schedule_triggers
    ]


def toggle_schedule_trigger(name: str, enabled: bool) -> bool:
    """Enable or disable a schedule trigger."""
    for trigger in _schedule_triggers:
        if trigger["name"] == name:
            trigger["enabled"] = enabled
            logger.info("Schedule trigger %s: %s", name, "enabled" if enabled else "disabled")
            return True
    return False


def evaluate_schedule_triggers() -> list[dict[str, Any]]:
    """Evaluate all enabled schedule triggers and execute those that are due.

    Uses a simple cron parser for common patterns. Returns a list of results.
    """
    results = []
    now = datetime.now(timezone.utc)

    for trigger in _schedule_triggers:
        if not trigger["enabled"]:
            continue

        if not _is_due(trigger["cron"], trigger["last_run"], now):
            continue

        try:
            result = trigger["action"]()
            trigger["last_run"] = now.isoformat()
            results.append({
                "trigger": trigger["name"],
                "status": "executed",
                "result": result,
            })
            logger.info("Schedule trigger executed: %s", trigger["name"])
        except Exception as e:
            results.append({
                "trigger": trigger["name"],
                "status": "error",
                "error": str(e),
            })
            logger.error("Schedule trigger failed: %s: %s", trigger["name"], e)

    return results


def _is_due(cron_expression: str, last_run: Optional[str], now: datetime) -> bool:
    """Check if a cron trigger is due based on the last run time.

    Supports basic cron patterns: minute hour day month weekday.
    """
    if last_run is None:
        return True

    try:
        last_dt = datetime.fromisoformat(last_run)
    except (ValueError, TypeError):
        return True

    # Parse cron expression
    parts = cron_expression.strip().split()
    if len(parts) != 5:
        logger.warning("Invalid cron expression: %s", cron_expression)
        return False

    minute, hour, day, month, weekday = parts

    # Check if the current time matches the cron pattern
    if minute != "*" and str(now.minute) != minute:
        return False
    if hour != "*" and str(now.hour) != hour:
        return False
    if day != "*" and str(now.day) != day:
        return False
    if month != "*" and str(now.month) != month:
        return False
    if weekday != "*" and str(now.weekday()) != weekday:
        return False

    # Check if enough time has passed since last run (at least 1 minute)
    if (now - last_dt).total_seconds() < 60:
        return False

    return True


# ─── Action Registry ─────────────────────────────────────────────────────────

ACTION_REGISTRY: dict[str, Any] = {}


def register_action(name: str, handler: Any) -> None:
    """Register an automation action handler."""
    ACTION_REGISTRY[name] = handler
    logger.info("Action registered: %s", name)


def get_registered_actions() -> list[str]:
    """List registered action names."""
    return list(ACTION_REGISTRY.keys())


def execute_action(name: str, **kwargs: Any) -> Any:
    """Execute a registered action by name."""
    handler = ACTION_REGISTRY.get(name)
    if handler is None:
        raise ValueError(f"Action '{name}' not registered")
    return handler(**kwargs)
