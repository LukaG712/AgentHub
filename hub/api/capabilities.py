"""Route module: service capabilities.

Provides an endpoint that reports what features and integrations
this service supports, allowing clients to adapt behavior based
on available capabilities.
"""

from typing import Any, Dict, List


async def api_capabilities():
    """Report the capabilities supported by this Greenie instance.

    Returns a structured list of features, integrations, and
    optional dependencies so clients can adapt behavior accordingly.
    """
    capabilities: Dict[str, Any] = {
        "service": "Greenie",
        "version": "1.0.3",
        "features": {
            "agents": {
                "supported": True,
                "description": "Agent execution via multiple providers",
            },
            "workflows": {
                "supported": True,
                "description": "Workflow engine with sequential and parallel execution",
                "step_types": ["agent", "service", "approval", "condition", "notify", "workstation", "planner", "worker", "validator", "milestone"],
                "triggers": ["manual", "schedule", "webhook", "file_watch"],
                "approval_gates": True,
                "cancellation": True,
                "retry_on_failure": True,
            },
            "pipelines": {
                "supported": True,
                "description": "Scheduled data pipelines",
            },
            "knowledge_graph": {
                "supported": True,
                "description": "Semantic search via Gobber",
            },
            "memory": {
                "supported": True,
                "description": "Persistent agent memory",
            },
            "obsidian": {
                "supported": True,
                "description": "Obsidian vault integration",
            },
            "ollama": {
                "supported": True,
                "description": "Local LLM via Ollama",
            },
            "streaming": {
                "supported": True,
                "description": "SSE streaming for agent runs",
            },
            "websockets": {
                "supported": True,
                "description": "Real-time WebSocket communication",
            },
            "rbac": {
                "supported": True,
                "description": "Role-based access control",
            },
            "audit_log": {
                "supported": True,
                "description": "Audit trail for sensitive operations",
            },
            "feature_flags": {
                "supported": True,
                "description": "Runtime feature toggles",
            },
            "circuit_breakers": {
                "supported": True,
                "description": "Circuit breaker pattern for service calls",
            },
            "cache": {
                "supported": True,
                "description": "Response caching with TTL",
            },
            "message_bus": {
                "supported": True,
                "description": "Pub/sub message bus",
            },
            "schedules": {
                "supported": True,
                "description": "Cron-based scheduling",
            },
            "routines": {
                "supported": True,
                "description": "Recurring task routines",
            },
            "workstations": {
                "supported": True,
                "description": "Docker-based workstations",
            },
            "plugins": {
                "supported": True,
                "description": "Plugin system for extensibility",
            },
            "marketplace": {
                "supported": True,
                "description": "Agent and skill marketplace",
            },
            "cluster": {
                "supported": True,
                "description": "Multi-instance cluster mode via Redis",
            },
            "csrf_protection": {
                "supported": True,
                "description": "CSRF protection for cookie-authenticated sessions",
            },
            "rate_limiting": {
                "supported": True,
                "description": "Rate limiting for expensive operations",
            },
            "opentelemetry": {
                "supported": True,
                "description": "OpenTelemetry tracing and metrics",
            },
            "backup_restore": {
                "supported": True,
                "description": "Database backup and restore via Speedy CLI",
            },
            "idempotency": {
                "supported": True,
                "description": "Idempotency keys for retryable operations",
            },
        },
        "integrations": {
            "slinker": {
                "type": "service",
                "optional": True,
                "description": "Code execution agent",
            },
            "trapper": {
                "type": "service",
                "optional": True,
                "description": "Web crawling and scraping",
            },
            "gobber": {
                "type": "service",
                "optional": True,
                "description": "Persistent storage and knowledge graph",
            },
            "hider": {
                "type": "service",
                "optional": True,
                "description": "Secrets management",
            },
            "poltergeist": {
                "type": "service",
                "optional": True,
                "description": "Notifications",
            },
            "shrewd": {
                "type": "service",
                "optional": True,
                "description": "LLM abstraction and routing",
            },
            "sneaker": {
                "type": "service",
                "optional": True,
                "description": "Observability and OTLP",
            },
            "slammer": {
                "type": "ui",
                "optional": True,
                "description": "Web dashboard",
            },
            "speedy": {
                "type": "cli",
                "optional": True,
                "description": "CLI tool",
            },
        },
        "api_versions": ["v1"],
    }
    return capabilities


def register(app):
    """Register capabilities route with the FastAPI app."""
    app.get("/api/capabilities")(api_capabilities)
