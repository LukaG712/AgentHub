"""Route module: observability."""

from fastapi import HTTPException
from starlette.responses import StreamingResponse
from hub import llm_providers as llm_module
from hub import providers
from typing import Any, Dict, List, Optional
import json

try:
    from hub import metrics as metrics_module
except ImportError:
    metrics_module = None


async def api_metrics():
    """Prometheus metrics endpoint for Grafana scraping."""
    if metrics_module is None:
        raise HTTPException(status_code=503, detail="Metrics not available")
    return metrics_module.create_metrics_endpoint()()


async def api_llm_providers():
    """List all available LLM providers and their status."""
    if llm_module is None:
        raise HTTPException(status_code=503, detail="LLM providers not available")
    return {"providers": llm_module.get_available_providers()}


async def api_llm_complete(body: Dict[str, Any]):
    """Send a completion request to the configured LLM provider."""
    if llm_module is None:
        raise HTTPException(status_code=503, detail="LLM providers not available")
    provider_name = body.get("provider")
    prompt = body.get("prompt", "")
    system = body.get("system")
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")
    provider = llm_module.get_llm_provider(provider_name)
    if not provider.check_available():
        raise HTTPException(status_code=503, detail=f"Provider '{provider.name}' is not available")
    result = await provider.complete(prompt, system=system)
    return {"provider": provider.name, "content": result}


async def api_llm_stream(body: Dict[str, Any]):
    """Stream a completion from the configured LLM provider via SSE."""
    if llm_module is None:
        raise HTTPException(status_code=503, detail="LLM providers not available")
    provider_name = body.get("provider")
    prompt = body.get("prompt", "")
    system = body.get("system")
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")
    provider = llm_module.get_llm_provider(provider_name)
    if not provider.check_available():
        raise HTTPException(status_code=503, detail=f"Provider '{provider.name}' is not available")
    async def event_generator():
        try:
            async for chunk in provider.stream(prompt, system=system):
                yield f'data: {json.dumps({"content": chunk})}\n\n'
            yield 'data: {"done": true}\n\n'
        except Exception as e:
            yield f'data: {json.dumps({"error": str(e)})}\n\n'
    return StreamingResponse(event_generator(), media_type="text/event-stream")



def register(app):
    """Register observability routes with the FastAPI app."""
    app.get("/metrics")(api_metrics)
    app.get("/api/llm/providers")(api_llm_providers)
    app.post("/api/llm/complete")(api_llm_complete)
    app.post("/api/llm/stream")(api_llm_stream)
