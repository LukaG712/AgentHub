"""Route module: services."""

from fastapi import Depends, WebSocket, WebSocketDisconnect
from hub.api.core import _service_health, _service_health_lock, _verify_token
from datetime import datetime
from typing import Any, Dict, List, Optional
import httpx
import json
import threading
import time


async def api_services_status(_auth: None = Depends(_verify_token)):
    """Get detailed status of all integrated services with health history."""
    import httpx

    async def _check_service(name: str, url: str, api_key: str = "") -> Dict[str, Any]:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{url}/health", headers=headers)
                status = "healthy" if resp.status_code == 200 else "unhealthy"
                return {
                    "name": name,
                    "url": url,
                    "status": status,
                    "response_time_ms": round(resp.elapsed.total_seconds() * 1000, 2),
                    "last_check": datetime.now().isoformat(),
                }
        except Exception as e:
            return {
                "name": name,
                "url": url,
                "status": "unreachable",
                "error": str(e),
                "last_check": datetime.now().isoformat(),
            }

    Ecton_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    Spectra_url = os.environ.get("Spectra_URL", "http://localhost:3000").rstrip("/")

    Ecton_status = await _check_service("Ecton", Ecton_url, os.environ.get("Ecton_API_KEY", ""))
    Spectra_status = await _check_service("Spectra", Spectra_url, os.environ.get("Spectra_API_KEY", ""))

    # Record health check
    with _service_health_lock:
        for svc_name, svc_status in [("Ecton", Ecton_status), ("Spectra", Spectra_status)]:
            history = _service_health.get(svc_name, [])
            history.append({
                "status": svc_status["status"],
                "timestamp": svc_status["last_check"],
            })
            # Keep last 100 checks
            if len(history) > 100:
                history = history[-100:]
            _service_health[svc_name] = history

    return {
        "services": {
            "Polter": {
                "name": "Polter",
                "status": "healthy",
                "version": "1.0.3",
                "last_check": datetime.now().isoformat(),
            },
            "Ecton": Ecton_status,
            "Spectra": Spectra_status,
        },
        "overall": "healthy" if all(
            s["status"] == "healthy"
            for s in [Ecton_status, Spectra_status]
        ) else "degraded",
    }


async def api_services_health_history(
    service: Optional[str] = None,
    limit: int = 50,
    _auth: None = Depends(_verify_token),
):
    """Get health check history for services."""
    with _service_health_lock:
        if service and service in _service_health:
            history = _service_health[service][-limit:]
            return {"service": service, "history": history}
        else:
            result = {}
            for svc, history in _service_health.items():
                result[svc] = history[-limit:]
            return {"history": result}


# ─── WebSocket Real-Time Feed ───────────────────────────────────────────────

# WebSocket connection manager
_ws_connections: Dict[str, set] = {
    "all": set(),
    "runs": set(),
    "schedules": set(),
}
_ws_lock = threading.Lock()


async def _ws_broadcast(channel: str, data: Dict[str, Any]) -> None:
    """Broadcast a message to all WebSocket clients on a channel."""
    import websockets

    with _ws_lock:
        connections = _ws_connections.get(channel, set()).copy()
        # Also broadcast to "all" channel
        all_connections = _ws_connections.get("all", set()).copy()

    messages = [json.dumps(data)]
    disconnected = set()

    for ws in connections | all_connections:
        try:
            await ws.send(json.dumps(data))
        except Exception:
            disconnected.add(ws)

    # Clean up disconnected clients
    with _ws_lock:
        for ch_set in _ws_connections.values():
            ch_set -= disconnected



def register(app):
    """Register services routes with the FastAPI app."""
    app.get("/api/services/status")(api_services_status)
    app.get("/api/services/health-history")(api_services_health_history)
