"""Skills System — reusable SKILL.md workflows.

Inspired by Factory Droid's skills, this module provides reusable workflow
packages. A skill is a directory with a SKILL.md entry point, optional
supporting files, and frontmatter that tells the agent when the workflow applies.

Key concepts:
- Skill: A directory with SKILL.md containing instructions and metadata.
- Model-invoked: Skills are auto-discovered based on task context.
- Composable: Skills can be chained for larger workflows.
- Token-efficient: Lightweight and focused instructions.
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
class SkillDefinition:
    """A skill definition."""
    name: str = ""
    description: str = ""
    # When to invoke this skill (trigger phrases)
    triggers: list[str] = field(default_factory=list)
    # Full instructions
    instructions: str = ""
    # Supporting files
    supporting_files: list[str] = field(default_factory=list)
    # Whether user can invoke directly
    user_invocable: bool = False
    # Source directory
    source_path: str = ""
    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillDefinition":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ─── Discovery ───────────────────────────────────────────────────────────────

_PROJECT_SKILLS_DIR = Path(".evershade/skills")
_PERSONAL_SKILLS_DIR = Path(os.environ.get("EVERSHADE_CONFIG_DIR", "~/.evershade")) / "skills"


def _parse_skill_markdown(content: str, source_dir: str = "") -> SkillDefinition:
    """Parse a SKILL.md file.

    Expected format:
    ```
    ---
    name: my-skill
    description: A skill for...
    triggers: [deploy, release]
    user_invocable: true
    ---
    Instructions...
    ```
    """
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)

    if frontmatter_match:
        fm_text = frontmatter_match.group(1)
        instructions = frontmatter_match.group(2).strip()

        name = ""
        description = ""
        triggers: list[str] = []
        user_invocable = False

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
            elif key == "triggers":
                value = value.strip("[]")
                triggers = [t.strip().strip("'\"") for t in value.split(",") if t.strip()]
            elif key == "user_invocable":
                user_invocable = value.lower() in ("true", "1", "yes")

        return SkillDefinition(
            name=name or Path(source_dir).name,
            description=description,
            triggers=triggers,
            instructions=instructions,
            user_invocable=user_invocable,
            source_path=source_dir,
        )
    else:
        return SkillDefinition(
            name=Path(source_dir).name,
            instructions=content.strip(),
            source_path=source_dir,
        )


def discover_skills(project_root: Optional[str] = None) -> list[SkillDefinition]:
    """Discover all available skills.

    Args:
        project_root: Optional project root to scan for project skills.

    Returns:
        List of all discovered skill definitions.
    """
    skills: dict[str, SkillDefinition] = {}

    # Scan personal skills
    personal_dir = Path(_PERSONAL_SKILLS_DIR).expanduser()
    if personal_dir.exists():
        for skill_dir in personal_dir.iterdir():
            if skill_dir.is_dir():
                skill_md = skill_dir / "SKILL.md"
                if skill_md.exists():
                    try:
                        content = skill_md.read_text(encoding="utf-8")
                        skill = _parse_skill_markdown(content, str(skill_dir))
                        # Collect supporting files
                        supporting = [f.name for f in skill_dir.iterdir() if f.is_file() and f.name != "SKILL.md"]
                        skill.supporting_files = supporting
                        if skill.name and skill.name not in skills:
                            skills[skill.name] = skill
                    except Exception:
                        continue

    # Scan project skills (override personal)
    if project_root:
        project_dir = Path(project_root) / _PROJECT_SKILLS_DIR
        if project_dir.exists():
            for skill_dir in project_dir.iterdir():
                if skill_dir.is_dir():
                    skill_md = skill_dir / "SKILL.md"
                    if skill_md.exists():
                        try:
                            content = skill_md.read_text(encoding="utf-8")
                            skill = _parse_skill_markdown(content, str(skill_dir))
                            supporting = [f.name for f in skill_dir.iterdir() if f.is_file() and f.name != "SKILL.md"]
                            skill.supporting_files = supporting
                            if skill.name:
                                skills[skill.name] = skill
                        except Exception:
                            continue

    return list(skills.values())


def get_skill(name: str, project_root: Optional[str] = None) -> Optional[SkillDefinition]:
    """Get a skill by name."""
    skills = discover_skills(project_root)
    for skill in skills:
        if skill.name == name:
            return skill
    return None


def match_skills(task: str, project_root: Optional[str] = None) -> list[SkillDefinition]:
    """Match skills to a task based on triggers.

    Searches both discovered and stored skills.

    Args:
        task: Task description.
        project_root: Optional project root.

    Returns:
        List of matching skills.
    """
    all_skills = discover_skills(project_root)
    stored = list_stored_skills()
    seen = set()
    for s in all_skills:
        if s.name not in seen:
            all_skills.append(s)
            seen.add(s.name)
    for s in stored:
        if s.name not in seen:
            all_skills.append(s)
            seen.add(s.name)

    task_lower = task.lower()
    matched = []

    for skill in all_skills:
        for trigger in skill.triggers:
            if trigger.lower() in task_lower:
                matched.append(skill)
                break

    return matched


# ─── Storage ─────────────────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_SKILLS_DB_PATH = os.environ.get("GREENIE_SKILLS_DB_PATH", str(_DATA_DIR / "skills.db"))

import sqlite3
import threading

_db_lock = threading.Lock()


def _get_connection() -> sqlite3.Connection:
    """Get a new database connection with WAL mode."""
    db_dir = Path(_SKILLS_DB_PATH).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_SKILLS_DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema() -> None:
    """Initialize the skills database schema."""
    conn = _get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS skills (
                name TEXT PRIMARY KEY,
                description TEXT NOT NULL DEFAULT '',
                triggers_json TEXT NOT NULL DEFAULT '[]',
                instructions TEXT NOT NULL DEFAULT '',
                supporting_files_json TEXT NOT NULL DEFAULT '[]',
                user_invocable INTEGER NOT NULL DEFAULT 0,
                source_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.commit()
    finally:
        conn.close()


with _db_lock:
    _init_schema()


def _row_to_skill(row: sqlite3.Row) -> SkillDefinition:
    """Convert a database row to a SkillDefinition."""
    return SkillDefinition(
        name=row["name"],
        description=row["description"],
        triggers=json.loads(row["triggers_json"]),
        instructions=row["instructions"],
        supporting_files=json.loads(row["supporting_files_json"]),
        user_invocable=bool(row["user_invocable"]),
        source_path=row["source_path"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def save_skill(skill: SkillDefinition) -> SkillDefinition:
    """Save or update a skill definition."""
    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO skills
                   (name, description, triggers_json, instructions, supporting_files_json,
                    user_invocable, source_path, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    skill.name, skill.description, json.dumps(skill.triggers),
                    skill.instructions, json.dumps(skill.supporting_files),
                    int(skill.user_invocable), skill.source_path,
                    skill.created_at, skill.updated_at,
                ),
            )
            conn.commit()
            return skill
        finally:
            conn.close()


def get_stored_skill(name: str) -> Optional[SkillDefinition]:
    """Get a stored skill by name."""
    conn = _get_connection()
    try:
        row = conn.execute("SELECT * FROM skills WHERE name = ?", (name,)).fetchone()
        return _row_to_skill(row) if row else None
    finally:
        conn.close()


def list_stored_skills() -> list[SkillDefinition]:
    """List all stored skill definitions."""
    conn = _get_connection()
    try:
        rows = conn.execute("SELECT * FROM skills ORDER BY name").fetchall()
        return [_row_to_skill(r) for r in rows]
    finally:
        conn.close()


def delete_stored_skill(name: str) -> bool:
    """Delete a stored skill definition."""
    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.execute("DELETE FROM skills WHERE name = ?", (name,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


# ─── Controller ──────────────────────────────────────────────────────────────


def create_skill(
    name: str,
    description: str,
    instructions: str,
    triggers: Optional[list[str]] = None,
    user_invocable: bool = False,
) -> SkillDefinition:
    """Create a new skill.

    Args:
        name: Unique name for the skill.
        description: Short description.
        instructions: Full workflow instructions.
        triggers: Optional trigger phrases.
        user_invocable: Whether users can invoke directly.

    Returns:
        The created SkillDefinition.
    """
    if not name.strip():
        raise ValueError("name is required")

    name = re.sub(r"[^a-z0-9-]", "-", name.lower().strip())

    if not instructions.strip():
        raise ValueError("instructions is required")

    skill = SkillDefinition(
        name=name,
        description=description.strip(),
        triggers=triggers or [],
        instructions=instructions.strip(),
        user_invocable=user_invocable,
    )
    save_skill(skill)
    return skill


def invoke_skill(
    name: str,
    task: str,
    context: Optional[dict[str, Any]] = None,
    project_root: Optional[str] = None,
) -> dict[str, Any]:
    """Invoke a skill for a task.

    Args:
        name: Skill name.
        task: Task description.
        context: Optional additional context.
        project_root: Optional project root.

    Returns:
        Dict with skill instructions and task details.
    """
    skill = get_skill(name, project_root)
    if skill is None:
        # Try stored skills
        skill = get_stored_skill(name)
    if skill is None:
        raise ValueError(f"Skill '{name}' not found")

    return {
        "skill": skill.to_dict(),
        "task": task,
        "context": context or {},
        "status": "invoked",
        "note": "Skill invocation placeholder — integrate with agent execution for actual workflow",
    }
