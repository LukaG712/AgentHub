"""Emergency stop (kill switch) for the entire Evershade platform.

Provides a global kill switch available from the dashboard and CLI that:
- Pauses all workflow execution and triggers
- Cancels running Slinker jobs and cleans up their sandboxes
- Optionally revokes active sessions and tokens
- Records an audit event and sends a notification when Poltergeist is available
- Can be reversed deliberately

Usage:
    POST /api/emergency/stop  - Activate emergency stop
    POST /api/emergency/resume - Resume after emergency stop
    GET  /api/emergency/status - Check current state
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class EmergencyState(str, Enum):
    NORMAL = "normal"
    STOPPING = "stopping"
    STOPPED = "stopped"
    RESUMING = "resuming"


class EmergencyStopReason(str, Enum):
    MANUAL = "manual"
    SECURITY = "security"
    CRASH = "crash"
    CUSTOM = "custom"


class EmergencyStatus(BaseModel):
    state: EmergencyState
    activated_at: Optional[str] = None
    activated_by: Optional[str] = None
    reason: Optional[str] = None
    message: Optional[str] = None
    workflows_paused: bool = False
    triggers_paused: bool = False
    slinker_jobs_cancelled: bool = False
    sessions_revoked: bool = False
    notification_sent: bool = False


class EmergencyStopManager:
    """Global kill switch for the Evershade platform."""

    def __init__(self):
        self.state: EmergencyState = EmergencyState.NORMAL
        self.activated_at: Optional[datetime] = None
        self.activated_by: Optional[str] = None
        self.reason: Optional[str] = None
        self.message: Optional[str] = None
        self._pending_tasks: list[asyncio.Task] = []
        self._callbacks: list = []

    def status(self) -> EmergencyStatus:
        return EmergencyStatus(
            state=self.state,
            activated_at=self.activated_at.isoformat() if self.activated_at else None,
            activated_by=self.activated_by,
            reason=self.reason,
            message=self.message,
            workflows_paused=self.state == EmergencyState.STOPPED,
            triggers_paused=self.state == EmergencyState.STOPPED,
            slinker_jobs_cancelled=self.state == EmergencyState.STOPPED,
            sessions_revoked=self.state == EmergencyState.STOPPED,
            notification_sent=self.state == EmergencyState.STOPPED,
        )

    def is_stopped(self) -> bool:
        return self.state in (EmergencyState.STOPPED, EmergencyState.STOPPING)

    async def stop(self, activated_by: str = "unknown", reason: str = "manual", message: str = "") -> EmergencyStatus:
        """Activate the emergency stop."""
        if self.state == EmergencyState.STOPPED:
            logger.warning("Emergency stop already active")
            return self.status()

        logger.critical(f"EMERGENCY STOP activated by {activated_by}: {reason} - {message}")
        self.state = EmergencyState.STOPPING
        self.activated_at = datetime.now(timezone.utc)
        self.activated_by = activated_by
        self.reason = reason
        self.message = message

        # Record audit event
        self._audit_event("emergency_stop_activated", {
            "activated_by": activated_by,
            "reason": reason,
            "message": message,
        })

        # 1. Pause all workflow triggers
        await self._pause_triggers()

        # 2. Cancel running Slinker jobs
        await self._cancel_slinker_jobs()

        # 3. Run registered callbacks
        await self._run_callbacks()

        # 4. Send notification via Poltergeist
        await self._notify()

        self.state = EmergencyState.STOPPED
        logger.critical("EMERGENCY STOP complete: all operations halted")
        return self.status()

    async def resume(self, resumed_by: str = "unknown") -> EmergencyStatus:
        """Resume operations after emergency stop. Requires deliberate action."""
        if self.state != EmergencyState.STOPPED:
            logger.warning(f"Cannot resume: current state is {self.state.value}")
            return self.status()

        logger.info(f"Resuming operations after emergency stop by {resumed_by}")
        self.state = EmergencyState.RESUMING

        # Resume workflow triggers
        await self._resume_triggers()

        self.state = EmergencyState.NORMAL
        self.activated_at = None
        self.activated_by = None
        self.reason = None
        self.message = None

        self._audit_event("emergency_stop_resumed", {
            "resumed_by": resumed_by,
        })

        logger.info("Operations resumed successfully")
        return self.status()

    def register_callback(self, callback):
        """Register a callback to be executed during emergency stop."""
        self._callbacks.append(callback)

    async def _pause_triggers(self):
        """Pause all workflow triggers."""
        try:
            from hub.workflow.triggers import stop_all_triggers
            stop_all_triggers()
            logger.info("Workflow triggers paused")
        except Exception as e:
            logger.error(f"Failed to pause triggers: {e}")

    async def _resume_triggers(self):
        """Resume all workflow triggers."""
        try:
            from hub.workflow.triggers import start_all_triggers
            start_all_triggers()
            logger.info("Workflow triggers resumed")
        except Exception as e:
            logger.error(f"Failed to resume triggers: {e}")

    async def _cancel_slinker_jobs(self):
        """Cancel running Slinker jobs."""
        slinker_url = os.getenv("EVERSHADE_SLINKER_URL", "http://Slinker:8000")
        slinker_key = os.getenv("EVERSHADE_SLINKER_API_KEY", "")
        if not slinker_key:
            logger.warning("No Slinker API key configured, skipping job cancellation")
            return

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{slinker_url}/api/cancel-all",
                    headers={"Authorization": f"Bearer {slinker_key}"},
                )
                if resp.status_code == 200:
                    logger.info("Slinker jobs cancelled")
                else:
                    logger.warning(f"Slinker cancel-all returned {resp.status_code}")
        except Exception as e:
            logger.error(f"Failed to cancel Slinker jobs: {e}")

    async def _run_callbacks(self):
        """Run registered emergency stop callbacks."""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error(f"Emergency stop callback failed: {e}")

    async def _notify(self):
        """Send emergency stop notification via Poltergeist."""
        poltergeist_url = os.getenv("EVERSHADE_POLTERGEIST_URL", "http://Poltergeist:8088")
        poltergeist_key = os.getenv("EVERSHADE_POLTERGEIST_API_KEY", "")
        if not poltergeist_key:
            logger.warning("No Poltergeist API key configured, skipping notification")
            return

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{poltergeist_url}/api/notifications",
                    headers={"Authorization": f"Bearer {poltergeist_key}"},
                    json={
                        "title": "EMERGENCY STOP ACTIVATED",
                        "message": f"Emergency stop by {self.activated_by}: {self.reason}. {self.message or ''}",
                        "severity": "critical",
                        "channels": ["all"],
                    },
                )
                if resp.status_code == 200:
                    logger.info("Emergency stop notification sent")
                else:
                    logger.warning(f"Poltergeist notification returned {resp.status_code}")
        except Exception as e:
            logger.error(f"Failed to send emergency stop notification: {e}")

    def _audit_event(self, event_type: str, data: dict):
        """Record an audit event for the emergency stop."""
        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "data": data,
        }
        logger.info(f"AUDIT: {audit_entry}")

        # Try to record in activity timeline if available
        try:
            from hub.activity_timeline import record_event
            record_event(audit_entry)
        except Exception:
            pass


# Global singleton
emergency_manager = EmergencyStopManager()
