"""Evershade Valley API package.

Imports all route modules and registers them with the FastAPI app.
Each route module exposes a `register(app)` function.
"""

import importlib
from hub.api.core import create_app

__all__ = ["create_app", "app", "register_all_routes"]

_ROUTE_MODULES = [
    "health", "agents", "runs", "sessions", "memories", "skills", "routines",
    "coordinator", "bots", "obsidian", "ollama", "git", "remote", "crawl",
    "polter", "pipeline", "schedules", "streaming", "webhooks",
    "notifications", "analytics", "export_import", "api_keys", "services",
    "websocket", "rate_limits", "audit", "templates", "approvals", "files",
    "rbac", "jobs", "cache", "message_bus", "feature_flags", "deployments",
    "circuit_breakers", "api_versions", "dags", "tenants", "auto_review",
    "backup", "observability", "github_webhooks", "reports", "static_files",
    "app_routes", "knowledge_graph", "cluster", "marketplace",
]


def register_all_routes(app):
    """Register all route modules with the given FastAPI app."""
    for name in _ROUTE_MODULES:
        module = importlib.import_module(f"hub.api.{name}")
        module.register(app)


# Create the app instance and register all routes
app = create_app()
register_all_routes(app)
