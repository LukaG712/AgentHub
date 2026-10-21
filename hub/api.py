"""FastAPI application for the agent hub.

This module re-exports the app from hub.api package for backward compatibility.
The actual routes are split into separate modules under hub/api/ for maintainability.
"""

from hub.api import app, create_app, register_all_routes

__all__ = ["app", "create_app", "register_all_routes"]
