"""Custom Droids — specialized subagents with their own prompts, models, and tools.

Inspired by Factory Droid's custom droids, this module allows defining specialized
subagents as Markdown files with their own system prompt, model preference, and
tool policy. Droids are discovered from project and personal directories.

Key concepts:
- Droid: A reusable subagent definition in Markdown format.
- Built-in droids: worker, explorer, reviewer, validator.
- Project droids: Shared with teammates via `.evershade/droids/`.
- Personal droids: Follow you across workspaces.
"""

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

# ─── Models ──────────────────────────────────────────────────────────────────


@dataclass
class DroidDefinition:
    """A custom droid (subagent) definition."""
    name: str = ""
    description: str = ""
    # System prompt for the droid
    system_prompt: str = ""
    # Preferred model for this droid
    model: Optional[str] = None
    # Allowed tools (empty means all tools)
    allowed_tools: list[str] = field(default_factory=list)
    # Denied tools
    denied_tools: list[str] = field(default_factory=list)
    # Whether this droid is built-in
    built_in: bool = False
    # Source file path
    source_path: str = ""
    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DroidDefinition":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# Built-in droids
BUILTIN_DROIDS: dict[str, DroidDefinition] = {
    "worker": DroidDefinition(
        name="worker",
        description="Implementation agent for coding tasks",
        system_prompt=(
            "You are a worker droid. Your job is to implement features and fix bugs. "
            "Follow the project conventions, write clean code, and run tests to verify your changes. "
            "Do not make changes outside the specified scope."
        ),
        built_in=True,
    ),
    "explorer": DroidDefinition(
        name="explorer",
        description="Research agent for repository analysis",
        system_prompt=(
            "You are an explorer droid. Your job is to analyze repositories, "
            "understand their structure, identify relevant files, and produce research findings. "
            "Do not modify any files — you are read-only."
        ),
        built_in=True,
    ),
    "reviewer": DroidDefinition(
        name="reviewer",
        description="Code review agent for quality assurance",
        system_prompt=(
            "You are a reviewer droid. Your job is to review code changes for correctness, "
            "security, performance, and adherence to project conventions. "
            "Provide specific findings with file paths, line numbers, and suggested corrections."
        ),
        built_in=True,
    ),
    "validator": DroidDefinition(
        name="validator",
        description="Validation agent for testing and verification",
        system_prompt=(
            "You are a validator droid. Your job is to run tests, check builds, "
            "and verify that changes meet the validation contract. "
            "Report pass/fail status with evidence for each assertion."
        ),
        built_in=True,
    ),
}


# ─── Discovery ───────────────────────────────────────────────────────────────

# Project-level droids directory
_PROJECT_DROIDS_DIR = Path(".evershade/droids")
# Personal-level droids directory
_PERSONAL_DROIDS_DIR = Path(os.environ.get("EVERSHADE_CONFIG_DIR", "~/.evershade")) / "droids"


def _parse_droid_markdown(content: str, source_path: str = "") -> DroidDefinition:
    """Parse a droid definition from Markdown content.

    Expected format:
    ```
    ---
    name: my-droid
    description: A custom droid for...
    model: gpt-4o
    allowed_tools: [read_file, write_file, run_command]
    denied_tools: [delete_file]
    ---
    System prompt content...
    ```
    """
    # Extract frontmatter
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)

    if frontmatter_match:
        fm_text = frontmatter_match.group(1)
        prompt = frontmatter_match.group(2).strip()

        # Parse frontmatter fields
        name = ""
        description = ""
        model = None
        allowed_tools: list[str] = []
        denied_tools: list[str] = []

        for line in fm_text.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if ":" not in line:
                continue

            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()

            if key == "name":
                name = value
            elif key == "description":
                description = value
            elif key == "model":
                model = value
            elif key == "allowed_tools":
                # Parse inline list
                value = value.strip("[]")
                allowed_tools = [t.strip().strip("'\"") for t in value.split(",") if t.strip()]
            elif key == "denied_tools":
                value = value.strip("[]")
                denied_tools = [t.strip().strip("'\"") for t in value.split(",") if t.strip()]

        return DroidDefinition(
            name=name or Path(source_path).stem,
            description=description,
            system_prompt=prompt,
            model=model,
            allowed_tools=allowed_tools,
            denied_tools=denied_tools,
            source_path=source_path,
        )
    else:
        # No frontmatter — use filename as name, content as prompt
        return DroidDefinition(
            name=Path(source_path).stem,
            system_prompt=content.strip(),
            source_path=source_path,
        )


def discover_droids(project_root: Optional[str] = None) -> list[DroidDefinition]:
    """Discover all available droids.

    Scans project and personal droid directories, plus built-in droids.
    Project droids override personal droids with the same name.

    Args:
        project_root: Optional project root to scan for project droids.

    Returns:
        List of all discovered droid definitions.
    """
    droids: dict[str, DroidDefinition] = {}

    # Add built-in droids
    for name, droid in BUILTIN_DROIDS.items():
        droids[name] = droid

    # Scan personal droids
    personal_dir = Path(_PERSONAL_DROIDS_DIR).expanduser()
    if personal_dir.exists():
        for md_file in personal_dir.glob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                droid = _parse_droid_markdown(content, str(md_file))
                if droid.name and droid.name not in droids:
                    droids[droid.name] = droid
            except Exception:
                continue

    # Scan project droids (override personal)
    if project_root:
        project_dir = Path(project_root) / _PROJECT_DROIDS_DIR
        if project_dir.exists():
            for md_file in project_dir.glob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    droid = _parse_droid_markdown(content, str(md_file))
                    if droid.name:
                        droids[droid.name] = droid
                except Exception:
                    continue

    return list(droids.values())


def get_droid(name: str, project_root: Optional[str] = None) -> Optional[DroidDefinition]:
    """Get a droid by name.

    Args:
        name: Droid name (e.g., "worker", "reviewer").
        project_root: Optional project root for discovery.

    Returns:
        The droid definition or None if not found.
    """
    droids = discover_droids(project_root)
    for droid in droids:
        if droid.name == name:
            return droid
    return None


# ─── Storage ─────────────────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DROIDS_DB_PATH = os.environ.get("GREENIE_DROIDS_DB_PATH", str(_DATA_DIR / "droids.db"))

import sqlite3
import threading

_db_lock = threading.Lock()


def _get_connection() -> sqlite3.Connection:
    """Get a new database connection with WAL mode."""
    db_dir = Path(_DROIDS_DB_PATH).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DROIDS_DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema() -> None:
    """Initialize the droids database schema."""
    conn = _get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS droids (
                name TEXT PRIMARY KEY,
                description TEXT NOT NULL DEFAULT '',
                system_prompt TEXT NOT NULL DEFAULT '',
                model TEXT,
                allowed_tools_json TEXT NOT NULL DEFAULT '[]',
                denied_tools_json TEXT NOT NULL DEFAULT '[]',
                built_in INTEGER NOT NULL DEFAULT 0,
                source_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.commit()
    finally:
        conn.close()


_init_schema()


def _row_to_droid(row: sqlite3.Row) -> DroidDefinition:
    """Convert a database row to a DroidDefinition."""
    return DroidDefinition(
        name=row["name"],
        description=row["description"],
        system_prompt=row["system_prompt"],
        model=row["model"],
        allowed_tools=json.loads(row["allowed_tools_json"]),
        denied_tools=json.loads(row["denied_tools_json"]),
        built_in=bool(row["built_in"]),
        source_path=row["source_path"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def save_droid(droid: DroidDefinition) -> DroidDefinition:
    """Save or update a droid definition."""
    if droid.built_in:
        raise ValueError("Cannot modify built-in droids")

    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO droids
                   (name, description, system_prompt, model, allowed_tools_json,
                    denied_tools_json, built_in, source_path, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    droid.name, droid.description, droid.system_prompt, droid.model,
                    json.dumps(droid.allowed_tools), json.dumps(droid.denied_tools),
                    int(droid.built_in), droid.source_path,
                    droid.created_at, droid.updated_at,
                ),
            )
            conn.commit()
            return droid
        finally:
            conn.close()


def get_stored_droid(name: str) -> Optional[DroidDefinition]:
    """Get a stored droid by name."""
    conn = _get_connection()
    try:
        row = conn.execute("SELECT * FROM droids WHERE name = ?", (name,)).fetchone()
        return _row_to_droid(row) if row else None
    finally:
        conn.close()


def list_stored_droids() -> list[DroidDefinition]:
    """List all stored droid definitions."""
    conn = _get_connection()
    try:
        rows = conn.execute("SELECT * FROM droids ORDER BY name").fetchall()
        return [_row_to_droid(r) for r in rows]
    finally:
        conn.close()


def delete_stored_droid(name: str) -> bool:
    """Delete a stored droid definition."""
    droid = get_stored_droid(name)
    if droid and droid.built_in:
        raise ValueError("Cannot delete built-in droids")

    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.execute("DELETE FROM droids WHERE name = ?", (name,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


# ─── Controller ──────────────────────────────────────────────────────────────


def create_droid(
    name: str,
    description: str,
    system_prompt: str,
    model: Optional[str] = None,
    allowed_tools: Optional[list[str]] = None,
    denied_tools: Optional[list[str]] = None,
) -> DroidDefinition:
    """Create a new custom droid.

    Args:
        name: Unique name for the droid (lowercase, hyphenated).
        description: Short description of the droid's purpose.
        system_prompt: System prompt for the droid.
        model: Optional preferred model.
        allowed_tools: Optional list of allowed tools.
        denied_tools: Optional list of denied tools.

    Returns:
        The created DroidDefinition.
    """
    if not name.strip():
        raise ValueError("name is required")

    # Normalize name
    name = re.sub(r"[^a-z0-9-]", "-", name.lower().strip())

    if not system_prompt.strip():
        raise ValueError("system_prompt is required")

    # Check for conflicts with built-in droids
    if name in BUILTIN_DROIDS:
        raise ValueError(f"Droid name '{name}' conflicts with a built-in droid")

    droid = DroidDefinition(
        name=name,
        description=description.strip(),
        system_prompt=system_prompt.strip(),
        model=model,
        allowed_tools=allowed_tools or [],
        denied_tools=denied_tools or [],
    )
    save_droid(droid)
    return droid


def invoke_droid(
    name: str,
    task: str,
    context: Optional[dict[str, Any]] = None,
    project_root: Optional[str] = None,
) -> dict[str, Any]:
    """Invoke a droid to perform a task.

    This is a placeholder that returns the droid's configuration and task.
    In a full implementation, this would spawn a subagent session.

    Args:
        name: Droid name.
        task: Task description.
        context: Optional additional context.
        project_root: Optional project root for discovery.

    Returns:
        Dict with droid config and task details.
    """
    droid = get_droid(name, project_root)
    if droid is None:
        raise ValueError(f"Droid '{name}' not found")

    return {
        "droid": droid.to_dict(),
        "task": task,
        "context": context or {},
        "status": "invoked",
        "note": "Subagent invocation placeholder — integrate with Slinker or Junie CLI for actual execution",
    }
