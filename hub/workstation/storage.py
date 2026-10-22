"""SQLite persistence layer for workstations.

Provides CRUD operations for workstation state using SQLite with WAL mode
for concurrent read/write access.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from hub.workstation.models import (
    Workstation,
    WorkstationAccess,
    WorkstationConfig,
    WorkstationStatus,
)

# Database path from env or default
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

_db_lock = threading.Lock()


def _get_db_path() -> str:
    """Get the database path from env or default."""
    return os.environ.get("GREENIE_WORKSTATION_DB_PATH", str(_DATA_DIR / "workstations.db"))


def _get_connection() -> sqlite3.Connection:
    """Get a new database connection with WAL mode."""
    db_path = _get_db_path()
    db_dir = Path(db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema() -> None:
    """Initialize the database schema if not already present."""
    conn = _get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS workstations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                container_id TEXT DEFAULT '',
                container_name TEXT DEFAULT '',
                config_json TEXT NOT NULL DEFAULT '{}',
                access_json TEXT,
                cpu_percent REAL NOT NULL DEFAULT 0.0,
                memory_usage_bytes INTEGER NOT NULL DEFAULT 0,
                disk_usage_bytes INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                stopped_at TEXT,
                destroyed_at TEXT,
                error TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                agent_name TEXT DEFAULT '',
                workflow_run_id TEXT DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]'
            );

            CREATE INDEX IF NOT EXISTS idx_ws_status ON workstations(status);
            CREATE INDEX IF NOT EXISTS idx_ws_agent ON workstations(agent_name);
            CREATE INDEX IF NOT EXISTS idx_ws_workflow ON workstations(workflow_run_id);
        """)
        conn.commit()
    finally:
        conn.close()


# Initialize schema on import
_init_schema()


# ─── Workstations ────────────────────────────────────────────────────────────

def save_workstation(ws: Workstation) -> Workstation:
    """Save or update a workstation."""
    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO workstations
                   (id, name, description, status, container_id, container_name,
                    config_json, access_json, cpu_percent, memory_usage_bytes,
                    disk_usage_bytes, created_at, started_at, stopped_at,
                    destroyed_at, error, created_by, agent_name, workflow_run_id, tags_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ws.id, ws.name, ws.description, ws.status,
                    ws.container_id, ws.container_name,
                    json.dumps(ws.config.to_dict()),
                    json.dumps(ws.access.to_dict()) if ws.access else None,
                    ws.cpu_percent, ws.memory_usage_bytes, ws.disk_usage_bytes,
                    ws.created_at, ws.started_at, ws.stopped_at, ws.destroyed_at,
                    ws.error, ws.created_by, ws.agent_name, ws.workflow_run_id,
                    json.dumps(ws.tags),
                ),
            )
            conn.commit()
            return ws
        finally:
            conn.close()


def get_workstation(workstation_id: str) -> Optional[Workstation]:
    """Get a workstation by ID."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM workstations WHERE id = ?", (workstation_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_workstation(row)
    finally:
        conn.close()


def list_workstations(
    status: Optional[str] = None,
    agent_name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Workstation]:
    """List workstations with optional filtering and pagination."""
    conn = _get_connection()
    try:
        query = "SELECT * FROM workstations WHERE 1=1"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if agent_name:
            query += " AND agent_name = ?"
            params.append(agent_name)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [_row_to_workstation(r) for r in rows]
    finally:
        conn.close()


def delete_workstation(workstation_id: str) -> bool:
    """Delete a workstation record."""
    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM workstations WHERE id = ?", (workstation_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def update_workstation_status(workstation_id: str, status: str, error: str = "") -> bool:
    """Update a workstation's status and optionally an error message."""
    with _db_lock:
        conn = _get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            if status == WorkstationStatus.RUNNING.value:
                conn.execute(
                    "UPDATE workstations SET status = ?, error = ?, started_at = ? WHERE id = ?",
                    (status, error, now, workstation_id),
                )
            elif status == WorkstationStatus.STOPPED.value:
                conn.execute(
                    "UPDATE workstations SET status = ?, error = ?, stopped_at = ? WHERE id = ?",
                    (status, error, now, workstation_id),
                )
            elif status == WorkstationStatus.DESTROYED.value:
                conn.execute(
                    "UPDATE workstations SET status = ?, error = ?, destroyed_at = ? WHERE id = ?",
                    (status, error, now, workstation_id),
                )
            else:
                conn.execute(
                    "UPDATE workstations SET status = ?, error = ? WHERE id = ?",
                    (status, error, workstation_id),
                )
            conn.commit()
            return True
        finally:
            conn.close()


def count_workstations(status: Optional[str] = None) -> int:
    """Count workstations, optionally filtered by status."""
    conn = _get_connection()
    try:
        if status:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM workstations WHERE status = ?", (status,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as cnt FROM workstations").fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


def _row_to_workstation(row: sqlite3.Row) -> Workstation:
    """Convert a database row to a Workstation."""
    config_data = json.loads(row["config_json"]) if row["config_json"] else {}
    config = WorkstationConfig.from_dict(config_data) if config_data else WorkstationConfig()

    access_data = json.loads(row["access_json"]) if row["access_json"] else None
    access = WorkstationAccess.from_dict(access_data) if access_data else None

    return Workstation(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        status=row["status"],
        container_id=row["container_id"],
        container_name=row["container_name"],
        config=config,
        access=access,
        cpu_percent=row["cpu_percent"],
        memory_usage_bytes=row["memory_usage_bytes"],
        disk_usage_bytes=row["disk_usage_bytes"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        stopped_at=row["stopped_at"],
        destroyed_at=row["destroyed_at"],
        error=row["error"],
        created_by=row["created_by"],
        agent_name=row["agent_name"],
        workflow_run_id=row["workflow_run_id"],
        tags=json.loads(row["tags_json"]),
    )
