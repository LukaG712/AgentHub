"""Emergency stop REST API endpoints.

Provides the kill switch endpoints for the Evershade platform.
"""

from hub.emergency_stop import emergency_manager


async def api_emergency_status():
    """Check the current emergency stop state."""
    return emergency_manager.status()


async def api_emergency_stop(activated_by: str = "api", reason: str = "manual", message: str = ""):
    """Activate the emergency stop (kill switch)."""
    return await emergency_manager.stop(activated_by=activated_by, reason=reason, message=message)


async def api_emergency_resume(resumed_by: str = "api"):
    """Resume operations after emergency stop."""
    return await emergency_manager.resume(resumed_by=resumed_by)


def register(app):
    """Register emergency stop routes with the FastAPI app."""
    app.get("/api/emergency/status")(api_emergency_status)
    app.post("/api/emergency/stop")(api_emergency_stop)
    app.post("/api/emergency/resume")(api_emergency_resume)
