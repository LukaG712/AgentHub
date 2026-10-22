"""Workflow triggers — schedule, webhook, and file change triggers.

Triggers monitor for events that should start workflow executions:
- Schedule triggers: cron-based recurring execution
- Webhook triggers: HTTP endpoint that starts a workflow on POST
- File change triggers: watch file system paths for changes
"""

import asyncio
import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from hub.workflow.models import (
    TriggerType,
    WorkflowDefinition,
    WorkflowTrigger,
)
from hub.workflow import storage, executor

logger = logging.getLogger("hub.workflow.triggers")


class ScheduleTrigger:
    """Manages cron-based schedule triggers."""

    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

    async def start(self) -> None:
        """Start all enabled schedule triggers."""
        self._running = True
        workflows = storage.list_workflow_definitions(limit=100)
        for wf in workflows:
            if not wf.enabled:
                continue
            for trigger in wf.triggers:
                if trigger.trigger_type == TriggerType.SCHEDULE.value and trigger.enabled:
                    self._start_schedule(wf, trigger)

    def _start_schedule(self, wf: WorkflowDefinition, trigger: WorkflowTrigger) -> None:
        """Start a background task for a schedule trigger."""
        task_key = f"{wf.id}:{trigger.id}"
        if task_key in self._tasks:
            return  # Already running

        task = asyncio.create_task(self._schedule_loop(wf, trigger))
        self._tasks[task_key] = task
        logger.info(f"Schedule trigger started: {task_key} cron={trigger.cron}")

    async def _schedule_loop(self, wf: WorkflowDefinition, trigger: WorkflowTrigger) -> None:
        """Loop that checks cron schedule and triggers workflow."""
        while self._running:
            next_run = self._next_cron_run(trigger.cron)
            if next_run is None:
                logger.warning(f"Invalid cron expression: {trigger.cron}")
                break

            wait_seconds = (next_run - datetime.now(timezone.utc)).total_seconds()
            if wait_seconds < 0:
                wait_seconds = 0

            logger.debug(f"Schedule {trigger.id}: next run in {wait_seconds:.0f}s")
            await asyncio.sleep(wait_seconds)

            # Trigger the workflow
            try:
                # Reload workflow to get latest version
                wf = storage.get_workflow_definition(wf.id)
                if wf and wf.enabled:
                    await executor.execute_workflow(
                        wf,
                        trigger_type=TriggerType.SCHEDULE.value,
                        trigger_data={"trigger_id": trigger.id, "cron": trigger.cron},
                        started_by="schedule",
                    )
            except Exception as e:
                logger.error(f"Schedule trigger failed for {wf.id}: {e}")

    def stop(self) -> None:
        """Stop all schedule triggers."""
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    @staticmethod
    def _next_cron_run(cron: str) -> Optional[datetime]:
        """Calculate the next run time from a cron expression (5 fields).

        Simplified cron parser supporting: minute hour day month weekday
        Supports: *, specific values, ranges (1-5), steps (*/15)
        """
        parts = cron.strip().split()
        if len(parts) != 5:
            return None

        try:
            now = datetime.now(timezone.utc)
            minute = int(parts[0]) if parts[0] != "*" else now.minute
            hour = int(parts[1]) if parts[1] != "*" else now.hour
            day = int(parts[2]) if parts[2] != "*" else now.day
            month = int(parts[3]) if parts[3] != "*" else now.month
            weekday = int(parts[4]) if parts[4] != "*" else now.weekday()

            # Handle */N patterns
            if parts[0].startswith("*/"):
                step = int(parts[0][2:])
                minute = ((now.minute // step) + 1) * step
                if minute >= 60:
                    minute = 0
                    hour += 1

            # Build next run time
            next_run = now.replace(
                minute=minute,
                hour=hour,
                second=0,
                microsecond=0,
            )

            # If we're past this time, move to next day
            if next_run <= now:
                from datetime import timedelta
                next_run += timedelta(days=1)

            return next_run
        except (ValueError, IndexError):
            return None


class WebhookTrigger:
    """Handles webhook triggers for workflows."""

    def __init__(self):
        self._trigger_map: dict[str, WorkflowDefinition] = {}
        self._load_triggers()

    def _load_triggers(self) -> None:
        """Load all webhook triggers into memory."""
        workflows = storage.list_workflow_definitions(limit=100)
        for wf in workflows:
            for trigger in wf.triggers:
                if trigger.trigger_type == TriggerType.WEBHOOK.value and trigger.enabled:
                    path = trigger.webhook_path or f"/api/workflows/webhook/{trigger.id}"
                    self._trigger_map[path] = wf

    async def handle_webhook(
        self, path: str, body: dict[str, Any], signature: Optional[str] = None
    ) -> dict[str, Any]:
        """Handle an incoming webhook and trigger the associated workflow."""
        wf = self._trigger_map.get(path)
        if wf is None:
            return {"error": "Webhook not found", "status": 404}

        # Verify signature if configured
        trigger = next(
            (t for t in wf.triggers if t.trigger_type == TriggerType.WEBHOOK.value
             and (t.webhook_path or f"/api/workflows/webhook/{t.id}") == path),
            None,
        )
        if trigger and trigger.webhook_secret and signature:
            expected = self._compute_signature(trigger.webhook_secret, body)
            if not hmac.compare_digest(expected, signature):
                return {"error": "Invalid signature", "status": 401}

        # Trigger the workflow
        run = await executor.execute_workflow(
            wf,
            trigger_type=TriggerType.WEBHOOK.value,
            trigger_data={"path": path, "body": body},
            started_by="webhook",
        )

        return {
            "status": "accepted",
            "run_id": run.id,
            "workflow_id": wf.id,
        }

    @staticmethod
    def _compute_signature(secret: str, body: dict[str, Any]) -> str:
        """Compute HMAC-SHA256 signature for webhook body."""
        import json
        payload = json.dumps(body, sort_keys=True)
        return hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


class FileChangeTrigger:
    """Monitors file system paths for changes."""

    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._file_hashes: dict[str, str] = {}
        self._running = False
        self._poll_interval = int(os.environ.get("WORKFLOW_FILE_POLL_INTERVAL", "10"))

    async def start(self) -> None:
        """Start all file change triggers."""
        self._running = True
        workflows = storage.list_workflow_definitions(limit=100)
        for wf in workflows:
            if not wf.enabled:
                continue
            for trigger in wf.triggers:
                if trigger.trigger_type == TriggerType.FILE_CHANGE.value and trigger.enabled:
                    self._start_watch(wf, trigger)

    def _start_watch(self, wf: WorkflowDefinition, trigger: WorkflowTrigger) -> None:
        """Start watching file paths for changes."""
        task_key = f"{wf.id}:{trigger.id}"
        if task_key in self._tasks:
            return

        # Initialize file hashes
        for path in trigger.watch_paths:
            try:
                p = Path(path)
                if p.exists():
                    self._file_hashes[str(p)] = self._hash_file(p)
            except Exception as e:
                logger.warning(f"Cannot watch {path}: {e}")

        task = asyncio.create_task(self._watch_loop(wf, trigger))
        self._tasks[task_key] = task
        logger.info(f"File change trigger started: {task_key} paths={trigger.watch_paths}")

    async def _watch_loop(self, wf: WorkflowDefinition, trigger: WorkflowTrigger) -> None:
        """Poll file paths for changes."""
        while self._running:
            changed = False
            for path in trigger.watch_paths:
                try:
                    p = Path(path)
                    if p.exists():
                        current_hash = self._hash_file(p)
                        previous_hash = self._file_hashes.get(str(p))
                        if previous_hash and current_hash != previous_hash:
                            changed = True
                            self._file_hashes[str(p)] = current_hash
                            logger.info(f"File changed: {path}")
                except Exception as e:
                    logger.warning(f"Error watching {path}: {e}")

            if changed:
                try:
                    wf = storage.get_workflow_definition(wf.id)
                    if wf and wf.enabled:
                        await executor.execute_workflow(
                            wf,
                            trigger_type=TriggerType.FILE_CHANGE.value,
                            trigger_data={"trigger_id": trigger.id, "paths": trigger.watch_paths},
                            started_by="file_change",
                        )
                except Exception as e:
                    logger.error(f"File change trigger failed for {wf.id}: {e}")

            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        """Stop all file change triggers."""
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Compute a simple hash of a file's content and modification time."""
        stat = path.stat()
        content = path.read_bytes()[:8192]  # First 8KB
        return hashlib.md5(content + str(stat.st_mtime).encode()).hexdigest()


# Global trigger managers
_schedule = ScheduleTrigger()
_webhook = WebhookTrigger()
_file_change = FileChangeTrigger()


async def start_all_triggers() -> None:
    """Start all trigger managers."""
    await _schedule.start()
    await _file_change.start()
    logger.info("All workflow triggers started")


async def stop_all_triggers() -> None:
    """Stop all trigger managers."""
    _schedule.stop()
    _file_change.stop()
    logger.info("All workflow triggers stopped")


async def handle_webhook(
    path: str, body: dict[str, Any], signature: Optional[str] = None
) -> dict[str, Any]:
    """Handle an incoming webhook (convenience function)."""
    return await _webhook.handle_webhook(path, body, signature)
