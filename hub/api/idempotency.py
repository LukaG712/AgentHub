"""Idempotency key middleware for retryable operations.

Allows clients to include an idempotency key header (X-Idempotency-Key)
on POST/PUT requests. If the same key is used again, the original response
is returned without re-executing the operation. This makes retries safe
for operations like workflow creation, agent execution, and backup.

Configuration:
    IDEMPOTENCY_ENABLED: Enable/disable idempotency (default: True)
    IDEMPOTENCY_TTL_SECONDS: How long to store keys (default: 86400 = 24h)
"""

import hashlib
import os
import time
import threading
from typing import Dict, Optional, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


# ─── Configuration ────────────────────────────────────────────────

IDEMPOTENCY_ENABLED = os.environ.get("IDEMPOTENCY_ENABLED", "true").lower() in ("true", "1", "yes")
IDEMPOTENCY_TTL_SECONDS = int(os.environ.get("IDEMPOTENCY_TTL_SECONDS", "86400"))

# Paths that support idempotency (POST/PUT only)
_IDEMPOTENT_PATHS = {
    "/api/workflows",           # Create workflow
    "/api/workflows/run",       # Run workflow
    "/api/agents/run",          # Run agent
    "/api/agents/run-stream",   # Run agent (streaming)
    "/api/workflows/runs/{run_id}/approve",  # Approve workflow
    "/api/workflows/runs/{run_id}/deny",     # Deny workflow
    "/api/backup/create",       # Create backup
}


# ─── In-memory idempotency store ──────────────────────────────────

class IdempotencyStore:
    """Thread-safe in-memory store for idempotency keys.

    In production, this should be backed by Redis for cluster mode.
    For now, it uses an in-memory dict with TTL-based expiration.
    """

    def __init__(self) -> None:
        # key -> (timestamp, status_code, headers, body)
        self._store: Dict[str, Tuple[float, int, Dict[str, str], str]] = {}
        self._lock = threading.Lock()

    def _cleanup(self, now: float) -> None:
        """Remove expired entries."""
        cutoff = now - IDEMPOTENCY_TTL_SECONDS
        self._store = {
            k: v for k, v in self._store.items()
            if v[0] > cutoff
        }

    def get(self, key: str) -> Optional[Tuple[int, Dict[str, str], str]]:
        """Get a stored response by idempotency key."""
        with self._lock:
            self._cleanup(time.time())
            entry = self._store.get(key)
            if entry is None:
                return None
            return (entry[1], entry[2], entry[3])

    def put(self, key: str, status_code: int, headers: Dict[str, str], body: str) -> None:
        """Store a response for an idempotency key."""
        with self._lock:
            self._store[key] = (time.time(), status_code, headers, body)


_idempotency_store = IdempotencyStore()


def _should_check_idempotency(request: Request) -> bool:
    """Check if this request should use idempotency."""
    if not IDEMPOTENCY_ENABLED:
        return False

    # Only POST and PUT requests
    if request.method not in ("POST", "PUT"):
        return False

    # Check if path matches idempotent paths
    path = request.url.path
    for idempotent_path in _IDEMPOTENT_PATHS:
        # Simple prefix match (handles path parameters)
        if path.startswith(idempotent_path.replace("{run_id}", "").rstrip("/")):
            return True

    return False


async def idempotency_middleware(request: Request, call_next):
    """FastAPI middleware for idempotency key handling.

    If a request includes an X-Idempotency-Key header and the path
    supports idempotency, the middleware will:
    1. Check if the key already exists in the store
    2. If yes, return the cached response without calling the handler
    3. If no, call the handler and store the response

    Args:
        request: The incoming request.
        call_next: The next middleware or route handler.

    Returns:
        The response (cached or fresh).
    """
    idempotency_key = request.headers.get("x-idempotency-key")

    # If no key or path doesn't support idempotency, pass through
    if not idempotency_key or not _should_check_idempotency(request):
        return await call_next(request)

    # Check for existing response
    cached = _idempotency_store.get(idempotency_key)
    if cached is not None:
        status_code, headers, body = cached
        response = JSONResponse(
            status_code=status_code,
            content=body,  # Already parsed JSON
            headers=headers,
        )
        response.headers["X-Idempotency-Key"] = idempotency_key
        response.headers["X-Idempotency-Replay"] = "true"
        return response

    # Execute the request and store the response
    response = await call_next(request)

    # Only cache successful responses (2xx)
    if 200 <= response.status_code < 300:
        # Get response body
        body = b"".join(response.body) if hasattr(response, "body") else b""
        try:
            import json
            parsed_body = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError):
            parsed_body = {}

        # Collect headers (exclude sensitive ones)
        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers.pop("transfer-encoding", None)

        _idempotency_store.put(
            idempotency_key,
            response.status_code,
            headers,
            parsed_body,
        )

    response.headers["X-Idempotency-Key"] = idempotency_key
    response.headers["X-Idempotency-Replay"] = "false"
    return response


def add_idempotency_middleware(app: FastAPI) -> None:
    """Add idempotency middleware to the FastAPI app.

    Args:
        app: The FastAPI application instance.
    """
    app.middleware("http")(idempotency_middleware)
