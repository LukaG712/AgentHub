"""Queue manager for parallel bot execution, per-bot sequential queueing, and pause/resume."""

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from hub.runner import Run, _load_run, _save_run, list_runs, run_agent

logger = logging.getLogger(__name__)

# Global state
_lock = threading.Lock()
_paused_bots: set = set()
_resume_events: Dict[str, threading.Event] = {}
_bot_queues: Dict[str, List["QueueItem"]] = {}
_active_workers: Dict[str, threading.Thread] = {}
_current_active_runs: Dict[str, Optional[Run]] = {}

# H1: Persist queue state to survive restarts
_QUEUE_STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "queue_state.json"


def _save_queue_state() -> None:
    """Persist queue state to disk (H1 fix)."""
    try:
        state = {
            "paused_bots": list(_paused_bots),
            "queues": {},
        }
        for bot_id, items in _bot_queues.items():
            state["queues"][bot_id] = [item.to_dict() for item in items]
        tmp = _QUEUE_STATE_FILE.with_suffix(".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(str(tmp), str(_QUEUE_STATE_FILE))
    except Exception:
        logger.exception("Failed to save queue state")


def _load_queue_state() -> None:
    """Restore queue state from disk on startup (H1 fix)."""
    if not _QUEUE_STATE_FILE.exists():
        return
    try:
        with open(_QUEUE_STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
        with _lock:
            _paused_bots.clear()
            _paused_bots.update(state.get("paused_bots", []))
            _bot_queues.clear()
            for bot_id, items in state.get("queues", {}).items():
                _bot_queues[bot_id] = []
                for item_data in items:
                    item = QueueItem(
                        run_id=item_data["run_id"],
                        bot_id=item_data["bot_id"],
                        task=item_data["task"],
                        session_id=item_data.get("session_id"),
                        created_at=item_data.get("created_at", ""),
                    )
                    _bot_queues[bot_id].append(item)
            # Re-ensure workers for non-empty queues
            for bot_id in list(_bot_queues.keys()):
                if _bot_queues[bot_id] and bot_id not in _paused_bots:
                    _ensure_worker_locked(bot_id)
            logger.info(f"Restored queue state: {len(_paused_bots)} paused bots, "
                       f"{sum(len(v) for v in _bot_queues.values())} queued tasks")
    except Exception:
        logger.exception("Failed to load queue state")


def recover_queue() -> None:
    """Recover queue state from disk. Call on server startup."""
    _load_queue_state()


@dataclass
class QueueItem:
    run_id: str
    bot_id: str
    task: str
    session_id: Optional[str] = None
    output_callback: Optional[Callable[[str, str], None]] = None
    on_start: Optional[Callable[[str], None]] = None
    on_complete: Optional[Callable[[Run], None]] = None
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "bot_id": self.bot_id,
            "task": self.task,
            "session_id": self.session_id,
            "created_at": self.created_at,
        }


def is_bot_paused(bot_id: str) -> bool:
    with _lock:
        return bot_id in _paused_bots


def pause_bot(bot_id: str) -> bool:
    with _lock:
        _paused_bots.add(bot_id)
        if bot_id in _resume_events:
            _resume_events[bot_id].clear()
    _save_queue_state()
    return True


def resume_bot(bot_id: str) -> bool:
    with _lock:
        _paused_bots.discard(bot_id)
        if bot_id not in _resume_events:
            _resume_events[bot_id] = threading.Event()
        _resume_events[bot_id].set()
        # Ensure worker is running if there are queued tasks
        _ensure_worker_locked(bot_id)
    _save_queue_state()
    return True


def get_bot_queue(bot_id: str) -> List[Dict[str, Any]]:
    with _lock:
        items = _bot_queues.get(bot_id, [])
        return [item.to_dict() for item in items]


def get_all_queued_runs() -> List[Run]:
    with _lock:
        runs = []
        for bot_id, items in _bot_queues.items():
            for item in items:
                r = _load_run(item.run_id)
                if r:
                    runs.append(r)
        return runs


def get_active_run_for_bot(bot_id: str) -> Optional[Run]:
    with _lock:
        return _current_active_runs.get(bot_id)


def enqueue_task(
    bot_id: str,
    task: str,
    session_id: Optional[str] = None,
    output_callback: Optional[Callable[[str, str], None]] = None,
    on_start: Optional[Callable[[str], None]] = None,
    on_complete: Optional[Callable[[Run], None]] = None,
    run_id: Optional[str] = None,
) -> Run:
    """Enqueue a task for a bot. Each bot runs one task at a time; separate bots run in parallel."""
    if run_id is None:
        run_id = str(uuid.uuid4())

    now = datetime.now(timezone.utc).isoformat()
    run = Run(
        id=run_id,
        agent=bot_id,
        task=task,
        state="queued",
        owner_pid=os.getpid(),
        session_id=session_id,
    )
    _save_run(run)

    item = QueueItem(
        run_id=run_id,
        bot_id=bot_id,
        task=task,
        session_id=session_id,
        output_callback=output_callback,
        on_start=on_start,
        on_complete=on_complete,
        created_at=now,
    )

    with _lock:
        if bot_id not in _bot_queues:
            _bot_queues[bot_id] = []
        _bot_queues[bot_id].append(item)
        _ensure_worker_locked(bot_id)
    _save_queue_state()

    return run


def _ensure_worker_locked(bot_id: str) -> None:
    worker = _active_workers.get(bot_id)
    if worker is None or not worker.is_alive():
        t = threading.Thread(target=_bot_worker_loop, args=(bot_id,), daemon=True)
        _active_workers[bot_id] = t
        t.start()


def _bot_worker_loop(bot_id: str) -> None:
    while True:
        # Check if paused before popping next item
        while is_bot_paused(bot_id):
            ev = None
            with _lock:
                if bot_id not in _resume_events:
                    _resume_events[bot_id] = threading.Event()
                ev = _resume_events[bot_id]
            ev.wait(timeout=1.0)

        # Pop next item
        item = None
        with _lock:
            queue = _bot_queues.get(bot_id, [])
            if not queue:
                _active_workers.pop(bot_id, None)
                _current_active_runs[bot_id] = None
                return
            item = queue.pop(0)
        _save_queue_state()

        if item is None:
            return

        # Check if the run was stopped or cancelled while queued
        current_run = _load_run(item.run_id)
        if current_run and current_run.state == "stopped":
            continue

        with _lock:
            _current_active_runs[bot_id] = current_run

        if item.on_start:
            try:
                item.on_start(item.run_id)
            except Exception as e:
                logger.exception(f"Error in on_start callback: {e}")

        try:
            result = run_agent(
                agent_name=item.bot_id,
                task=item.task,
                no_wait=False,
                session_id=item.session_id,
                output_callback=item.output_callback,
                run_id=item.run_id,
            )
            with _lock:
                _current_active_runs[bot_id] = None
            if item.on_complete:
                try:
                    item.on_complete(result)
                except Exception as e:
                    logger.exception(f"Error in on_complete callback: {e}")
        except Exception as e:
            logger.exception(f"Error executing task for bot {bot_id}: {e}")
            with _lock:
                _current_active_runs[bot_id] = None


def clear_all_queues() -> None:
    """Clear all queues (used for test teardown)."""
    with _lock:
        _paused_bots.clear()
        _bot_queues.clear()
        _active_workers.clear()
        _current_active_runs.clear()
        _resume_events.clear()
