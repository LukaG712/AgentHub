"""Optional Obsidian vault integration for reading notes and writing session summaries."""

import hashlib
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Obsidian vault file patterns
OBSIDIAN_VAULT_FILE = ".obsidian"
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mdtxt", ".mdtext", ".text", ".markdn", ".mdwn", ".mkd", ".mkdn"}

# Hub-managed markers for Obsidian-synced notes
HUB_MARKER_START = "<!-- Evershade Valley: managed-section-start -->"
HUB_MARKER_END = "<!-- Evershade Valley: managed-section-end -->"


class ObsidianNote:
    """Represents a note in an Obsidian vault."""

    def __init__(
        self,
        path: Path,
        vault_path: Path,
        title: Optional[str] = None,
        content: Optional[str] = None,
        tags: Optional[List[str]] = None,
        created_at: Optional[str] = None,
        modified_at: Optional[str] = None,
    ):
        self.path = path
        self.vault_path = vault_path
        self.title = title or _extract_title(path)
        self.content = content
        self.tags = tags or []
        self.created_at = created_at
        self.modified_at = modified_at

    @property
    def relative_path(self) -> str:
        """Return the path relative to the vault root."""
        try:
            return str(self.path.relative_to(self.vault_path))
        except ValueError:
            return str(self.path)

    @property
    def note_id(self) -> str:
        """Generate a stable ID from the relative path using URL encoding."""
        return urllib.parse.quote(self.relative_path, safe="")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.note_id,
            "title": self.title,
            "path": self.relative_path,
            "tags": self.tags,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
        }


class ObsidianVault:
    """Read and write operations for an Obsidian vault."""

    def __init__(self, vault_path: Path):
        self.vault_path = Path(vault_path).expanduser().resolve()
        self.enabled = self.vault_path.exists() and self.vault_path.is_dir()

    def is_valid(self) -> bool:
        """Check if the vault path exists and appears to be an Obsidian vault."""
        if not self.vault_path.exists() or not self.vault_path.is_dir():
            return False
        # Check for .obsidian directory (strong indicator)
        obsidian_dir = self.vault_path / ".obsidian"
        return obsidian_dir.exists()

    def list_notes(
        self,
        query: Optional[str] = None,
        tag: Optional[str] = None,
        folder: Optional[str] = None,
        limit: int = 100,
    ) -> List[ObsidianNote]:
        """List Markdown notes in the vault, optionally filtered by query, tag, or folder."""
        if not self.enabled:
            return []

        notes: List[ObsidianNote] = []
        search_paths = self._get_search_paths(folder)

        for path in search_paths:
            if not path.is_file() or path.suffix.lower() not in MARKDOWN_EXTENSIONS:
                continue
            # Skip hidden files and .obsidian folder contents
            if self._should_skip(path):
                continue

            note = self._load_note(path)
            if note is None:
                continue

            # Apply filters
            if query and not self._matches_query(note, query):
                continue
            if tag and tag not in note.tags:
                continue

            notes.append(note)
            if len(notes) >= limit:
                break

        # Sort by modified time, most recent first
        notes.sort(key=lambda n: n.modified_at or "", reverse=True)
        return notes

    def get_note(self, note_id: str) -> Optional[ObsidianNote]:
        """Get a note by its ID (URL-encoded relative path)."""
        if not self.enabled:
            return None

        # Decode the URL-encoded path
        rel_path = urllib.parse.unquote(note_id)
        full_path = self.vault_path / rel_path
        if not full_path.exists():
            return None

        return self._load_note(full_path)

    def read_note_content(self, note_id: str) -> Optional[str]:
        """Read the full content of a note."""
        note = self.get_note(note_id)
        if note is None:
            return None
        if note.content is None:
            try:
                note.content = note.path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return None
        return note.content

    def write_note(
        self,
        folder: str,
        title: str,
        content: str,
        tags: Optional[List[str]] = None,
        append: bool = False,
    ) -> Optional[ObsidianNote]:
        """Write a new note or update an existing one in the vault.

        Args:
            folder: Subfolder within the vault (e.g., "Evershade Valley/Summaries").
            title: Note title (used for filename).
            content: Note content.
            tags: Optional tags to add.
            append: If True and note exists, append content instead of overwriting.

        Returns:
            The created/updated ObsidianNote, or None on failure.
        """
        if not self.vault_path.exists():
            return None

        # Create folder if needed
        folder_path = self.vault_path / folder
        folder_path.mkdir(parents=True, exist_ok=True)

        # Generate filename from title
        filename = _title_to_filename(title) + ".md"
        note_path = folder_path / filename

        # Read existing content if appending
        if append and note_path.exists():
            try:
                existing = note_path.read_text(encoding="utf-8")
                # Avoid duplicate hub-managed sections
                if HUB_MARKER_START in existing:
                    # Replace existing hub section
                    existing = re.sub(
                        re.escape(HUB_MARKER_START) + r".*?" + re.escape(HUB_MARKER_END),
                        "",
                        existing,
                        flags=re.DOTALL,
                    )
                content = existing + "\n\n" + content
            except (OSError, UnicodeDecodeError):
                pass

        # Write content
        try:
            note_path.write_text(content, encoding="utf-8")
        except OSError:
            return None

        return self._load_note(note_path)

    def write_session_summary(
        self,
        session_id: str,
        title: str,
        messages: List[Dict[str, str]],
        folder: str = "Evershade Valley/Sessions",
    ) -> Optional[ObsidianNote]:
        """Write a session summary to the vault.

        Args:
            session_id: Unique session identifier.
            title: Session title.
            messages: List of message dicts with 'role' and 'content' keys.
            folder: Target folder within the vault.

        Returns:
            The created ObsidianNote, or None on failure.
        """
        if not self.vault_path.exists():
            return None

        # Build content
        lines = [f"# {title}", "", f"**Session ID:** {session_id}", ""]

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                lines.append(f"## User\n\n{content}\n")
            elif role == "assistant":
                lines.append(f"## Agent Response\n\n{content}\n")
            elif role == "system":
                lines.append(f"## System\n\n{content}\n")

        # Add hub-managed markers
        content = HUB_MARKER_START + "\n" + "\n".join(lines) + "\n" + HUB_MARKER_END

        # Add date-based title
        now = datetime.now(timezone.utc)
        date_prefix = now.strftime("%Y-%m-%d")
        note_title = f"{date_prefix} - {title}"

        return self.write_note(folder, note_title, content, tags=["Evershade Valley", "session"])

    def search_notes(self, query: str, limit: int = 50) -> List[ObsidianNote]:
        """Search notes by title and content using simple text matching."""
        return self.list_notes(query=query, limit=limit)

    def _get_search_paths(self, folder: Optional[str] = None) -> List[Path]:
        """Get all files to search, optionally filtered by folder."""
        if folder:
            search_root = self.vault_path / folder
            if not search_root.exists():
                return []
            return list(search_root.rglob("*"))
        return list(self.vault_path.rglob("*"))

    def _should_skip(self, path: Path) -> bool:
        """Check if a file should be skipped during note discovery."""
        # Skip .obsidian folder
        try:
            rel = path.relative_to(self.vault_path)
            if rel.parts and rel.parts[0] == ".obsidian":
                return True
        except ValueError:
            pass
        # Skip hidden files
        if path.name.startswith("."):
            return True
        return False

    def _load_note(self, path: Path) -> Optional[ObsidianNote]:
        """Load a note from a file path."""
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        tags = _extract_tags(content)
        title = _extract_title_from_content(content) or _extract_title(path)

        # Get file modification times
        try:
            mtime = path.stat().st_mtime
            modified_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            ctime = path.stat().st_ctime
            created_at = datetime.fromtimestamp(ctime, tz=timezone.utc).isoformat()
        except OSError:
            modified_at = None
            created_at = None

        return ObsidianNote(
            path=path,
            vault_path=self.vault_path,
            title=title,
            content=content,
            tags=tags,
            created_at=created_at,
            modified_at=modified_at,
        )

    def _matches_query(self, note: ObsidianNote, query: str) -> bool:
        """Check if a note matches a search query."""
        query_lower = query.lower()
        if query_lower in note.title.lower():
            return True
        if note.content and query_lower in note.content.lower():
            return True
        for tag in note.tags:
            if query_lower in tag.lower():
                return True
        return False


def _extract_title(path: Path) -> str:
    """Extract a title from a file path."""
    return path.stem


def _extract_title_from_content(content: str) -> Optional[str]:
    """Extract the first H1 heading from Markdown content."""
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return None


def _extract_tags(content: str) -> List[str]:
    """Extract #tags from Markdown content."""
    tags = re.findall(r"#([a-zA-Z0-9_]+)", content)
    return list(set(tags))


def _title_to_filename(title: str) -> str:
    """Convert a title to a safe filename."""
    # Remove invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', "", title)
    # Replace spaces with hyphens
    filename = re.sub(r"\s+", "-", filename)
    # Truncate to 200 chars
    return filename[:200] or "untitled"


# Module-level vault cache with path index
_vault_cache: Dict[str, ObsidianVault] = {}


def get_vault(vault_path: str) -> Optional[ObsidianVault]:
    """Get or create a vault instance for the given path."""
    resolved = str(Path(vault_path).expanduser().resolve())
    if resolved not in _vault_cache:
        vault = ObsidianVault(Path(vault_path))
        if vault.enabled:
            _vault_cache[resolved] = vault
    return _vault_cache.get(resolved)


def clear_vault_cache() -> None:
    """Clear the vault cache (useful for testing)."""
    _vault_cache.clear()
