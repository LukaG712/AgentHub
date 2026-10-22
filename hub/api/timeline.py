"""Activity Timeline and Audit Trail REST API.

Provides endpoints for querying the unified activity timeline and security audit trail.
"""

from hub.activity_timeline import (
    query_timeline,
    query_audit,
    get_workflow_timeline,
    get_task_timeline,
    get_correlation_timeline,
    timeline_stats,
    record_event,
)


async def api_timeline_events(
    correlation_id=None, workflow_id=None, task_id=None, agent_id=None,
    service=None, category=None, start_time=None, end_time=None,
    limit=100, offset=0,
):
    """Query the activity timeline with filters."""
    events = query_timeline(
        correlation_id=correlation_id, workflow_id=workflow_id, task_id=task_id,
        agent_id=agent_id, service=service, category=category,
        start_time=start_time, end_time=end_time, limit=limit, offset=offset,
    )
    return {"events": events, "count": len(events)}


async def api_workflow_timeline(workflow_id: str):
    """Get the complete timeline for a specific workflow run."""
    events = get_workflow_timeline(workflow_id)
    return {"workflow_id": workflow_id, "events": events, "count": len(events)}


async def api_task_timeline(task_id: str):
    """Get the complete timeline for a specific task."""
    events = get_task_timeline(task_id)
    return {"task_id": task_id, "events": events, "count": len(events)}


async def api_correlation_timeline(correlation_id: str):
    """Get all events across services for a correlation ID."""
    events = get_correlation_timeline(correlation_id)
    return {"correlation_id": correlation_id, "events": events, "count": len(events)}


async def api_timeline_stats():
    """Get timeline statistics."""
    return timeline_stats()


async def api_record_event(
    event_type: str, category: str = "system", summary: str = None,
):
    """Record an event in the activity timeline."""
    event_id = record_event(event_type, event_type=event_type, category=category, summary=summary)
    return {"event_id": event_id}


async def api_audit_events(user_id=None, resource_type=None, start_time=None, end_time=None, limit=100, offset=0):
    """Query the security audit trail."""
    events = query_audit(
        user_id=user_id, resource_type=resource_type,
        start_time=start_time, end_time=end_time, limit=limit, offset=offset,
    )
    return {"events": events, "count": len(events)}


def register(app):
    """Register timeline and audit routes with the FastAPI app."""
    app.get("/api/timeline/events")(api_timeline_events)
    app.get("/api/timeline/workflow/{workflow_id}")(api_workflow_timeline)
    app.get("/api/timeline/task/{task_id}")(api_task_timeline)
    app.get("/api/timeline/correlation/{correlation_id}")(api_correlation_timeline)
    app.get("/api/timeline/stats")(api_timeline_stats)
    app.post("/api/timeline/record")(api_record_event)
    app.get("/api/audit/events")(api_audit_events)
