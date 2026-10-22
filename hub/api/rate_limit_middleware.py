"""General rate limiting middleware for the Greenie API.

Provides configurable rate limiting for expensive operations like LLM requests,
workflow creation, and code execution. Uses a sliding window algorithm with
per-IP and per-API-key tracking.

Configuration:
    RATE_LIMIT_ENABLED: Enable/disable rate limiting (default: True)
    RATE_LIMIT_DEFAULT_REQUESTS: Default requests per window (default: 60)
    RATE_LIMIT_DEFAULT_WINDOW: Default window in seconds (default: 60)
"""

import os
import time
import threading
from typing import Dict, List, Optional, Tuple, Set

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


# ─── Configuration ────────────────────────────────────────────────

RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")
RATE_LIMIT_DEFAULT_REQUESTS = int(os.environ.get("RATE_LIMIT_DEFAULT_REQUESTS", "60"))
RATE_LIMIT_DEFAULT_WINDOW = int(os.environ.get("RATE_LIMIT_DEFAULT_WINDOW", "60"))

# Expensive endpoints with stricter limits
_EXPENSIVE_PATHS: Dict[str, Tuple[int, int]] = {
    # (max_requests, window_seconds)
    "/api/agents/run": (10, 60),           # Agent execution
    "/api/agents/run-stream": (10, 60),    # Streaming agent execution
    "/api/llm": (20, 60),                  # LLM model requests
    "/api/llm/chat": (20, 60),             # LLM chat
    "/api/llm/embed": (30, 60),            # Embedding generation
    "/api/workflows": (10, 60),            # Workflow creation
    "/api/workflows/run": (10, 60),        # Workflow execution
    "/api/slinker/execute": (5, 60),       # Code execution
    "/api/crawl": (10, 60),               # Web crawling
    "/api/scrape": (10, 60),              # Web scraping
}

# Paths to exclude from rate limiting
_EXCLUDED_PATHS: Set[str] = {
    "/health",
    "/api/health",
    "/api/metrics",
    "/api/csrf/token",
    "/docs",
    "/redoc",
    "/openapi.json",
}


# ─── Sliding Window Rate Limiter ──────────────────────────────────

class SlidingWindowRateLimiter:
    """Thread-safe sliding window rate limiter."""

    def __init__(self) -> None:
        # key -> list of timestamps
        self._windows: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def _cleanup(self, key: str, now: float, window: int) -> None:
        """Remove expired entries for a key."""
        if key in self._windows:
            self._windows[key] = [
                t for t in self._windows[key] if now - t < window
            ]

    def allow(self, key: str, max_requests: int, window: int) -> Tuple[bool, Dict]:
        """Check if a request is allowed under the rate limit.

        Returns:
            (allowed, info_dict) where info_dict contains retry_after, remaining, limit
        """
        now = time.time()
        with self._lock:
            self._cleanup(key, now, window)
            if key not in self._windows:
                self._windows[key] = []

            current_count = len(self._windows[key])
            remaining = max(0, max_requests - current_count)

            if current_count >= max_requests:
                # Calculate retry-after
                oldest = min(self._windows[key]) if self._windows[key] else now
                retry_after = int(window - (now - oldest)) + 1
                return False, {
                    "limit": max_requests,
                    "window": window,
                    "remaining": 0,
                    "retry_after": max(1, retry_after),
                }

            # Record this request
            self._windows[key].append(now)
            remaining = max(0, max_requests - current_count - 1)
            return True, {
                "limit": max_requests,
                "window": window,
                "remaining": remaining,
                "retry_after": 0,
            }


# Global rate limiter instance
_rate_limiter = SlidingWindowRateLimiter()


def _get_rate_limit_key(request: Request) -> str:
    """Extract rate limit key from request (IP or API key)."""
    # Prefer API key for authenticated requests
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        # Hash the token to avoid storing it in plaintext
        import hashlib
        return f"apikey:{hashlib.sha256(token.encode()).hexdigest()[:16]}"

    # Fall back to IP address
    client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"


def _get_limit_for_path(path: str) -> Tuple[int, int]:
    """Get the rate limit (max_requests, window) for a path."""
    # Check exact match first
    if path in _EXPENSIVE_PATHS:
        return _EXPENSIVE_PATHS[path]

    # Check prefix match for paths with query strings or trailing slashes
    for expensive_path, limit in _EXPENSIVE_PATHS.items():
        if path.startswith(expensive_path):
            return limit

    return (RATE_LIMIT_DEFAULT_REQUESTS, RATE_LIMIT_DEFAULT_WINDOW)


def _should_skip_rate_limit(request: Request) -> bool:
    """Check if rate limiting should be skipped for this request."""
    if not RATE_LIMIT_ENABLED:
        return True

    # Safe methods don't need rate limiting
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return True

    # Check excluded paths
    path = request.url.path
    for excluded in _EXCLUDED_PATHS:
        if path.startswith(excluded):
            return True

    return False


async def rate_limit_middleware(request: Request, call_next):
    """FastAPI middleware for general rate limiting.

    Applies stricter limits to expensive operations (LLM, code execution, etc.)
    and default limits to other endpoints.

    Args:
        request: The incoming request.
        call_next: The next middleware or route handler.

    Returns:
        The response from the next handler with rate limit headers.
    """
    if _should_skip_rate_limit(request):
        response = await call_next(request)
        return response

    path = request.url.path
    key = _get_rate_limit_key(request)
    max_requests, window = _get_limit_for_path(path)

    allowed, info = _rate_limiter.allow(f"{key}:{path}", max_requests, window)

    if not allowed:
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded. Try again later.",
                "retry_after": info["retry_after"],
            },
            headers={
                "X-RateLimit-Limit": str(info["limit"]),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(window),
                "Retry-After": str(info["retry_after"]),
            },
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(info["limit"])
    response.headers["X-RateLimit-Remaining"] = str(info["remaining"])
    response.headers["X-RateLimit-Reset"] = str(window)
    return response


def add_rate_limit_middleware(app: FastAPI) -> None:
    """Add rate limiting middleware to the FastAPI app.

    Args:
        app: The FastAPI application instance.
    """
    app.middleware("http")(rate_limit_middleware)
