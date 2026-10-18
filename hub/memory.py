"""SQLite-based persistence for conversations, sessions, and memories."""

import os
import sqlite3
import threading
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
    """Get a thread-local database connection, creating it if needed."""
    if not hasattr(_local, "conn") or _local.conn is None:
        db_path = _get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn)
        _local.conn = conn
    return _local.conn


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
) -> Dict[str, Any]:
    """Create a new session and return its dict representation."""
    now = datetime.now(timezone.utc).isoformat()
    session_id = str(uuid.uuid4())
    conn = _get_connection()
    conn.execute(
        """INSERT INTO sessions (id, title, project_path, agent_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, title, project_path, agent_id, now, now),
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
) -> Dict[str, Any]:
    """Add a message to a session."""
    if role not in ("user", "assistant", "system", "tool"):
        raise ValueError(f"Invalid role: {role}")
    now = datetime.now(timezone.utc).isoformat()
    message_id = str(uuid.uuid4())
    conn = _get_connection()
    conn.execute(
        """INSERT INTO messages (id, session_id, role, content, run_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (message_id, session_id, role, content, run_id, now),
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
    """
    parts: List[str] = []

    # 1. Recent session messages (last N user/assistant pairs)
    messages = get_session_messages(session_id)
    if messages:
        # Take the last max_messages messages, excluding the most recent user message
        # (which is the current task being dispatched)
        recent = messages[-max_messages:]
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

    # 2. Relevant memories for the agent/project
    # Search by agent_id first, then by project_path, combining results
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
        memories = found_memories
        if memories:
            mem_lines = []
            for mem in memories:
                content = mem["content"]
                tags = mem.get("tags", "")
                tag_str = f" [{tags}]" if tags else ""
                mem_lines.append(f"- {content}{tag_str}")
            parts.append("## Relevant Memories\n\n" + "\n".join(mem_lines))

    # 3. Project guidelines from agent config
    if guidelines:
        parts.append("## Agent Guidelines\n\n" + guidelines)

    # 4. AGENTS.md files found in the project directory
    if project_path:
        agents_md_path = Path(project_path) / ".junie" / "AGENTS.md"
        if agents_md_path.exists():
            try:
                content = agents_md_path.read_text(encoding="utf-8")
                parts.append("## Project Instructions (AGENTS.md)\n\n" + content)
            except (OSError, PermissionError):
                pass
        # Also check for project-level instructions
        for filename in ("AGENTS.md", ".junie/AGENTS.md", "README.md"):
            filepath = Path(project_path) / filename
            if filepath.exists() and filepath != agents_md_path:
                try:
                    content = filepath.read_text(encoding="utf-8")
                    # Truncate README to avoid huge context
                    if filename == "README.md" and len(content) > 4000:
                        content = content[:4000] + "\n... (truncated)"
                    parts.append(f"## Project File ({filename})\n\n" + content)
                except (OSError, PermissionError):
                    pass

    if not parts:
        return ""

    # Build final context string, respecting character limit
    header = "## Context from Previous Sessions\n\n"
    full = header + "\n\n---\n\n".join(parts)

    # Truncate if too long, keeping the header
    if len(full) > max_context_chars:
        truncated = full[:max_context_chars - 100]
        truncated += "\n\n... (context truncated due to length)"
        full = truncated

    return full
