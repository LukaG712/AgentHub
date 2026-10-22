"""Credential rotation REST API endpoints."""

from hub.credential_rotation import api_rotate_credential, api_rotation_history


async def api_rotate(credential_type: str, name: str = "", rotated_by: str = "api", reason: str = "routine"):
    """Rotate a credential."""
    result, status = api_rotate_credential(credential_type, name, rotated_by, reason)
    return result


async def api_history(credential_type: str = None, limit: int = 50):
    """Get rotation history."""
    return api_rotation_history(credential_type, limit)


def register(app):
    """Register credential rotation routes."""
    app.post("/api/credentials/rotate")(api_rotate)
    app.get("/api/credentials/history")(api_history)
