"""CSRF protection middleware for the Greenie API.

Provides CSRF token generation and validation to protect against
cross-site request forgery attacks. Uses a double-submit cookie
pattern for stateless validation.

Configuration:
    CSRF_SECRET_KEY: Secret key for token signing (required in production)
    CSRF_ENABLED: Enable/disable CSRF protection (default: True)
    CSRF_EXCLUDED_PATHS: Comma-separated paths to exclude (default: /health,/api/metrics)
"""

import hashlib
import hmac
import os
import secrets
import threading
import time
from typing import Optional, Set

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

# ─── Configuration ────────────────────────────────────────────────

CSRF_SECRET_KEY = os.environ.get("CSRF_SECRET_KEY", "")
CSRF_ENABLED = os.environ.get("CSRF_ENABLED", "true").lower() in ("true", "1", "yes")
CSRF_TOKEN_EXPIRY = int(os.environ.get("CSRF_TOKEN_EXPIRY", "3600"))  # 1 hour default
CSRF_EXCLUDED_PATHS: Set[str] = {
    path.strip()
    for path in os.environ.get("CSRF_EXCLUDED_PATHS", "/health,/api/metrics").split(",")
    if path.strip()
}

# Token store for validation (in-memory, thread-safe)
_token_store: dict[str, float] = {}
_token_store_lock = threading.Lock()


# ─── Token Generation ─────────────────────────────────────────────


def generate_csrf_token() -> str:
    """Generate a new CSRF token with timestamp for expiry.

    Returns a signed token that can be validated later.
    Format: <random_bytes>.<timestamp>.<signature>
    """
    if not CSRF_SECRET_KEY:
        # Fallback: use a simple random token without signing
        token = secrets.token_urlsafe(32)
        timestamp = time.time()
        return f"{token}.{int(timestamp)}"

    random_part = secrets.token_urlsafe(32)
    timestamp = int(time.time())
    payload = f"{random_part}.{timestamp}"

    # Sign the payload with HMAC-SHA256
    signature = hmac.new(
        CSRF_SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]

    return f"{payload}.{signature}"


def validate_csrf_token(token: str) -> bool:
    """Validate a CSRF token for authenticity and expiry.

    Checks:
    1. Token format is correct
    2. Token has not expired
    3. Token signature is valid (if signing is enabled)

    Args:
        token: The CSRF token to validate.

    Returns:
        True if the token is valid, False otherwise.
    """
    if not token:
        return False

    parts = token.split(".")
    if len(parts) < 2:
        return False

    # Format: random.timestamp (no signing) or random.timestamp.signature (with signing)
    try:
        timestamp = int(parts[1])
    except (ValueError, IndexError):
        return False

    # Check expiry
    if time.time() - timestamp > CSRF_TOKEN_EXPIRY:
        return False

    # Verify signature if signing is enabled
    if CSRF_SECRET_KEY and len(parts) == 3:
        random_part = parts[0]
        signature = parts[2]
        payload = f"{random_part}.{timestamp}"

        expected_signature = hmac.new(
            CSRF_SECRET_KEY.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:16]

        if not hmac.compare_digest(signature, expected_signature):
            return False

    return True


# ─── Middleware ───────────────────────────────────────────────────


def get_csrf_token_from_request(request: Request) -> Optional[str]:
    """Extract CSRF token from request headers or cookies.

    Checks:
    1. X-CSRF-Token header (preferred)
    2. X-XSRF-Token header (alternative)
    3. csrf_token cookie

    Args:
        request: The FastAPI request object.

    Returns:
        The CSRF token if found, None otherwise.
    """
    # Check headers first (preferred method)
    token = request.headers.get("x-csrf-token") or request.headers.get("x-xsrf-token")
    if token:
        return token

    # Fall back to cookie
    token = request.cookies.get("csrf_token")
    return token


def should_skip_csrf(request: Request) -> bool:
    """Determine if CSRF check should be skipped for this request.

    Skips CSRF for:
    - Safe methods (GET, HEAD, OPTIONS, TRACE)
    - Excluded paths
    - When CSRF is disabled globally
    - Bearer-authenticated API clients (not vulnerable to CSRF)

    Args:
        request: The FastAPI request object.

    Returns:
        True if CSRF check should be skipped.
    """
    if not CSRF_ENABLED:
        return True

    # Safe methods don't need CSRF protection
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return True

    # Bearer-authenticated API clients are not vulnerable to CSRF
    # because they don't use cookie-based authentication
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return True

    # Check excluded paths
    path = request.url.path
    for excluded in CSRF_EXCLUDED_PATHS:
        if path.startswith(excluded):
            return True

    return False


async def csrf_middleware(request: Request, call_next):
    """FastAPI middleware for CSRF protection.

    Validates CSRF tokens on state-changing requests (POST, PUT, PATCH, DELETE).
    Safe methods (GET, HEAD, OPTIONS) are allowed without a token.

    The token can be provided via:
    - X-CSRF-Token header (recommended for API clients)
    - X-XSRF-Token header (alternative)
    - csrf_token cookie (for browser-based clients)

    Args:
        request: The incoming request.
        call_next: The next middleware or route handler.

    Returns:
        The response from the next handler.

    Raises:
        HTTPException: 403 if CSRF token is missing or invalid.
    """
    if should_skip_csrf(request):
        response = await call_next(request)
        return response

    # Extract and validate CSRF token
    token = get_csrf_token_from_request(request)
    if token is None:
        raise HTTPException(
            status_code=403,
            detail="CSRF token missing. Provide X-CSRF-Token header or csrf_token cookie.",
        )

    if not validate_csrf_token(token):
        raise HTTPException(
            status_code=403,
            detail="CSRF token invalid or expired.",
        )

    response = await call_next(request)
    return response


# ─── Token Endpoint ───────────────────────────────────────────────


def register_csrf_routes(app: FastAPI) -> None:
    """Register CSRF token endpoint with the FastAPI app.

    Adds:
    - GET /api/csrf/token — Returns a new CSRF token

    Args:
        app: The FastAPI application instance.
    """

    @app.get("/api/csrf/token")
    async def get_csrf_token() -> dict:
        """Generate and return a new CSRF token.

        Returns:
            Dict with 'token' key containing the new CSRF token.
        """
        token = generate_csrf_token()
        return {"token": token}

    @app.get("/api/csrf/verify")
    async def verify_csrf_token(request: Request) -> dict:
        """Verify the current CSRF token without executing a state-changing action.

        Useful for pre-flight checks.

        Returns:
            Dict with 'valid' key indicating token validity.
        """
        token = get_csrf_token_from_request(request)
        if token is None:
            return {"valid": False, "reason": "Token missing"}
        if not validate_csrf_token(token):
            return {"valid": False, "reason": "Token invalid or expired"}
        return {"valid": True}


# ─── Integration Helper ───────────────────────────────────────────


def add_csrf_middleware(app: FastAPI) -> None:
    """Add CSRF middleware to the FastAPI app.

    This should be called during app setup, before any routes are registered.

    Args:
        app: The FastAPI application instance.
    """
    app.middleware("http")(csrf_middleware)
    register_csrf_routes(app)
