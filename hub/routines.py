"""Routines engine and scheduler for Grok Bot teammates."""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from hub import memory, queue_manager
from hub.runner import Run

logger = logging.getLogger(__name__)

_scheduler_thread: Optional[threading.Thread] = None
_scheduler_stop_event = threading.Event()
_scheduler_lock = threading.Lock()


def parse_schedule_seconds(schedule_type: str, schedule_value: str) -> int:
    """Parse schedule string (seconds, '5m', '1h', '1d', or cron interval) into seconds."""
    s = str(schedule_value).strip().lower()
    if schedule_type == "cron":
        # Check simple step cron like */5 * * * * (every 5 minutes)
        parts = s.split()
        if len(parts) >= 1 and parts[0].startswith("*/"):
            try:
                mins = int(parts[0][2:])
                return max(1, mins * 60)
            except ValueError:
                pass
        return 3600  # Default 1 hour for cron

    # Interval parser
    if s.endswith("s"):
        try:
            return max(1, int(s[:-1]))
        except ValueError:
            pass
    elif s.endswith("m"):
        try:
            return max(1, int(s[:-1]) * 60)
        except ValueError:
            pass
    elif s.endswith("h"):
        try:
            return max(1, int(s[:-1]) * 3600)
        except ValueError:
            pass
    elif s.endswith("d"):
        try:
            return max(1, int(s[:-1]) * 86400)
        except ValueError:
            pass

    try:
        val = int(s)
        return max(1, val)
    except ValueError:
        return 3600


def run_routine_now(routine_id: str) -> Optional[Dict[str, Any]]:
    """Execute a routine immediately for its bot."""
    routine = memory.get_routine(routine_id)
    if not routine:
        return None

    bot_id = routine["bot_id"]
    task_text = routine["task_text"]
    name = routine["name"]

    # Find or create a session for this bot's routines
    sessions = memory.list_sessions(agent_id=bot_id)
    session_id = None
    for s in sessions:
        if s.get("agent_id") == bot_id and "Routine" in s.get("title", ""):
            session_id = s["id"]
            break
    if not session_id:
        sess = memory.create_session(title=f"{bot_id} (Routines)", agent_id=bot_id)
        session_id = sess["id"]

    now_iso = datetime.now(timezone.utc).isoformat()
    # Add initial notice to thread
    memory.add_message(
        session_id=session_id,
        role="assistant",
        content=f"Routine '{name}' ran: {task_text}",
        bot_id=bot_id,
        msg_type="routine_ran",
        metadata=f'{{"routine_id": "{routine_id}", "routine_name": "{name}", "started_at": "{now_iso}"}}',
    )

    # Dispatch via queue manager
    def _on_routine_complete(res: Run):
        finished_iso = datetime.now(timezone.utc).isoformat()
        memory.update_routine(routine_id, last_run_at=finished_iso)

    run = queue_manager.enqueue_task(
        bot_id=bot_id,
        task=f"[Routine: {name}]\n{task_text}",
        session_id=session_id,
        on_complete=_on_routine_complete,
    )

    memory.update_routine(routine_id, last_run_at=now_iso)
    return {"status": "dispatched", "run_id": run.id, "routine_id": routine_id, "session_id": session_id}


def _scheduler_loop():
    logger.info("Routine scheduler thread started")
    while not _scheduler_stop_event.is_set():
        try:
            now = datetime.now(timezone.utc)
            routines = memory.list_routines(enabled_only=True)
            for r in routines:
                interval_secs = parse_schedule_seconds(r.get("schedule_type", "interval"), r.get("schedule_value", "3600"))
                last_run_str = r.get("last_run_at")
                should_run = False
                if not last_run_str:
                    should_run = True
                else:
                    try:
                        last_run = datetime.fromisoformat(last_run_str)
                        if (now - last_run).total_seconds() >= interval_secs:
                            should_run = True
                    except Exception:
                        should_run = True

                if should_run:
                    logger.info(f"Triggering scheduled routine: {r['name']} for bot: {r['bot_id']}")
                    run_routine_now(r["id"])

        except Exception as e:
            logger.exception(f"Error in routine scheduler: {e}")
        finally:
            # Close the scheduler thread's DB connection to avoid holding locks
            # that conflict with other threads (e.g. tests, API requests)
            memory.close_connection()

        # Sleep in small slices to respond quickly to stop event
        for _ in range(20):
            if _scheduler_stop_event.is_set():
                break
            time.sleep(0.25)


def start_scheduler():
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread is None or not _scheduler_thread.is_alive():
            _scheduler_stop_event.clear()
            _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
            _scheduler_thread.start()


def stop_scheduler():
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread is not None:
            _scheduler_stop_event.set()
            _scheduler_thread.join(timeout=2.0)
            _scheduler_thread = None

