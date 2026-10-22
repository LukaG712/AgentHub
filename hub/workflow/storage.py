"""SQLite persistence layer for the workflow engine.

Provides CRUD operations for workflow definitions, runs, and approvals
using SQLite with WAL mode for concurrent read/write access.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from hub.workflow.models import (
    WorkflowApproval,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStep,
    WorkflowStepRun,
    WorkflowTrigger,
)

# Database path from env or default
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DB_PATH = os.environ.get("GREENIE_WORKFLOW_DB_PATH", str(_DATA_DIR / "workflows.db"))

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
            CREATE TABLE IF NOT EXISTS workflow_definitions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                steps_json TEXT NOT NULL DEFAULT '[]',
                triggers_json TEXT NOT NULL DEFAULT '[]',
                enabled INTEGER NOT NULL DEFAULT 1,
                timeout_minutes INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS workflow_runs (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                workflow_name TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                trigger_type TEXT DEFAULT '',
                trigger_data_json TEXT NOT NULL DEFAULT '{}',
                step_runs_json TEXT NOT NULL DEFAULT '[]',
                current_step_index INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                completed_at TEXT,
                duration_seconds REAL NOT NULL DEFAULT 0.0,
                error TEXT DEFAULT '',
                started_by TEXT DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS workflow_approvals (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                resolved_by TEXT DEFAULT '',
                timeout_minutes INTEGER NOT NULL DEFAULT 30,
                context_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_runs_workflow ON workflow_runs(workflow_id);
            CREATE INDEX IF NOT EXISTS idx_runs_status ON workflow_runs(status);
            CREATE INDEX IF NOT EXISTS idx_approvals_run ON workflow_approvals(run_id);
            CREATE INDEX IF NOT EXISTS idx_approvals_status ON workflow_approvals(status);
        """)
        conn.commit()
    finally:
        conn.close()


# Initialize schema on import
with _db_lock:
    _init_schema()


# ─── Workflow Definitions ───────────────────────────────────────────────────

def save_workflow_definition(wf: WorkflowDefinition) -> WorkflowDefinition:
    """Save or update a workflow definition."""
    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO workflow_definitions
                   (id, name, description, steps_json, triggers_json, enabled,
                    timeout_minutes, created_at, updated_at, created_by, tags_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    wf.id, wf.name, wf.description,
                    json.dumps([s.to_dict() for s in wf.steps]),
                    json.dumps([t.to_dict() for t in wf.triggers]),
                    int(wf.enabled),
                    wf.timeout_minutes,
                    wf.created_at,
                    wf.updated_at,
                    wf.created_by,
                    json.dumps(wf.tags),
                ),
            )
            conn.commit()
            return wf
        finally:
            conn.close()


def get_workflow_definition(workflow_id: str) -> Optional[WorkflowDefinition]:
    """Get a workflow definition by ID."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM workflow_definitions WHERE id = ?", (workflow_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_workflow(row)
    finally:
        conn.close()


def list_workflow_definitions(limit: int = 50, offset: int = 0) -> list[WorkflowDefinition]:
    """List workflow definitions with pagination."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM workflow_definitions ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_row_to_workflow(r) for r in rows]
    finally:
        conn.close()


def delete_workflow_definition(workflow_id: str) -> bool:
    """Delete a workflow definition."""
    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM workflow_definitions WHERE id = ?", (workflow_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def _row_to_workflow(row: sqlite3.Row) -> WorkflowDefinition:
    """Convert a database row to a WorkflowDefinition."""
    steps = [WorkflowStep.from_dict(s) for s in json.loads(row["steps_json"])]
    triggers = [WorkflowTrigger.from_dict(t) for t in json.loads(row["triggers_json"])]
    return WorkflowDefinition(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        steps=steps,
        triggers=triggers,
        enabled=bool(row["enabled"]),
        timeout_minutes=row["timeout_minutes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        created_by=row["created_by"],
        tags=json.loads(row["tags_json"]),
    )


# ─── Workflow Runs ──────────────────────────────────────────────────────────

def save_workflow_run(run: WorkflowRun) -> WorkflowRun:
    """Save or update a workflow run."""
    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO workflow_runs
                   (id, workflow_id, workflow_name, status, trigger_type,
                    trigger_data_json, step_runs_json, current_step_index,
                    started_at, completed_at, duration_seconds, error,
                    started_by, tags_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.id, run.workflow_id, run.workflow_name, run.status,
                    run.trigger_type,
                    json.dumps(run.trigger_data),
                    json.dumps([s.to_dict() for s in run.step_runs]),
                    run.current_step_index,
                    run.started_at,
                    run.completed_at,
                    run.duration_seconds,
                    run.error,
                    run.started_by,
                    json.dumps(run.tags),
                ),
            )
            conn.commit()
            return run
        finally:
            conn.close()


def get_workflow_run(run_id: str) -> Optional[WorkflowRun]:
    """Get a workflow run by ID."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM workflow_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_run(row)
    finally:
        conn.close()


def list_workflow_runs(
    workflow_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[WorkflowRun]:
    """List workflow runs with optional filters."""
    conn = _get_connection()
    try:
        query = "SELECT * FROM workflow_runs WHERE 1=1"
        params: list[Any] = []

        if workflow_id:
            query += " AND workflow_id = ?"
            params.append(workflow_id)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [_row_to_run(r) for r in rows]
    finally:
        conn.close()


def delete_workflow_run(run_id: str) -> bool:
    """Delete a workflow run and its approvals."""
    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute("DELETE FROM workflow_approvals WHERE run_id = ?", (run_id,))
            cursor = conn.execute("DELETE FROM workflow_runs WHERE id = ?", (run_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def _row_to_run(row: sqlite3.Row) -> WorkflowRun:
    """Convert a database row to a WorkflowRun."""
    step_runs = [WorkflowStepRun.from_dict(s) for s in json.loads(row["step_runs_json"])]
    return WorkflowRun(
        id=row["id"],
        workflow_id=row["workflow_id"],
        workflow_name=row["workflow_name"],
        status=row["status"],
        trigger_type=row["trigger_type"],
        trigger_data=json.loads(row["trigger_data_json"]),
        step_runs=step_runs,
        current_step_index=row["current_step_index"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        duration_seconds=row["duration_seconds"],
        error=row["error"],
        started_by=row["started_by"],
        tags=json.loads(row["tags_json"]),
    )


# ─── Workflow Approvals ─────────────────────────────────────────────────────

def save_workflow_approval(approval: WorkflowApproval) -> WorkflowApproval:
    """Save or update a workflow approval."""
    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO workflow_approvals
                   (id, run_id, step_id, description, status, created_at,
                    resolved_at, resolved_by, timeout_minutes, context_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    approval.id, approval.run_id, approval.step_id,
                    approval.description, approval.status, approval.created_at,
                    approval.resolved_at, approval.resolved_by,
                    approval.timeout_minutes,
                    json.dumps(approval.context),
                ),
            )
            conn.commit()
            return approval
        finally:
            conn.close()


def get_workflow_approval(approval_id: str) -> Optional[WorkflowApproval]:
    """Get a workflow approval by ID."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM workflow_approvals WHERE id = ?", (approval_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_approval(row)
    finally:
        conn.close()


def list_workflow_approvals(
    run_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[WorkflowApproval]:
    """List workflow approvals with optional filters."""
    conn = _get_connection()
    try:
        query = "SELECT * FROM workflow_approvals WHERE 1=1"
        params: list[Any] = []

        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [_row_to_approval(r) for r in rows]
    finally:
        conn.close()


def _row_to_approval(row: sqlite3.Row) -> WorkflowApproval:
    """Convert a database row to a WorkflowApproval."""
    return WorkflowApproval(
        id=row["id"],
        run_id=row["run_id"],
        step_id=row["step_id"],
        description=row["description"],
        status=row["status"],
        created_at=row["created_at"],
        resolved_at=row["resolved_at"],
        resolved_by=row["resolved_by"],
        timeout_minutes=row["timeout_minutes"],
        context=json.loads(row["context_json"]),
    )


# ─── Statistics ──────────────────────────────────────────────────────────────

def get_workflow_stats() -> dict[str, Any]:
    """Get workflow engine statistics."""
    conn = _get_connection()
    try:
        defs_count = conn.execute("SELECT COUNT(*) FROM workflow_definitions").fetchone()[0]
        runs_count = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
        pending_runs = conn.execute(
            "SELECT COUNT(*) FROM workflow_runs WHERE status IN ('pending', 'running', 'waiting_approval')"
        ).fetchone()[0]
        pending_approvals = conn.execute(
            "SELECT COUNT(*) FROM workflow_approvals WHERE status = 'pending'"
        ).fetchone()[0]
        return {
            "total_workflows": defs_count,
            "total_runs": runs_count,
            "active_runs": pending_runs,
            "pending_approvals": pending_approvals,
        }
    finally:
        conn.close()
