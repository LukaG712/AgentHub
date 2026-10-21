"""Route module: circuit_breakers."""

from fastapi import Depends, HTTPException
from hub.api.core import _api_versions, _api_versions_lock, _circuit_breakers, _circuit_breakers_lock, _verify_token
from datetime import datetime
from hub import feature_store
from typing import Any, Dict, List, Optional
import threading
import time


async def api_list_circuit_breakers(_auth: None = Depends(_verify_token)):
    """Get circuit breaker state for all services."""
    with _circuit_breakers_lock:
        breakers = {}
        for service, cb in _circuit_breakers.items():
            breakers[service] = {
                "state": cb["state"],
                "failure_count": cb["failure_count"],
                "success_count": cb["success_count"],
                "last_failure_at": cb["last_failure_at"],
                "last_state_change": cb["last_state_change"],
            }
    return {"circuit_breakers": breakers}


async def api_record_circuit_result(
    service: str,
    body: Dict[str, Any],
    _auth: None = Depends(_verify_token),
):
    """Record a success or failure for a service's circuit breaker.

    Example body:
    {
        "success": true
    }
    """
    success = body.get("success", True)
    if success:
        state = _record_success(service)
    else:
        state = _record_failure(service)

    return {"service": service, "new_state": state}


async def api_check_circuit(service: str, _auth: None = Depends(_verify_token)):
    """Check if a service call is allowed by the circuit breaker."""
    allowed = _can_execute(service)
    cb = _get_circuit_state(service)
    return {
        "service": service,
        "allowed": allowed,
        "state": cb["state"],
    }


async def api_reset_circuit_breaker(service: str, _auth: None = Depends(_verify_token)):
    """Reset a circuit breaker to closed state."""
    with _circuit_breakers_lock:
        if service not in _circuit_breakers:
            raise HTTPException(status_code=404, detail="Service circuit breaker not found")
        _circuit_breakers[service] = {
            "service": service,
            "state": "closed",
            "failure_count": 0,
            "success_count": 0,
            "last_failure_at": None,
            "last_state_change": datetime.now().isoformat(),
            "failure_threshold": _CB_DEFAULT_FAILURE_THRESHOLD,
            "recovery_timeout": _CB_DEFAULT_RECOVERY_TIMEOUT,
            "success_threshold": _CB_DEFAULT_SUCCESS_THRESHOLD,
        }
    # Persist to database
    try:
        feature_store.save_circuit_breaker(service, "closed", 0)
    except Exception as e:
        logger.warning(f"Failed to reset circuit breaker: {e}")
    return {"status": "ok", "service": service, "state": "closed"}


async def api_set_circuit_config(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Configure circuit breaker thresholds for a service.

    Example body:
    {
        "service": "Spectra",
        "failure_threshold": 5,
        "recovery_timeout": 60,
        "success_threshold": 3
    }
    """
    service = body.get("service", "").strip()
    if not service:
        raise HTTPException(status_code=400, detail="service is required")

    cb = _get_circuit_state(service)
    with _circuit_breakers_lock:
        if "failure_threshold" in body:
            cb["failure_threshold"] = body["failure_threshold"]
        if "recovery_timeout" in body:
            cb["recovery_timeout"] = body["recovery_timeout"]
        if "success_threshold" in body:
            cb["success_threshold"] = body["success_threshold"]

    return {"status": "ok", "config": cb}


# ─── API Versioning & Deprecation ───────────────────────────────────────────

# API version registry
_api_versions: Dict[str, Dict[str, Any]] = {
    "v1": {
        "version": "v1",
        "status": "current",  # current, deprecated, sunset
        "release_date": "2024-01-01",
        "deprecation_date": None,
        "sunset_date": None,
        "description": "Current stable API version",
    },
}
_api_versions_lock = threading.Lock()

# Deprecated endpoint mappings: old_path -> new_path
_deprecated_endpoints: Dict[str, Dict[str, Any]] = {}
_deprecated_endpoints_lock = threading.Lock()



def register(app):
    """Register circuit_breakers routes with the FastAPI app."""
    app.get("/api/circuit-breakers")(api_list_circuit_breakers)
    app.post("/api/circuit-breakers/{service}/record")(api_record_circuit_result)
    app.post("/api/circuit-breakers/{service}/check")(api_check_circuit)
    app.post("/api/circuit-breakers/{service}/reset")(api_reset_circuit_breaker)
    app.post("/api/circuit-breakers/config")(api_set_circuit_config)
