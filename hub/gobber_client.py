"""Gobber HTTP client for Greenie.

Provides an async client for communicating with the Gobber storage service.
All calls include graceful fallback when Gobber is unavailable, so Greenie
continues to operate with local in-memory stores as a backup.
"""

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger("hub.gobber_client")


class GobberClient:
    """Async HTTP client for the Gobber storage service."""

    def __init__(self):
        self.base_url = os.getenv("GOBBER_URL", os.getenv("EVERSHADE_GOBBER_URL", "http://gobber:8085"))
        self.api_key = os.getenv("EVERSHADE_GOBBER_API_KEY", os.getenv("GOBBER_API_KEY", ""))
        self._available = None  # Cached availability status

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def check_available(self) -> bool:
        """Check if Gobber is reachable."""
        if self._available is not None:
            return self._available
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{self.base_url}/health")
                self._available = resp.status_code == 200
        except Exception:
            self._available = False
        return self._available

    def invalidate_cache(self) -> None:
        """Invalidate the availability cache (e.g., after a failure)."""
        self._available = None

    async def _request(self, method: str, path: str, **kwargs: Any) -> Optional[Any]:
        """Make a request to Gobber with error handling."""
        if not await self.check_available():
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=self.headers,
                    **kwargs,
                )
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 404:
                    return None
                else:
                    logger.warning(f"Gobber {method} {path} returned {resp.status_code}")
                    return None
        except Exception as e:
            logger.warning(f"Gobber request failed: {e}")
            self.invalidate_cache()
            return None

    # ─── Cache ──────────────────────────────────────────────────

    async def set_cache(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> bool:
        """Set a cache entry in Gobber."""
        data = {"key": key, "value": value}
        if ttl_seconds:
            data["ttl_seconds"] = ttl_seconds
        result = await self._request("POST", "/api/cache", json=data)
        return result is not None

    async def get_cache(self, key: str) -> Optional[Any]:
        """Get a cache entry from Gobber."""
        result = await self._request("GET", f"/api/cache/{key}")
        if result:
            return result.get("value")
        return None

    async def delete_cache(self, key: str) -> bool:
        """Delete a cache entry from Gobber."""
        result = await self._request("DELETE", f"/api/cache/{key}")
        return result is not None

    # ─── Feature Flags ──────────────────────────────────────────

    async def get_flag(self, name: str) -> Optional[dict[str, Any]]:
        """Get a feature flag from Gobber."""
        return await self._request("GET", f"/api/flags/{name}")

    async def list_flags(self) -> list[dict[str, Any]]:
        """List all feature flags from Gobber."""
        result = await self._request("GET", "/api/flags")
        return result if isinstance(result, list) else []

    async def set_flag(self, name: str, is_enabled: bool, description: str = "", targeting: Optional[dict] = None) -> bool:
        """Set or update a feature flag in Gobber."""
        data = {"name": name, "is_enabled": is_enabled, "description": description}
        if targeting:
            data["targeting"] = targeting
        # Try update first, then create
        result = await self._request("PATCH", f"/api/flags/{name}", json=data)
        if result is None:
            result = await self._request("POST", "/api/flags", json=data)
        return result is not None

    async def delete_flag(self, name: str) -> bool:
        """Delete a feature flag from Gobber."""
        result = await self._request("DELETE", f"/api/flags/{name}")
        return result is not None

    # ─── Webhooks ───────────────────────────────────────────────

    async def create_webhook(self, name: str, url: str, events: list[str], secret: Optional[str] = None) -> Optional[str]:
        """Create a webhook in Gobber."""
        data = {"name": name, "url": url, "events": events}
        if secret:
            data["secret"] = secret
        result = await self._request("POST", "/api/webhooks", json=data)
        if result:
            return result.get("id")
        return None

    async def list_webhooks(self, active_only: bool = False) -> list[dict[str, Any]]:
        """List webhooks from Gobber."""
        params = {"active_only": "true"} if active_only else {}
        result = await self._request("GET", "/api/webhooks", params=params)
        return result if isinstance(result, list) else []

    async def delete_webhook(self, webhook_id: str) -> bool:
        """Delete a webhook from Gobber."""
        result = await self._request("DELETE", f"/api/webhooks/{webhook_id}")
        return result is not None

    async def create_delivery(self, webhook_id: str, event: str, payload: dict[str, Any]) -> bool:
        """Record a webhook delivery in Gobber."""
        data = {"event": event, "payload": payload}
        result = await self._request("POST", f"/api/webhooks/{webhook_id}/deliveries", json=data)
        return result is not None

    # ─── Analytics ──────────────────────────────────────────────

    async def record_event(self, event_type: str, properties: Optional[dict] = None, service: Optional[str] = None) -> bool:
        """Record an analytics event in Gobber."""
        data = {"event_type": event_type}
        if properties:
            data["properties"] = properties
        if service:
            data["service"] = service
        result = await self._request("POST", "/api/analytics/events", json=data)
        return result is not None

    async def query_events(self, event_type: Optional[str] = None, service: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        """Query analytics events from Gobber."""
        params = {}
        if event_type:
            params["event_type"] = event_type
        if service:
            params["service"] = service
        params["limit"] = str(limit)
        result = await self._request("GET", "/api/analytics/events", params=params)
        return result if isinstance(result, list) else []

    # ─── RBAC ───────────────────────────────────────────────────

    async def create_role(self, name: str, permissions: list[str], description: str = "") -> Optional[str]:
        """Create an RBAC role in Gobber."""
        data = {"name": name, "permissions": permissions, "description": description}
        result = await self._request("POST", "/api/roles", json=data)
        if result:
            return result.get("id")
        return None

    async def list_roles(self) -> list[dict[str, Any]]:
        """List RBAC roles from Gobber."""
        result = await self._request("GET", "/api/roles")
        return result if isinstance(result, list) else []

    async def get_role(self, role_id: str) -> Optional[dict[str, Any]]:
        """Get an RBAC role from Gobber."""
        return await self._request("GET", f"/api/roles/{role_id}")

    async def delete_role(self, role_id: str) -> bool:
        """Delete an RBAC role from Gobber."""
        result = await self._request("DELETE", f"/api/roles/{role_id}")
        return result is not None

    async def assign_role(self, user_id: str, role_id: str) -> bool:
        """Assign a role to a user in Gobber."""
        data = {"role_id": role_id}
        result = await self._request("POST", f"/api/users/{user_id}/roles", json=data)
        return result is not None

    async def get_user_roles(self, user_id: str) -> list[dict[str, Any]]:
        """Get roles for a user from Gobber."""
        result = await self._request("GET", f"/api/users/{user_id}/roles")
        return result if isinstance(result, list) else []

    async def revoke_role(self, user_id: str, role_id: str) -> bool:
        """Revoke a role from a user in Gobber."""
        result = await self._request("DELETE", f"/api/users/{user_id}/roles/{role_id}")
        return result is not None


# Singleton instance
gobber_client = GobberClient()
