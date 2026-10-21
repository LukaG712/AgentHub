"""Built-in task manager application for Agent Hub."""

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from hub.config import load_config

_TASKS_FILE = "tasks.json"


def _get_tasks_path() -> Path:
    config = load_config()
    data_dir = Path(config.get("data_dir", "data"))
    return data_dir / _TASKS_FILE


@dataclass
class Task:
    id: str
    title: str
    description: str = ""
    done: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_tasks: List[Task] = []
_tasks_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> None:
    global _tasks
    path = _get_tasks_path()
    if path.exists():
        try:
            data = json.loads(path.read_text())
            _tasks = [Task(**t) for t in data]
        except (json.JSONDecodeError, TypeError):
            _tasks = []
    else:
        _tasks = []


def _save() -> None:
    path = _get_tasks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([t.to_dict() for t in _tasks], indent=2))


# Load on import
_load()


def list_tasks() -> List[Dict[str, Any]]:
    with _tasks_lock:
        return [t.to_dict() for t in _tasks]


def create_task(title: str, description: str = "") -> Dict[str, Any]:
    import uuid
    task = Task(
        id=uuid.uuid4().hex[:8],
        title=title,
        description=description,
        created_at=_now(),
        updated_at=_now(),
    )
    with _tasks_lock:
        _tasks.append(task)
        _save()
    return task.to_dict()


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    with _tasks_lock:
        for t in _tasks:
            if t.id == task_id:
                return t.to_dict()
    return None


def update_task(task_id: str, **kwargs) -> Optional[Dict[str, Any]]:
    with _tasks_lock:
        for t in _tasks:
            if t.id == task_id:
                for key, value in kwargs.items():
                    if hasattr(t, key):
                        setattr(t, key, value)
                t.updated_at = _now()
                _save()
                return t.to_dict()
    return None


def delete_task(task_id: str) -> bool:
    with _tasks_lock:
        for i, t in enumerate(_tasks):
            if t.id == task_id:
                _tasks.pop(i)
                _save()
                return True
    return False
