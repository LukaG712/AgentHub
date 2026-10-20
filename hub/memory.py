"""SQLite-based persistence for conversations, sessions, and memories."""

import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_DB_PATH = _DATA_DIR / "hub.db"

# Thread-local storage for database connections
_local = threading.local()

# Global lock for schema initialization
_schema_lock = threading.Lock()


def _get_db_path() -> Path:
    """Get database path, respecting HUB_DB_PATH env var for testing."""
    path = os.environ.get("HUB_DB_PATH")
    if path:
        return Path(path)
    return _DB_PATH


def _get_connection() -> sqlite3.Connection:
    """Get a thread-local database connection, creating it if needed.

    Retries on transient SQLite lock errors (e.g. another thread holding a lock
    during PRAGMA journal_mode=WAL). This avoids flaky test failures when the
    scheduler thread and test thread open connections concurrently.
    """
    if not hasattr(_local, "conn") or _local.conn is None:
        db_path = _get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        max_retries = 5
        for attempt in range(max_retries):
            try:
                conn = sqlite3.connect(str(db_path), timeout=10.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.row_factory = sqlite3.Row
                _ensure_schema(conn)
                _local.conn = conn
                break
            except sqlite3.OperationalError:
                if conn is not None:
                    conn.close()
                if attempt == max_retries - 1:
                    raise
                time.sleep(0.1 * (attempt + 1))
    return _local.conn


def _add_column_if_not_exists(cursor: sqlite3.Cursor, table: str, column: str, col_type: str) -> None:
    cursor.execute(f"PRAGMA table_info({table})")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if column not in existing_cols:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    with _schema_lock:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                project_path TEXT,
                agent_id TEXT,
                bot_ids TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
                content TEXT NOT NULL DEFAULT '',
                run_id TEXT,
                bot_id TEXT,
                msg_type TEXT NOT NULL DEFAULT 'message',
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL DEFAULT '',
                project_path TEXT,
                session_id TEXT,
                agent_id TEXT,
                tags TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                run_id TEXT,
                session_id TEXT,
                bot_id TEXT,
                action_type TEXT NOT NULL DEFAULT 'command',
                description TEXT NOT NULL DEFAULT '',
                pattern_matched TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                decided_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS routines (
                id TEXT PRIMARY KEY,
                bot_id TEXT NOT NULL,
                name TEXT NOT NULL,
                task_text TEXT NOT NULL,
                schedule_type TEXT NOT NULL DEFAULT 'interval',
                schedule_value TEXT NOT NULL DEFAULT '3600',
                enabled INTEGER NOT NULL DEFAULT 1,
                last_run_at TEXT,
                next_run_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # Schema migration for existing tables
        _add_column_if_not_exists(cursor, "sessions", "bot_ids", "TEXT")
        _add_column_if_not_exists(cursor, "messages", "bot_id", "TEXT")
        _add_column_if_not_exists(cursor, "messages", "msg_type", "TEXT NOT NULL DEFAULT 'message'")
        _add_column_if_not_exists(cursor, "messages", "metadata", "TEXT")

        # Indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session_id
            ON messages(session_id, created_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
            ON sessions(updated_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_agent_id
            ON sessions(agent_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_agent_id
            ON memories(agent_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_project_path
            ON memories(project_path)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_created_at
            ON memories(created_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_approvals_session
            ON approvals(session_id, status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_approvals_bot
            ON approvals(bot_id, status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_routines_bot
            ON routines(bot_id, enabled)
        """)
        conn.commit()


def close_connection() -> None:
    """Close the thread-local database connection."""
    if hasattr(_local, "conn") and _local.conn is not None:
        _local.conn.close()
        _local.conn = None


# --- Sessions ---

def create_session(
    title: str = "",
    project_path: Optional[str] = None,
    agent_id: Optional[str] = None,
    bot_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new session and return its dict representation."""
    import json as _json
    now = datetime.now(timezone.utc).isoformat()
    session_id = str(uuid.uuid4())
    conn = _get_connection()
    bot_ids_val = _json.dumps(bot_ids) if bot_ids is not None else (_json.dumps([agent_id]) if agent_id else None)
    conn.execute(
        """INSERT INTO sessions (id, title, project_path, agent_id, bot_ids, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (session_id, title, project_path, agent_id, bot_ids_val, now, now),
    )
    conn.commit()
    return _session_to_dict(conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone())


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Get a session by ID."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        return None
    return _session_to_dict(row)


def list_sessions(
    agent_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List sessions ordered by recent activity, optionally filtered by agent."""
    conn = _get_connection()
    if agent_id:
        rows = conn.execute(
            """SELECT s.*, m.content AS last_message
               FROM sessions s
               LEFT JOIN messages m ON m.session_id = s.id
                   AND m.id = (
                       SELECT id FROM messages
                       WHERE session_id = s.id
                       ORDER BY created_at DESC LIMIT 1
                   )
               WHERE s.agent_id = ?
               ORDER BY s.updated_at DESC
               LIMIT ?""",
            (agent_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT s.*, m.content AS last_message
               FROM sessions s
               LEFT JOIN messages m ON m.session_id = s.id
                   AND m.id = (
                       SELECT id FROM messages
                       WHERE session_id = s.id
                       ORDER BY created_at DESC LIMIT 1
                   )
               ORDER BY s.updated_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [_session_to_dict(r) for r in rows]


def delete_session(session_id: str) -> bool:
    """Delete a session and its messages. Returns True if deleted."""
    conn = _get_connection()
    cursor = conn.execute(
        "DELETE FROM sessions WHERE id = ?", (session_id,)
    )
    conn.commit()
    return cursor.rowcount > 0


def update_session_timestamp(session_id: str) -> None:
    """Update the updated_at timestamp for a session."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_connection()
    conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?",
        (now, session_id),
    )
    conn.commit()


def _session_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a session row to a dict."""
    d = dict(row)
    # Remove last_message from the main dict, add as separate field
    last_message = d.pop("last_message", None)
    if last_message is not None:
        d["last_message_preview"] = last_message[:200] if len(last_message) > 200 else last_message
    return d


# --- Messages ---

def add_message(
    session_id: str,
    role: str,
    content: str,
    run_id: Optional[str] = None,
    bot_id: Optional[str] = None,
    msg_type: str = "message",
    metadata: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a message to a session."""
    if role not in ("user", "assistant", "system", "tool"):
        raise ValueError(f"Invalid role: {role}")
    now = datetime.now(timezone.utc).isoformat()
    message_id = str(uuid.uuid4())
    conn = _get_connection()
    conn.execute(
        """INSERT INTO messages (id, session_id, role, content, run_id, bot_id, msg_type, metadata, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (message_id, session_id, role, content, run_id, bot_id, msg_type, metadata, now),
    )
    conn.commit()
    # Update session timestamp
    conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?",
        (now, session_id),
    )
    conn.commit()
    return _message_to_dict(conn.execute(
        "SELECT * FROM messages WHERE id = ?", (message_id,)
    ).fetchone())


def get_session_messages(session_id: str) -> List[Dict[str, Any]]:
    """Get all messages for a session in chronological order."""
    conn = _get_connection()
    rows = conn.execute(
        """SELECT * FROM messages
           WHERE session_id = ?
           ORDER BY created_at ASC""",
        (session_id,),
    ).fetchall()
    return [_message_to_dict(r) for r in rows]


def get_session_with_messages(session_id: str) -> Optional[Dict[str, Any]]:
    """Get a session with its messages."""
    session = get_session(session_id)
    if session is None:
        return None
    messages = get_session_messages(session_id)
    return {**session, "messages": messages}


def _message_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a message row to a dict."""
    return dict(row)


# --- Memories ---

def create_memory(
    content: str,
    project_path: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    tags: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new memory."""
    now = datetime.now(timezone.utc).isoformat()
    memory_id = str(uuid.uuid4())
    conn = _get_connection()
    conn.execute(
        """INSERT INTO memories (id, content, project_path, session_id, agent_id, tags, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (memory_id, content, project_path, session_id, agent_id, tags, now, now),
    )
    conn.commit()
    return _memory_to_dict(conn.execute(
        "SELECT * FROM memories WHERE id = ?", (memory_id,)
    ).fetchone())


def get_memory(memory_id: str) -> Optional[Dict[str, Any]]:
    """Get a memory by ID."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM memories WHERE id = ?", (memory_id,)
    ).fetchone()
    if row is None:
        return None
    return _memory_to_dict(row)


def list_memories(
    agent_id: Optional[str] = None,
    project_path: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List memories with optional filters and search."""
    conn = _get_connection()
    conditions = []
    params: List[Any] = []

    if agent_id:
        conditions.append("agent_id = ?")
        params.append(agent_id)
    if project_path:
        conditions.append("project_path = ?")
        params.append(project_path)
    if search:
        conditions.append("(content LIKE ? OR tags LIKE ?)")
        search_pattern = f"%{search}%"
        params.extend([search_pattern, search_pattern])

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    params.append(limit)
    rows = conn.execute(
        f"""SELECT * FROM memories {where}
            ORDER BY created_at DESC LIMIT ?""",
        params,
    ).fetchall()
    return [_memory_to_dict(r) for r in rows]


def search_memories(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Search memories by content using SQLite LIKE."""
    return list_memories(search=query, limit=limit)


def update_memory(memory_id: str, content: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Update a memory's content."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    if content is not None:
        conn.execute(
            "UPDATE memories SET content = ?, updated_at = ? WHERE id = ?",
            (content, now, memory_id),
        )
    else:
        conn.execute(
            "UPDATE memories SET updated_at = ? WHERE id = ?",
            (now, memory_id),
        )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM memories WHERE id = ?", (memory_id,)
    ).fetchone()
    if row is None:
        return None
    return _memory_to_dict(row)


def delete_memory(memory_id: str) -> bool:
    """Delete a memory. Returns True if deleted."""
    conn = _get_connection()
    cursor = conn.execute(
        "DELETE FROM memories WHERE id = ?", (memory_id,)
    )
    conn.commit()
    return cursor.rowcount > 0


def _memory_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a memory row to a dict."""
    return dict(row)


# --- Project discovery ---

def discover_projects(workspace_roots: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Discover Git repositories from workspace roots.
    
    Scans common directories for .git subdirectories.
    Returns a list of project paths with metadata.
    """
    if workspace_roots is None:
        workspace_roots = _default_workspace_roots()

    projects = []
    seen = set()

    for root in workspace_roots:
        root_path = Path(root)
        if not root_path.exists() or not root_path.is_dir():
            continue
        try:
            for entry in root_path.iterdir():
                if entry.is_dir() and (entry / ".git").exists():
                    real_path = str(entry.resolve())
                    if real_path not in seen:
                        seen.add(real_path)
                        projects.append({
                            "name": entry.name,
                            "path": real_path,
                        })
        except PermissionError:
            continue

    return projects


def _default_workspace_roots() -> List[str]:
    """Get default workspace roots for project discovery."""
    roots = []
    home = Path.home()
    for name in ("workspace", "projects", "code", "Desktop", "Documents"):
        path = home / name
        if path.exists():
            roots.append(str(path))
    # Check current working directory's parent
    cwd = Path.cwd().parent
    if cwd.exists():
        roots.append(str(cwd))
    return roots


# --- Context assembly ---

def assemble_context(
    session_id: str,
    agent_id: Optional[str] = None,
    project_path: Optional[str] = None,
    guidelines: Optional[str] = None,
    max_messages: int = 20,
    max_memories: int = 10,
    max_context_chars: int = 32000,
) -> str:
    """Assemble context for an agent run from session history, memories, and project files.

    Returns a formatted context string to prepend to the task prompt.
    The most recent user message is excluded since it is the current task.
    Messages are ordered chronologically (created_at ASC).
    Memories are deduplicated by ID.
    """
    parts: List[str] = []
    sources: List[str] = []  # Track which sources were included

    # 1. Recent session messages (last N, excluding the most recent user message)
    messages = get_session_messages(session_id)
    if messages:
        # Exclude the most recent message if it's a user message (the current task)
        if messages and messages[-1].get("role") == "user":
            messages = messages[:-1]
        # Take the last max_messages messages (already in created_at ASC order)
        recent = messages[-max_messages:]
        if recent:
            conv_lines = []
            for msg in recent:
                role = msg["role"]
                content = msg["content"]
                if role == "user":
                    conv_lines.append(f"User: {content}")
                elif role == "assistant":
                    conv_lines.append(f"Assistant: {content}")
                elif role == "system":
                    conv_lines.append(f"(System: {content})")
            if conv_lines:
                parts.append("## Conversation History\n\n" + "\n\n".join(conv_lines))
                sources.append(f"session:{session_id} ({len(recent)} messages)")

    # 2. Relevant memories for the agent/project (deduplicated by ID)
    if agent_id or project_path:
        found_memories: List[Dict[str, Any]] = []
        seen_ids: set = set()
        if agent_id:
            for mem in list_memories(agent_id=agent_id, limit=max_memories):
                if mem["id"] not in seen_ids:
                    found_memories.append(mem)
                    seen_ids.add(mem["id"])
                    if len(found_memories) >= max_memories:
                        break
        if project_path and len(found_memories) < max_memories:
            for mem in list_memories(project_path=project_path, limit=max_memories):
                if mem["id"] not in seen_ids:
                    found_memories.append(mem)
                    seen_ids.add(mem["id"])
                    if len(found_memories) >= max_memories:
                        break
        if found_memories:
            mem_lines = []
            for mem in found_memories:
                content = mem["content"]
                tags = mem.get("tags", "")
                tag_str = f" [{tags}]" if tags else ""
                mem_lines.append(f"- {content}{tag_str}")
            parts.append("## Relevant Memories\n\n" + "\n".join(mem_lines))
            sources.append(f"memories ({len(found_memories)} items)")

    # 3. Project guidelines from agent config
    if guidelines:
        parts.append("## Agent Guidelines\n\n" + guidelines)
        sources.append("agent_guidelines")

    # 3b. Bot memory file (data/bots/{agent_id}/memory.md)
    if agent_id:
        try:
            from hub import bot_memory as bot_memory_module
            bot_mem = bot_memory_module.read_bot_memory(agent_id)
            if bot_mem.strip():
                parts.append("## Bot Memory\n\n" + bot_mem.strip())
                sources.append(f"bot_memory:{agent_id}")
        except (ValueError, OSError):
            pass  # Invalid bot_id or file not found

    # 4. Project files (AGENTS.md, README.md) — avoid duplicates
    included_files: set = set()
    if project_path:
        project_root = Path(project_path)
        # Check .junie/AGENTS.md first (highest priority)
        agents_md_path = project_root / ".junie" / "AGENTS.md"
        if agents_md_path.exists() and ".junie/AGENTS.md" not in included_files:
            try:
                content = agents_md_path.read_text(encoding="utf-8")
                parts.append("## Project Instructions (.junie/AGENTS.md)\n\n" + content)
                sources.append(".junie/AGENTS.md")
                included_files.add(".junie/AGENTS.md")
            except (OSError, PermissionError):
                pass
        # Check project-level AGENTS.md
        root_agents_md = project_root / "AGENTS.md"
        if root_agents_md.exists() and "AGENTS.md" not in included_files:
            try:
                content = root_agents_md.read_text(encoding="utf-8")
                parts.append("## Project Instructions (AGENTS.md)\n\n" + content)
                sources.append("AGENTS.md")
                included_files.add("AGENTS.md")
            except (OSError, PermissionError):
                pass
        # Check README.md (truncated)
        readme_path = project_root / "README.md"
        if readme_path.exists():
            try:
                content = readme_path.read_text(encoding="utf-8")
                if len(content) > 4000:
                    content = content[:4000] + "\n... (truncated)"
                parts.append("## Project File (README.md)\n\n" + content)
                sources.append("README.md")
            except (OSError, PermissionError):
                pass

    if not parts:
        return ""

    # Build final context string, respecting character limit
    header = "## Context from Previous Sessions\n\n"
    full = header + "\n\n---\n\n".join(parts)

    # Truncate if too long — drop least important sections first
    if len(full) > max_context_chars:
        # Remove conversation history first (least critical)
        if len(parts) > 1:
            parts = parts[:-1]  # Remove last part (conversation history)
            full = header + "\n\n---\n\n".join(parts)
        # If still too long, hard truncate
        if len(full) > max_context_chars:
            truncated = full[:max_context_chars - 100]
            truncated += "\n\n... (context truncated due to length)"
            full = truncated

    return full


# --- Approvals Persistence ---

def create_approval(
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
    bot_id: Optional[str] = None,
    action_type: str = "command",
    description: str = "",
    pattern_matched: str = "",
) -> Dict[str, Any]:
    """Create an approval record."""
    now = datetime.now(timezone.utc).isoformat()
    approval_id = str(uuid.uuid4())
    conn = _get_connection()
    conn.execute(
        """INSERT INTO approvals (id, run_id, session_id, bot_id, action_type, description, pattern_matched, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (approval_id, run_id, session_id, bot_id, action_type, description, pattern_matched, now),
    )
    conn.commit()
    return _approval_to_dict(conn.execute(
        "SELECT * FROM approvals WHERE id = ?", (approval_id,)
    ).fetchone())


def get_approval(approval_id: str) -> Optional[Dict[str, Any]]:
    """Get an approval by ID."""
    conn = _get_connection()
    row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    if row is None:
        return None
    return _approval_to_dict(row)


def list_approvals(
    session_id: Optional[str] = None,
    bot_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List approvals with optional filters."""
    conn = _get_connection()
    conditions = []
    params: List[Any] = []
    if session_id:
        conditions.append("session_id = ?")
        params.append(session_id)
    if bot_id:
        conditions.append("bot_id = ?")
        params.append(bot_id)
    if status:
        conditions.append("status = ?")
        params.append(status)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM approvals {where} ORDER BY created_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [_approval_to_dict(r) for r in rows]


def update_approval_status(approval_id: str, status: str) -> Optional[Dict[str, Any]]:
    """Update approval status (e.g. 'approved' or 'denied')."""
    if status not in ("pending", "approved", "denied"):
        raise ValueError(f"Invalid status: {status}")
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_connection()
    conn.execute(
        "UPDATE approvals SET status = ?, decided_at = ? WHERE id = ?",
        (status, now, approval_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    if row is None:
        return None
    return _approval_to_dict(row)


def _approval_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row)


# --- Routines Persistence ---

def create_routine(
    bot_id: str,
    name: str,
    task_text: str,
    schedule_type: str = "interval",
    schedule_value: str = "3600",
    enabled: bool = True,
) -> Dict[str, Any]:
    """Create a new routine for a bot."""
    now = datetime.now(timezone.utc).isoformat()
    routine_id = str(uuid.uuid4())
    conn = _get_connection()
    conn.execute(
        """INSERT INTO routines (id, bot_id, name, task_text, schedule_type, schedule_value, enabled, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (routine_id, bot_id, name, task_text, schedule_type, schedule_value, 1 if enabled else 0, now, now),
    )
    conn.commit()
    return _routine_to_dict(conn.execute(
        "SELECT * FROM routines WHERE id = ?", (routine_id,)
    ).fetchone())


def get_routine(routine_id: str) -> Optional[Dict[str, Any]]:
    """Get a routine by ID."""
    conn = _get_connection()
    row = conn.execute("SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone()
    if row is None:
        return None
    return _routine_to_dict(row)


def list_routines(
    bot_id: Optional[str] = None,
    enabled_only: bool = False,
) -> List[Dict[str, Any]]:
    """List routines, optionally filtered by bot and enabled state."""
    conn = _get_connection()
    conditions = []
    params: List[Any] = []
    if bot_id:
        conditions.append("bot_id = ?")
        params.append(bot_id)
    if enabled_only:
        conditions.append("enabled = 1")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM routines {where} ORDER BY created_at ASC",
        params,
    ).fetchall()
    return [_routine_to_dict(r) for r in rows]


def update_routine(
    routine_id: str,
    name: Optional[str] = None,
    task_text: Optional[str] = None,
    schedule_type: Optional[str] = None,
    schedule_value: Optional[str] = None,
    enabled: Optional[bool] = None,
    last_run_at: Optional[str] = None,
    next_run_at: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Update a routine."""
    conn = _get_connection()
    updates = []
    params: List[Any] = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if task_text is not None:
        updates.append("task_text = ?")
        params.append(task_text)
    if schedule_type is not None:
        updates.append("schedule_type = ?")
        params.append(schedule_type)
    if schedule_value is not None:
        updates.append("schedule_value = ?")
        params.append(schedule_value)
    if enabled is not None:
        updates.append("enabled = ?")
        params.append(1 if enabled else 0)
    if last_run_at is not None:
        updates.append("last_run_at = ?")
        params.append(last_run_at)
    if next_run_at is not None:
        updates.append("next_run_at = ?")
        params.append(next_run_at)

    updates.append("updated_at = ?")
    params.append(datetime.now(timezone.utc).isoformat())
    params.append(routine_id)

    conn.execute(f"UPDATE routines SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    row = conn.execute("SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone()
    if row is None:
        return None
    return _routine_to_dict(row)


def delete_routine(routine_id: str) -> bool:
    """Delete a routine."""
    conn = _get_connection()
    cursor = conn.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
    conn.commit()
    return cursor.rowcount > 0


def _routine_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["enabled"] = bool(d.get("enabled", 1))
    return d
