"""Prometheus metrics collection and exposition.

Exposes a /metrics endpoint for Prometheus/Grafana scraping with the following
metrics:

- http_requests_total: Counter of HTTP requests by method, endpoint, and status code.
- http_request_duration_seconds: Histogram of request latency in seconds.
- http_active_requests: Gauge of currently in-flight requests.
- evershade_valley_runs_total: Counter of agent runs by agent name and outcome.
- evershade_valley_pipeline_steps_total: Counter of pipeline steps executed.
- evershade_valley_queue_depth: Gauge of background job queue depth.
- evershade_valley_store_sizes: Gauge of in-memory store sizes.

Configuration:
    PROMETHEUS_ENABLED: Set to "false" to disable metrics (default: true)
"""

import os
import time
from typing import Optional, Callable, Awaitable, Any

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from prometheus_client.metrics_core import MetricWrapper
from starlette.requests import Request
from starlette.responses import Response


# ─── Registry ────────────────────────────────────────────────────────────────

registry = CollectorRegistry()

# ─── HTTP Metrics ────────────────────────────────────────────────────────────

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests by method, endpoint, and status",
    ["method", "endpoint", "status"],
    registry=registry,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=registry,
)

http_active_requests = Gauge(
    "http_active_requests",
    "Number of currently in-flight HTTP requests",
    registry=registry,
)

# ─── Evershade Valley-specific Metrics ───────────────────────────────────────────────

evershade_valley_runs_total = Counter(
    "evershade_valley_runs_total",
    "Total agent runs by agent and outcome",
    ["agent", "outcome"],
    registry=registry,
)

evershade_valley_pipeline_steps_total = Counter(
    "evershade_valley_pipeline_steps_total",
    "Total pipeline steps executed",
    ["service", "outcome"],
    registry=registry,
)

evershade_valley_queue_depth = Gauge(
    "evershade_valley_queue_depth",
    "Number of jobs in the background queue",
    registry=registry,
)

evershade_valley_store_sizes = Gauge(
    "evershade_valley_store_sizes",
    "Size of in-memory feature stores",
    ["store_name"],
    registry=registry,
)

# ─── Metrics Endpoint ────────────────────────────────────────────────────────

def create_metrics_endpoint() -> Callable:
    """Create a FastAPI route handler for /metrics."""

    async def metrics_endpoint() -> Response:
        """Return Prometheus-formatted metrics."""
        return Response(
            content=generate_latest(registry).decode("utf-8"),
            media_type=CONTENT_TYPE_LATEST,
        )

    return metrics_endpoint

# ─── Middleware Factory ──────────────────────────────────────────────────────

def create_metrics_middleware():
    """Create Starlette middleware that records HTTP metrics.

    Returns a middleware factory function.
    """

    async def metrics_middleware(request: Request, call_next: Callable) -> Response:
        """Record request count, latency, and active requests."""
        method = request.method
        endpoint = request.url.path

        http_active_requests.inc()
        start = time.time()
        status = "200"

        try:
            response = await call_next(request)
            status = str(response.status_code)
        except Exception:
            status = "500"
        finally:
            duration = time.time() - start
            http_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
            http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)
            http_active_requests.dec()

        return response

    return metrics_middleware

# ─── Helper Functions ────────────────────────────────────────────────────────

def increment_runs(agent: str, outcome: str):
    """Increment the agent runs counter."""
    evershade_valley_runs_total.labels(agent=agent, outcome=outcome).inc()


def increment_pipeline_steps(service: str, outcome: str):
    """Increment the pipeline steps counter."""
    evershade_valley_pipeline_steps_total.labels(service=service, outcome=outcome).inc()


def set_queue_depth(depth: int):
    """Set the current queue depth gauge."""
    evershade_valley_queue_depth.set(depth)


def set_store_size(store_name: str, size: int):
    """Set the size of an in-memory store."""
    evershade_valley_store_sizes.labels(store_name=store_name).set(size)


def set_store_sizes(sizes: dict):
    """Set sizes for multiple stores at once."""
    for name, size in sizes.items():
        set_store_size(name, size)
