"""Core infrastructure for the Greenie API.

This module contains shared infrastructure used by all route modules:
- In-memory stores with thread-safe locks
- SSE event store for streaming responses
- Authentication helpers
- App lifespan (startup/shutdown)
- Middleware (CORS, logging, metrics)
- Background tasks (scheduled pipelines, job queue)

Route modules import from this module to access stores and helpers.
"""

import asyncio
import contextlib
import json
import logging
import os
import queue
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from hub import agents, coordinator, memory, obsidian, ollama, providers, remote, skills
from hub import routines as routines_engine
from hub.config import load_config, save_config, set_primary_bot, validate_name
from hub.logging_config import setup_structured_logging, get_logger, RequestIDFilter
from hub import feature_store
from hub.runner import (
    Run,
    agent_status,
    get_run,
    list_runs,
    recover_stale_runs,
    run_agent,
    stop_run,
)

# Observability: tracing and metrics (optional, graceful fallback if deps missing)
try:
    from hub import tracing as tracing_module
except ImportError:
    tracing_module = None
try:
    from hub import metrics as metrics_module
except ImportError:
    metrics_module = None
try:
    from hub import plugins as plugins_module
except ImportError:
    plugins_module = None
try:
    from hub import cluster as cluster_module
except ImportError:
    cluster_module = None
try:
    from hub import marketplace as marketplace_module
except ImportError:
    marketplace_module = None

# Initialize structured logging
log_level = os.environ.get("LOG_LEVEL", "INFO")
setup_structured_logging(level=log_level)
logger = get_logger(__name__)

security = HTTPBearer(auto_error=False)

# ─── Static files directory ─────────────────────────────────────────────────

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# ─── Rate limiting for authentication failures ──────────────────────────────

_auth_failure_store: Dict[str, List[float]] = {}
_auth_failure_lock = threading.Lock()
_AUTH_MAX_FAILURES = 10
_AUTH_WINDOW_SECONDS = 60


def _check_auth_rate_limit(client_ip: str) -> None:
    """Rate limit authentication failures per IP address."""
    now = time.time()
    with _auth_failure_lock:
        if client_ip not in _auth_failure_store:
            _auth_failure_store[client_ip] = []
        failures = _auth_failure_store[client_ip]
        _auth_failure_store[client_ip] = [t for t in failures if now - t < _AUTH_WINDOW_SECONDS]
        failures = _auth_failure_store[client_ip]
        if len(failures) >= _AUTH_MAX_FAILURES:
            raise HTTPException(
                status_code=429,
                detail="Too many authentication failures. Try again later."
            )


def _record_auth_failure(client_ip: str) -> None:
    """Record an authentication failure for rate limiting."""
    now = time.time()
    with _auth_failure_lock:
        if client_ip not in _auth_failure_store:
            _auth_failure_store[client_ip] = []
        _auth_failure_store[client_ip].append(now)


# ─── SSE event store ────────────────────────────────────────────────────────

_sse_event_store: Dict[str, "SSERunStore"] = {}
_sse_event_store_lock = threading.Lock()
_SSE_MAX_EVENTS = 1000
_TERMINAL_EVENTS = {"complete", "error", "end"}
_sse_next_id: int = 0


class SSERunStore:
    """Bounded, append-only event store for one run."""

    __slots__ = ("events", "evicted_before_id")

    def __init__(self) -> None:
        self.events: list = []
        self.evicted_before_id: Optional[int] = None


def _sse_buffer_for_run(run_id: str) -> SSERunStore:
    """Get or create an SSE event store for a run."""
    with _sse_event_store_lock:
        if run_id not in _sse_event_store:
            _sse_event_store[run_id] = SSERunStore()
        return _sse_event_store[run_id]


def _sse_remove_buffer(run_id: str) -> None:
    """Remove an SSE event store after completion."""
    with _sse_event_store_lock:
        _sse_event_store.pop(run_id, None)


def _sse_send_event(run_id: str, event: str, data: str) -> None:
    """Send an SSE event to the store for a run."""
    global _sse_next_id
    sse_event = f"event: {event}\ndata: {data}\n\n"
    is_terminal = event in _TERMINAL_EVENTS

    with _sse_event_store_lock:
        if run_id not in _sse_event_store:
            _sse_event_store[run_id] = SSERunStore()
        store = _sse_event_store[run_id]

        _sse_next_id += 1
        event_id = _sse_next_id

        if len(store.events) >= _SSE_MAX_EVENTS:
            if is_terminal:
                removed = False
                for i in range(len(store.events)):
                    ev_id, ev_str = store.events[i]
                    if not any(f"event: {t}" in ev_str for t in _TERMINAL_EVENTS):
                        oldest_evicted = ev_id
                        store.events.pop(i)
                        removed = True
                        if store.evicted_before_id is None or oldest_evicted > store.evicted_before_id:
                            store.evicted_before_id = oldest_evicted
                        break
                if not removed and store.events:
                    oldest_evicted = store.events[0][0]
                    store.events.pop(0)
                    if store.evicted_before_id is None or oldest_evicted > store.evicted_before_id:
                        store.evicted_before_id = oldest_evicted
            else:
                oldest_evicted = store.events[0][0]
                store.events.pop(0)
                if store.evicted_before_id is None or oldest_evicted > store.evicted_before_id:
                    store.evicted_before_id = oldest_evicted

        store.events.append((event_id, sse_event))


# ─── Authentication helpers ─────────────────────────────────────────────────

def _get_api_key() -> str:
    key = os.environ.get("HUB_API_KEY", "")
    if not key:
        raise RuntimeError("HUB_API_KEY environment variable is not set. Refusing to start.")
    return key


def _verify_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> None:
    client_ip = request.client.host if request else "unknown"
    _check_auth_rate_limit(client_ip)
    if credentials is None:
        _record_auth_failure(client_ip)
        raise HTTPException(status_code=401, detail="Authorization header missing")
    expected = _get_api_key()
    if credentials.credentials != expected:
        _record_auth_failure(client_ip)
        raise HTTPException(status_code=401, detail="Invalid API key")


def _verify_token_or_query(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> None:
    """Verify token from Authorization header or cookie."""
    client_ip = request.client.host if request else "unknown"
    _check_auth_rate_limit(client_ip)
    expected = _get_api_key()
    if credentials is not None:
        if credentials.credentials == expected:
            return
    cookie_token = request.cookies.get("hub_api_key") if request else None
    if cookie_token is not None and cookie_token == expected:
        return
    _record_auth_failure(client_ip)
    raise HTTPException(status_code=401, detail="Invalid API key")


# ─── In-memory stores ───────────────────────────────────────────────────────

# Scheduled pipelines
_scheduled_pipelines: Dict[str, Dict[str, Any]] = {}
_scheduled_pipelines_lock = threading.Lock()
_scheduled_tasks: Dict[str, asyncio.Task] = {}

# Webhooks
_webhooks: Dict[str, Dict[str, Any]] = {}
_webhooks_lock = threading.Lock()

# Notification channels
_notification_channels: Dict[str, Dict[str, Any]] = {}
_notification_channels_lock = threading.Lock()

# Analytics
_analytics: Dict[str, Any] = {
    "api_calls": {},
    "task_durations": [],
    "daily_stats": {},
}
_analytics_lock = threading.Lock()

# API keys
_api_keys: Dict[str, Dict[str, Any]] = {}
_api_keys_lock = threading.Lock()

# Service health
_service_health: Dict[str, Dict[str, Any]] = {}
_service_health_lock = threading.Lock()

# Rate limits
_rate_limits: Dict[str, Dict[str, Any]] = {}
_rate_limits_lock = threading.Lock()

# Audit log
_audit_log: List[Dict[str, Any]] = []
_audit_log_lock = threading.Lock()

# Templates
_templates: Dict[str, Dict[str, Any]] = {}
_templates_lock = threading.Lock()

# Approval workflows
_approval_policies: Dict[str, Dict[str, Any]] = {}
_approval_policies_lock = threading.Lock()
_approval_requests: Dict[str, Dict[str, Any]] = {}
_approval_requests_lock = threading.Lock()

# RBAC
_rbac_roles: Dict[str, Dict[str, Any]] = {}
_rbac_roles_lock = threading.Lock()
_rbac_users: Dict[str, Dict[str, Any]] = {}
_rbac_users_lock = threading.Lock()

# Background jobs
_background_jobs: Dict[str, Dict[str, Any]] = {}
_background_jobs_lock = threading.Lock()

# Response cache
_response_cache: Dict[str, Dict[str, Any]] = {}
_response_cache_lock = threading.Lock()

# Message bus
_message_bus: Dict[str, List[Dict[str, Any]]] = {}
_message_bus_lock = threading.Lock()
_message_subscriptions: Dict[str, List[Dict[str, Any]]] = {}
_message_subscriptions_lock = threading.Lock()

# Feature flags
_feature_flags: Dict[str, Dict[str, Any]] = {}
_feature_flags_lock = threading.Lock()

# Deployments
_deployments: Dict[str, Dict[str, Any]] = {}
_deployments_lock = threading.Lock()

# Circuit breakers
_circuit_breakers: Dict[str, Dict[str, Any]] = {}
_circuit_breakers_lock = threading.Lock()

# API versions
_api_versions: Dict[str, Dict[str, Any]] = {}
_api_versions_lock = threading.Lock()

# DAG definitions
_dag_definitions: Dict[str, Dict[str, Any]] = {}
_dag_definitions_lock = threading.Lock()

# Multi-tenancy
_tenants: Dict[str, Dict[str, Any]] = {}
_tenants_lock = threading.Lock()
_tenant_resources: Dict[str, List[str]] = {}
_tenant_resources_lock = threading.Lock()

# Scheduled reports
_scheduled_reports: Dict[str, Dict[str, Any]] = {}
_scheduled_reports_lock = threading.Lock()

# Webhook configs (GitHub/GitLab)
_webhook_secrets: Dict[str, Dict[str, Any]] = {}
_webhook_secrets_lock = threading.Lock()

# File storage metadata
_file_storage: Dict[str, Dict[str, Any]] = {}
_file_storage_lock = threading.Lock()


# ─── CORS configuration ─────────────────────────────────────────────────────

_default_cors_origins = [
    "http://localhost:*",
    "http://127.0.0.1:*",
]


def _get_cors_origins() -> List[str]:
    """Get CORS allowed origins from config, falling back to defaults."""
    try:
        config = load_config()
        cors_cfg = config.get("cors", {})
        if cors_cfg.get("enabled", True):
            origins = cors_cfg.get("origins", _default_cors_origins)
            return origins
    except Exception:
        pass
    return _default_cors_origins


# ─── Startup validation ─────────────────────────────────────────────────────

def _validate_startup() -> Dict[str, Any]:
    """Validate configuration and return a status report."""
    issues: List[Dict[str, Any]] = []
    config = load_config()

    for agent_name, agent_cfg in config.get("agents", {}).items():
        runner_name = agent_cfg.get("runner", "junie")
        provider = providers.get_provider(runner_name)
        if provider is None:
            issues.append({
                "agent": agent_name,
                "severity": "error",
                "message": f"Provider '{runner_name}' not registered",
            })
        elif not provider.check_available():
            issues.append({
                "agent": agent_name,
                "severity": "warning",
                "message": f"Provider '{runner_name}' binary not found on PATH",
            })

        project_dir = agent_cfg.get("project_dir", "")
        if project_dir:
            p = Path(project_dir).expanduser().resolve()
            if not p.exists():
                issues.append({
                    "agent": agent_name,
                    "severity": "warning",
                    "message": f"Project directory does not exist: {project_dir}",
                })

        remote_cfg = remote.get_agent_remote_config(config, agent_name)
        if remote_cfg:
            target = remote.RemoteTarget(remote_cfg)
            if not target.is_available():
                issues.append({
                    "agent": agent_name,
                    "severity": "warning",
                    "message": f"Remote target '{remote_cfg.host}' is not reachable",
                })

    available_providers = []
    for pname in providers.list_providers():
        p = providers.get_provider(pname)
        if p:
            available_providers.append({
                "name": pname,
                "available": p.check_available(),
            })

    return {
        "issues": issues,
        "providers": available_providers,
        "healthy": len([i for i in issues if i["severity"] == "error"]) == 0,
    }


# ─── App factory ────────────────────────────────────────────────────────────

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown event handler."""
    recover_stale_runs()
    providers.ensure_default_providers()
    routines_engine.start_scheduler()
    try:
        from hub import queue_manager
        queue_manager.recover_queue()
    except Exception:
        pass
    try:
        from hub.runner import _build_run_index
        _build_run_index()
    except Exception:
        pass
    # Initialize persistent feature stores from SQLite
    try:
        _fs = feature_store.init_all()
        _webhooks.clear()
        _webhooks.update(_fs["webhooks"])
        _notification_channels.clear()
        _notification_channels.update(_fs["notification_channels"])
        _analytics["api_calls"].clear()
        _analytics["api_calls"].update(_fs["analytics"]["api_calls"])
        _analytics["task_durations"] = _fs["analytics"]["task_durations"]
        _analytics["daily_stats"].clear()
        _analytics["daily_stats"].update(_fs["analytics"]["daily_stats"])
        _api_keys.clear()
        _api_keys.update(_fs["api_keys"])
        _scheduled_pipelines.clear()
        _scheduled_pipelines.update(_fs["scheduled_pipelines"])
        _rate_limits.clear()
        _rate_limits.update(_fs["rate_limits"])
        _templates.clear()
        _templates.update(_fs["templates"])
        _approval_policies.clear()
        _approval_policies.update(_fs["approval_policies"])
        _approval_requests.clear()
        _approval_requests.update(_fs["approval_requests"])
        _rbac_roles.clear()
        _rbac_roles.update(_fs["rbac_roles"])
        _rbac_users.clear()
        _rbac_users.update(_fs["rbac_users"])
        _background_jobs.clear()
        _background_jobs.update(_fs["background_jobs"])
        _message_subscriptions.clear()
        _message_subscriptions.update(_fs["message_subscriptions"])
        _feature_flags.clear()
        _feature_flags.update(_fs["feature_flags"])
        _circuit_breakers.clear()
        _circuit_breakers.update(_fs["circuit_breakers"])
        _api_versions.clear()
        _api_versions.update(_fs["api_versions"])
        _dag_definitions.clear()
        _dag_definitions.update(_fs["dag_definitions"])
        _tenants.clear()
        _tenants.update(_fs["tenants"])
        _tenant_resources.clear()
        _tenant_resources.update(_fs["tenant_resources"])
        _scheduled_reports.clear()
        _scheduled_reports.update(_fs["scheduled_reports"])
        _webhook_secrets.clear()
        for platform, cfg in _fs.get("webhook_configs", {}).items():
            _webhook_secrets[platform] = {
                "secret": cfg.get("secret", ""),
                "pipelines": cfg.get("pipelines", []),
            }
        # Load additional stores that were missing
        _audit_log.clear()
        _audit_log.extend(_fs.get("audit_log", []))
        _file_storage.clear()
        _file_storage.update(_fs.get("file_storage", {}))
        _response_cache.clear()
        _response_cache.update(_fs.get("response_cache", {}))
        _deployments.clear()
        _deployments.update(_fs.get("deployments", {}))
        _message_bus.clear()
        for topic, messages in _fs.get("message_bus", {}).items():
            _message_bus[topic] = messages
        logger.info("Feature stores loaded from SQLite database")
    except Exception as e:
        logger.warning(f"Failed to load feature stores from database: {e}")
    # Initialize OpenTelemetry tracing
    if tracing_module is not None:
        try:
            tracing_module.setup_tracing(app)
            logger.info("OpenTelemetry tracing initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize tracing: {e}")
    # Load plugins from plugins directory
    if plugins_module is not None:
        try:
            loaded = plugins_module.load_plugins()
            if loaded:
                logger.info(f"Loaded {len(loaded)} plugins: {', '.join(loaded)}")
        except Exception as e:
            logger.warning(f"Failed to load plugins: {e}")
    # Initialize cluster support (Redis-based shared state)
    if cluster_module is not None:
        try:
            available = await cluster_module.cluster.initialize()
            if available:
                logger.info("Cluster mode enabled: multi-instance support active")
            else:
                logger.info("Cluster mode disabled: running in single-instance mode")
        except Exception as e:
            logger.warning(f"Failed to initialize cluster: {e}")
    # Initialize marketplace registry
    if marketplace_module is not None:
        try:
            marketplace_module.registry.initialize()
            logger.info("Marketplace registry initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize marketplace: {e}")
    yield
    routines_engine.stop_scheduler()
    # Shutdown cluster support
    if cluster_module is not None:
        try:
            await cluster_module.cluster.shutdown()
        except Exception as e:
            logger.warning(f"Failed to shutdown cluster: {e}")
    # Shutdown marketplace registry
    if marketplace_module is not None:
        try:
            marketplace_module.registry.shutdown()
        except Exception as e:
            logger.warning(f"Failed to shutdown marketplace: {e}")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Agent Hub",
        description="Unified Workflow orchestration platform — central API for agents, pipelines, and cross-service integration with Slinker and Trapper.",
        version="1.0.3",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_get_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    )

    # Prometheus metrics middleware
    if metrics_module is not None:
        app.add_middleware(metrics_module.create_metrics_middleware())

    # Plugin routes
    if plugins_module is not None:
        try:
            plugins_module.create_plugin_routes(app)
        except Exception as e:
            logger.warning(f"Failed to register plugin routes: {e}")

    # Request logging middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Log all requests with timing and correlation ID."""
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"{request.method} {request.url.path} {response.status_code} "
            f"{duration_ms:.1f}ms",
            extra={"request_id": request_id, "method": request.method,
                   "path": request.url.path, "status": response.status_code,
                   "duration_ms": round(duration_ms, 1)},
        )

        response.headers["X-Request-ID"] = request_id
        return response

    return app
