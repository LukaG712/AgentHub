"""Greenie API package.

Imports all route modules and registers them with the FastAPI app.
Each route module exposes a `register(app)` function.
"""

import importlib

from hub.api.core import (
    _AUTH_MAX_FAILURES,
    _AUTH_WINDOW_SECONDS,
    _SSE_MAX_EVENTS,
    _TERMINAL_EVENTS,
    # Auth failure rate limiting
    _auth_failure_lock,
    _auth_failure_store,
    _check_auth_rate_limit,
    _record_auth_failure,
    _sse_buffer_for_run,
    # SSE event store
    _sse_event_store,
    _sse_event_store_lock,
    _sse_remove_buffer,
    _sse_send_event,
    create_app,
)

__all__ = [
    "create_app", "app", "register_all_routes",
    # Auth rate limiting
    "_auth_failure_lock", "_auth_failure_store", "_AUTH_MAX_FAILURES", "_AUTH_WINDOW_SECONDS",
    "_check_auth_rate_limit", "_record_auth_failure",
    # SSE
    "_sse_event_store", "_sse_event_store_lock", "_SSE_MAX_EVENTS", "_TERMINAL_EVENTS",
    "_sse_buffer_for_run", "_sse_remove_buffer", "_sse_send_event",
]

_ROUTE_MODULES = [
    "health", "agents", "runs", "sessions", "memories", "skills", "routines",
    "coordinator", "bots", "obsidian", "ollama", "git", "remote", "crawl",
    "slinker", "pipeline", "schedules", "streaming", "webhooks",
    "notifications", "analytics", "export_import", "api_keys", "services",
    "websocket", "rate_limits", "audit", "templates", "approvals", "files",
    "rbac", "jobs", "cache", "message_bus", "feature_flags", "deployments",
    "circuit_breakers", "api_versions", "dags", "tenants", "auto_review",
    "backup", "observability", "github_webhooks", "reports", "static_files",
    "app_routes", "knowledge_graph", "cluster", "marketplace", "workflows",
    "workstations", "mcp", "plugins", "system", "emergency", "timeline", "credentials",
    "missions", "agent_harness", "capabilities",
]


def register_all_routes(app):
    """Register all route modules with the given FastAPI app."""
    for name in _ROUTE_MODULES:
        module = importlib.import_module(f"hub.api.{name}")
        module.register(app)


# Create the app instance and register all routes
app = create_app()
register_all_routes(app)
