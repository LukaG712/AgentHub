"""SQLite persistence layer for the mission control system.

Provides CRUD operations for missions, milestones, features, validation
contracts, results, and checkpoints using SQLite with WAL mode.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from hub.mission.models import (
    Mission,
    MissionCheckpoint,
    MissionFeature,
    MissionMilestone,
    ValidationContract,
    ValidationResult,
)

# Database path from env or default — reuse the workflow data directory
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DB_PATH = os.environ.get("GREENIE_MISSION_DB_PATH", str(_DATA_DIR / "missions.db"))

_db_lock = threading.Lock()


def _get_connection() -> sqlite3.Connection:
    """Get a new database connection with WAL mode."""
    db_dir = Path(_DB_PATH).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema() -> None:
    """Initialize the database schema if not already present."""
    conn = _get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS missions (
                id TEXT PRIMARY KEY,
                description TEXT NOT NULL DEFAULT '',
                target_repository TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'planning',
                orchestrator_model TEXT,
                worker_model TEXT,
                validator_model TEXT,
                autonomy_level TEXT NOT NULL DEFAULT 'restricted_autonomous',
                milestones_json TEXT NOT NULL DEFAULT '[]',
                validation_contract_json TEXT,
                artifacts_json TEXT NOT NULL DEFAULT '[]',
                error TEXT NOT NULL DEFAULT '',
                parallel_workers INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS mission_checkpoints (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                state_json TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS validation_results (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                milestone_id TEXT,
                severity TEXT NOT NULL DEFAULT 'info',
                file_path TEXT,
                line_number INTEGER,
                explanation TEXT NOT NULL DEFAULT '',
                suggested_correction TEXT NOT NULL DEFAULT '',
                verified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS mission_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_id TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                message TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                timestamp TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(status);
            CREATE INDEX IF NOT EXISTS idx_missions_repo ON missions(target_repository);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_mission ON mission_checkpoints(mission_id);
            CREATE INDEX IF NOT EXISTS idx_validation_mission ON validation_results(mission_id);
            CREATE INDEX IF NOT EXISTS idx_mission_logs_mission ON mission_logs(mission_id);
            CREATE INDEX IF NOT EXISTS idx_mission_logs_timestamp ON mission_logs(timestamp);
        """)
        conn.commit()
    finally:
        conn.close()


# Initialize schema on import
_init_schema()


# ─── Missions ────────────────────────────────────────────────────────────────

def save_mission(mission: Mission) -> Mission:
    """Save or update a mission."""
    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO missions
                   (id, description, target_repository, status, orchestrator_model,
                    worker_model, validator_model, autonomy_level, milestones_json,
                    validation_contract_json, artifacts_json, error, parallel_workers,
                    started_at, completed_at, created_at, updated_at, created_by, tags_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mission.id, mission.description, mission.target_repository,
                    mission.status, mission.orchestrator_model, mission.worker_model,
                    mission.validator_model, mission.autonomy_level,
                    json.dumps([m.to_dict() for m in mission.milestones]),
                    json.dumps(mission.validation_contract.to_dict()) if mission.validation_contract else None,
                    json.dumps(mission.artifacts),
                    mission.error, int(mission.parallel_workers),
                    mission.started_at, mission.completed_at,
                    mission.created_at, mission.updated_at,
                    mission.created_by, json.dumps(mission.tags),
                ),
            )
            conn.commit()
            return mission
        finally:
            conn.close()


def get_mission(mission_id: str) -> Optional[Mission]:
    """Get a mission by ID."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM missions WHERE id = ?", (mission_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_mission(row)
    finally:
        conn.close()


def list_missions(
    status: Optional[str] = None,
    target_repository: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Mission]:
    """List missions with optional filters."""
    conn = _get_connection()
    try:
        query = "SELECT * FROM missions WHERE 1=1"
        params: list[Any] = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if target_repository:
            query += " AND target_repository = ?"
            params.append(target_repository)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [_row_to_mission(r) for r in rows]
    finally:
        conn.close()


def delete_mission(mission_id: str) -> bool:
    """Delete a mission and its related data."""
    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute("DELETE FROM mission_checkpoints WHERE mission_id = ?", (mission_id,))
            conn.execute("DELETE FROM validation_results WHERE mission_id = ?", (mission_id,))
            cursor = conn.execute("DELETE FROM missions WHERE id = ?", (mission_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def _row_to_mission(row: sqlite3.Row) -> Mission:
    """Convert a database row to a Mission."""
    milestones = [MissionMilestone.from_dict(m) for m in json.loads(row["milestones_json"])]
    validation_contract = None
    if row["validation_contract_json"]:
        validation_contract = ValidationContract.from_dict(json.loads(row["validation_contract_json"]))
    return Mission(
        id=row["id"],
        description=row["description"],
        target_repository=row["target_repository"],
        status=row["status"],
        orchestrator_model=row["orchestrator_model"],
        worker_model=row["worker_model"],
        validator_model=row["validator_model"],
        autonomy_level=row["autonomy_level"],
        milestones=milestones,
        validation_contract=validation_contract,
        artifacts=json.loads(row["artifacts_json"]),
        error=row["error"],
        parallel_workers=bool(row["parallel_workers"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        created_by=row["created_by"],
        tags=json.loads(row["tags_json"]),
    )


# ─── Mission Checkpoints ─────────────────────────────────────────────────────

def save_checkpoint(checkpoint: MissionCheckpoint) -> MissionCheckpoint:
    """Save a mission checkpoint."""
    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO mission_checkpoints
                   (id, mission_id, state_json, description, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    checkpoint.id, checkpoint.mission_id,
                    checkpoint.state_json, checkpoint.description,
                    checkpoint.created_at,
                ),
            )
            conn.commit()
            return checkpoint
        finally:
            conn.close()


def get_latest_checkpoint(mission_id: str) -> Optional[MissionCheckpoint]:
    """Get the most recent checkpoint for a mission."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM mission_checkpoints WHERE mission_id = ? ORDER BY created_at DESC LIMIT 1",
            (mission_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_checkpoint(row)
    finally:
        conn.close()


def list_checkpoints(mission_id: str) -> list[MissionCheckpoint]:
    """List all checkpoints for a mission."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM mission_checkpoints WHERE mission_id = ? ORDER BY created_at DESC",
            (mission_id,),
        ).fetchall()
        return [_row_to_checkpoint(r) for r in rows]
    finally:
        conn.close()


def _row_to_checkpoint(row: sqlite3.Row) -> MissionCheckpoint:
    """Convert a database row to a MissionCheckpoint."""
    return MissionCheckpoint(
        id=row["id"],
        mission_id=row["mission_id"],
        state_json=row["state_json"],
        description=row["description"],
        created_at=row["created_at"],
    )


# ─── Validation Results ──────────────────────────────────────────────────────

def save_validation_result(result: ValidationResult) -> ValidationResult:
    """Save a validation result."""
    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO validation_results
                   (id, mission_id, milestone_id, severity, file_path, line_number,
                    explanation, suggested_correction, verified, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.id, result.mission_id, result.milestone_id,
                    result.severity, result.file_path, result.line_number,
                    result.explanation, result.suggested_correction,
                    int(result.verified), result.created_at,
                ),
            )
            conn.commit()
            return result
        finally:
            conn.close()


def get_validation_results(
    mission_id: str,
    milestone_id: Optional[str] = None,
    severity: Optional[str] = None,
) -> list[ValidationResult]:
    """Get validation results for a mission."""
    conn = _get_connection()
    try:
        query = "SELECT * FROM validation_results WHERE mission_id = ?"
        params: list[Any] = [mission_id]

        if milestone_id:
            query += " AND milestone_id = ?"
            params.append(milestone_id)
        if severity:
            query += " AND severity = ?"
            params.append(severity)

        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [_row_to_validation_result(r) for r in rows]
    finally:
        conn.close()


def _row_to_validation_result(row: sqlite3.Row) -> ValidationResult:
    """Convert a database row to a ValidationResult."""
    return ValidationResult(
        id=row["id"],
        mission_id=row["mission_id"],
        milestone_id=row["milestone_id"],
        severity=row["severity"],
        file_path=row["file_path"],
        line_number=row["line_number"],
        explanation=row["explanation"],
        suggested_correction=row["suggested_correction"],
        verified=bool(row["verified"]),
        created_at=row["created_at"],
    )


# ─── Statistics ──────────────────────────────────────────────────────────────

def get_mission_stats() -> dict[str, Any]:
    """Get mission control statistics."""
    conn = _get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM missions").fetchone()[0]
        planning = conn.execute(
            "SELECT COUNT(*) FROM missions WHERE status = 'planning'"
        ).fetchone()[0]
        executing = conn.execute(
            "SELECT COUNT(*) FROM missions WHERE status = 'executing'"
        ).fetchone()[0]
        validating = conn.execute(
            "SELECT COUNT(*) FROM missions WHERE status = 'validating'"
        ).fetchone()[0]
        completed = conn.execute(
            "SELECT COUNT(*) FROM missions WHERE status = 'completed'"
        ).fetchone()[0]
        failed = conn.execute(
            "SELECT COUNT(*) FROM missions WHERE status = 'failed'"
        ).fetchone()[0]
        cancelled = conn.execute(
            "SELECT COUNT(*) FROM missions WHERE status = 'cancelled'"
        ).fetchone()[0]
        paused = conn.execute(
            "SELECT COUNT(*) FROM missions WHERE status = 'paused'"
        ).fetchone()[0]
        return {
            "total_missions": total,
            "planning": planning,
            "executing": executing,
            "validating": validating,
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
            "paused": paused,
        }
    finally:
        conn.close()


# ─── Mission Execution Logs ──────────────────────────────────────────────────

def save_mission_log(
    mission_id: str,
    level: str,
    message: str,
    source: str = "",
) -> int:
    """Save an execution log entry for a mission.

    Returns the log entry ID.
    """
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).isoformat()
    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.execute(
                """INSERT INTO mission_logs (mission_id, level, message, source, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (mission_id, level, message, source, timestamp),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()


def get_mission_logs(
    mission_id: str,
    level: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Get execution logs for a mission.

    Returns logs sorted by timestamp descending (newest first).
    """
    conn = _get_connection()
    try:
        query = "SELECT * FROM mission_logs WHERE mission_id = ?"
        params: list[Any] = [mission_id]

        if level:
            query += " AND level = ?"
            params.append(level)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [
            {
                "id": row["id"],
                "mission_id": row["mission_id"],
                "level": row["level"],
                "message": row["message"],
                "source": row["source"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_mission_logs_since(
    mission_id: str,
    since_timestamp: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Get execution logs for a mission since a given timestamp.

    Used by SSE streaming to deliver only new log entries.
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM mission_logs
               WHERE mission_id = ? AND timestamp > ?
               ORDER BY timestamp ASC
               LIMIT ?""",
            (mission_id, since_timestamp, limit),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "mission_id": row["mission_id"],
                "level": row["level"],
                "message": row["message"],
                "source": row["source"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def delete_mission_logs(mission_id: str) -> int:
    """Delete all logs for a mission. Returns number of deleted rows."""
    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.execute("DELETE FROM mission_logs WHERE mission_id = ?", (mission_id,))
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
