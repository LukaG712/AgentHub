"""OpenTelemetry distributed tracing configuration.

Sets up automatic tracing for FastAPI routes and outgoing HTTPX requests,
enabling end-to-end tracing across Evershade Valley → Ecton → Spectra.

Configuration via environment variables:
    OTEL_SERVICE_NAME: Service identifier (default: "Evershade Valley")
    OTEL_EXPORTER_OTLP_ENDPOINT: OTLP collector endpoint (default: none, uses console)
    OTEL_TRACES_SAMPL_RATIO: Trace sampling ratio 0.0-1.0 (default: 1.0)

When an OTLP endpoint is configured, traces are exported in the OpenTelemetry
protocol format for ingestion by Jaeger, Zipkin, or any OTLP-compatible backend.
Without an endpoint, traces are printed to stdout as JSON for local debugging.
"""

import os
from typing import Optional

from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.context import get_current
from opentelemetry.propagate import inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


# ─── Singleton Tracer ────────────────────────────────────────────────────────

_tracer: Optional[trace.Tracer] = None
_propagator = TraceContextTextMapPropagator()


def get_tracer() -> trace.Tracer:
    """Get the global tracer instance."""
    return _tracer or trace.get_tracer("Evershade Valley")


def setup_tracing(app: Optional[FastAPI] = None) -> trace.TracerProvider:
    """Initialize OpenTelemetry tracing with auto-instrumentation.

    Args:
        app: FastAPI app to instrument. If None, only the provider is set up.

    Returns:
        The TracerProvider instance.
    """
    global _tracer

    service_name = os.environ.get("OTEL_SERVICE_NAME", "Evershade Valley")
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    sample_ratio = float(os.environ.get("OTEL_TRACES_SAMPLE_RATIO", "1.0"))

    # ─── Resource ────────────────────────────────────────────────────────
    resource = Resource.create({
        "service.name": service_name,
        "service.version": "1.0.0",
    })

    # ─── Provider ────────────────────────────────────────────────────────
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    sampler = ParentBasedTraceIdRatio(sample_ratio)
    provider = TracerProvider(resource=resource, sampler=sampler)
    trace.set_tracer_provider(provider)

    # ─── Exporter ────────────────────────────────────────────────────────
    if endpoint:
        try:
            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except Exception as e:
            print(f"Warning: OTLP exporter failed to connect: {e}")
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        # Console exporter for local debugging — prints traces to stdout
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    # ─── Auto-instrument FastAPI ─────────────────────────────────────────
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app) if app else FastAPIInstrumentor.instrument()
    except ImportError:
        pass  # FastAPI instrumentation optional

    # ─── Auto-instrument HTTPX ───────────────────────────────────────────
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor.instrument()
    except ImportError:
        pass  # HTTPX instrumentation optional

    # ─── Middleware for trace context injection ──────────────────────────
    if app:
        @app.middleware("http")
        async def trace_context_middleware(request: Request, call_next) -> Response:
            """Inject trace context into outgoing HTTP requests."""
            span_name = f"{request.method} {request.url.path}"
            with get_tracer().start_as_current_span(span_name) as span:
                span.set_attribute("http.method", request.method)
                span.set_attribute("http.url", str(request.url))
                span.set_attribute("http.flavor", "1.1")

                # Inject trace context into request headers for downstream services
                headers = dict(request.headers)
                inject(headers)

                response = await call_next(request)
                span.set_attribute("http.status_code", response.status_code)
                span.set_status(trace.Status(trace.StatusCode.OK))

            return response

    _tracer = get_tracer()
    return provider
