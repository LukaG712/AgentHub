"""Tests for Obsidian vault integration."""

import os
import tempfile
import shutil
from pathlib import Path

import pytest

from hub import obsidian


@pytest.fixture()
def vault_dir():
    """Create a temporary Obsidian-like vault directory."""
    tmp = tempfile.mkdtemp()
    vault = Path(tmp)
    # Create .obsidian directory to mark it as a valid vault
    (vault / ".obsidian").mkdir()
    yield vault
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def vault(vault_dir):
    """Create an ObsidianVault instance."""
    return obsidian.ObsidianVault(vault_dir)


class TestObsidianVaultInit:
    """Test vault initialization and validation."""

    def test_valid_vault(self, vault, vault_dir):
        assert vault.vault_path == vault_dir.resolve()
        assert vault.enabled is True
        assert vault.is_valid() is True

    def test_invalid_path(self):
        v = obsidian.ObsidianVault(Path("/nonexistent/path"))
        assert v.enabled is False
        assert v.is_valid() is False

    def test_missing_obsidian_dir(self, tmp_path):
        # Directory exists but no .obsidian marker
        v = obsidian.ObsidianVault(tmp_path)
        assert v.enabled is True  # directory exists
        assert v.is_valid() is False  # but not a valid Obsidian vault


class TestObsidianNote:
    """Test ObsidianNote class."""

    def test_note_id_is_url_encoded_path(self, vault):
        note = obsidian.ObsidianNote(
            path=vault.vault_path / "Test Note.md",
            vault_path=vault.vault_path,
        )
        assert note.note_id == "Test%20Note.md"

    def test_note_id_with_subfolder(self, vault):
        (vault.vault_path / "Folder").mkdir()
        note = obsidian.ObsidianNote(
            path=vault.vault_path / "Folder" / "My Note.md",
            vault_path=vault.vault_path,
        )
        assert "Folder" in note.note_id

    def test_to_dict(self, vault):
        note = obsidian.ObsidianNote(
            path=vault.vault_path / "Test.md",
            vault_path=vault.vault_path,
            title="Test",
            tags=["tag1"],
        )
        d = note.to_dict()
        assert d["title"] == "Test"
        assert d["tags"] == ["tag1"]
        assert "id" in d
        assert "path" in d


class TestListNotes:
    """Test note listing and filtering."""

    def test_empty_vault(self, vault):
        notes = vault.list_notes()
        assert notes == []

    def test_list_single_note(self, vault):
        (vault.vault_path / "Test.md").write_text("# Test\n\nContent here")
        notes = vault.list_notes()
        assert len(notes) == 1
        assert notes[0].title == "Test"

    def test_list_multiple_notes(self, vault):
        (vault.vault_path / "Note1.md").write_text("# Note 1")
        (vault.vault_path / "Note2.md").write_text("# Note 2")
        notes = vault.list_notes()
        assert len(notes) == 2

    def test_skip_hidden_files(self, vault):
        (vault.vault_path / ".hidden.md").write_text("# Hidden")
        (vault.vault_path / "Visible.md").write_text("# Visible")
        notes = vault.list_notes()
        assert len(notes) == 1
        assert notes[0].title == "Visible"

    def test_skip_obsidian_folder(self, vault):
        (vault.vault_path / ".obsidian" / "config.md").write_text("# Config")
        (vault.vault_path / "Note.md").write_text("# Note")
        notes = vault.list_notes()
        assert len(notes) == 1

    def test_filter_by_query(self, vault):
        (vault.vault_path / "Alpha.md").write_text("# Alpha\n\nAbout alpha stuff")
        (vault.vault_path / "Beta.md").write_text("# Beta\n\nAbout beta stuff")
        notes = vault.list_notes(query="alpha")
        assert len(notes) == 1
        assert notes[0].title == "Alpha"

    def test_filter_by_tag(self, vault):
        (vault.vault_path / "Tagged.md").write_text("# Tagged\n\n#important tag")
        (vault.vault_path / "Untagged.md").write_text("# Untagged\n\nNo tags here")
        notes = vault.list_notes(tag="important")
        assert len(notes) == 1
        assert notes[0].title == "Tagged"

    def test_filter_by_folder(self, vault):
        (vault.vault_path / "Folder").mkdir()
        (vault.vault_path / "Folder" / "Inside.md").write_text("# Inside")
        (vault.vault_path / "Outside.md").write_text("# Outside")
        notes = vault.list_notes(folder="Folder")
        assert len(notes) == 1
        assert notes[0].title == "Inside"

    def test_limit_results(self, vault):
        for i in range(10):
            (vault.vault_path / f"Note{i}.md").write_text(f"# Note {i}")
        notes = vault.list_notes(limit=5)
        assert len(notes) <= 5

    def test_extract_tags(self, vault):
        (vault.vault_path / "Tags.md").write_text("# Tags\n\n#project #test tags")
        notes = vault.list_notes()
        assert len(notes) == 1
        tags = notes[0].tags
        assert "project" in tags
        assert "test" in tags


class TestGetNote:
    """Test note retrieval by ID."""

    def test_get_existing_note(self, vault):
        (vault.vault_path / "Test.md").write_text("# Test\n\nContent")
        notes = vault.list_notes()
        note_id = notes[0].note_id
        retrieved = vault.get_note(note_id)
        assert retrieved is not None
        assert retrieved.title == "Test"

    def test_get_nonexistent_note(self, vault):
        retrieved = vault.get_note("nonexistent.md")
        assert retrieved is None

    def test_read_note_content(self, vault):
        (vault.vault_path / "Test.md").write_text("# Test\n\nSome content here")
        notes = vault.list_notes()
        note_id = notes[0].note_id
        content = vault.read_note_content(note_id)
        assert content is not None
        assert "Some content here" in content


class TestWriteNote:
    """Test note writing."""

    def test_write_new_note(self, vault):
        note = vault.write_note("TestFolder", "My Note", "# My Note\n\nContent")
        assert note is not None
        assert note.title == "My Note"
        # Verify file exists
        expected = vault.vault_path / "TestFolder" / "My-Note.md"
        assert expected.exists()

    def test_write_note_creates_folder(self, vault):
        note = vault.write_note("New/Nested/Folder", "Note", "# Note")
        assert note is not None
        expected = vault.vault_path / "New" / "Nested" / "Folder" / "Note.md"
        assert expected.exists()

    def test_write_note_special_chars(self, vault):
        note = vault.write_note("Folder", 'Test: Note "with" chars', "# Test")
        assert note is not None
        # Special chars should be removed from filename
        assert ":" not in note.path.name
        assert '"' not in note.path.name

    def test_write_note_disabled_vault(self):
        p = Path(__file__).parent / f"__nonexistent_vault_{os.getpid()}_write__"
        v = obsidian.ObsidianVault(p)
        note = v.write_note("Folder", "Note", "# Note")
        assert note is None

    def test_append_to_existing_note(self, vault):
        # Write initial note
        vault.write_note("Folder", "Note", "# Note\n\nOriginal content")
        # Append
        note = vault.write_note("Folder", "Note", "Appended content", append=True)
        assert note is not None
        content = note.path.read_text()
        assert "Original content" in content
        assert "Appended content" in content


class TestWriteSessionSummary:
    """Test session summary writing."""

    def test_write_session_summary(self, vault):
        messages = [
            {"role": "user", "content": "Hello, agent!"},
            {"role": "assistant", "content": "Hello! How can I help?"},
        ]
        note = vault.write_session_summary("session-123", "Test Session", messages)
        assert note is not None
        content = note.path.read_text()
        assert "session-123" in content
        assert "Hello, agent!" in content
        assert "Hello! How can I help?" in content
        assert obsidian.HUB_MARKER_START in content
        assert obsidian.HUB_MARKER_END in content

    def test_session_summary_includes_date(self, vault):
        messages = [{"role": "user", "content": "Test"}]
        note = vault.write_session_summary("session-123", "Test", messages)
        assert note is not None
        # Filename should start with date
        assert len(note.path.name) > 10  # "YYYY-MM-DD - ..."


class TestSearchNotes:
    """Test note search."""

    def test_search_by_title(self, vault):
        (vault.vault_path / "Project Alpha.md").write_text("# Project Alpha")
        (vault.vault_path / "Project Beta.md").write_text("# Project Beta")
        results = vault.search_notes("Alpha")
        assert len(results) == 1
        assert results[0].title == "Project Alpha"

    def test_search_by_content(self, vault):
        (vault.vault_path / "Notes.md").write_text("# Notes\n\nThis contains important info")
        results = vault.search_notes("important")
        assert len(results) == 1

    def test_search_no_results(self, vault):
        (vault.vault_path / "Note.md").write_text("# Note")
        results = vault.search_notes("nonexistent")
        assert results == []


class TestHelperFunctions:
    """Test helper functions."""

    def test_extract_title_from_content(self):
        title = obsidian._extract_title_from_content("# My Title\n\nContent")
        assert title == "My Title"

    def test_extract_title_no_heading(self):
        title = obsidian._extract_title_from_content("No heading here")
        assert title is None

    def test_extract_tags(self):
        tags = obsidian._extract_tags("#project #test some #tags here")
        assert "project" in tags
        assert "test" in tags
        assert "tags" in tags

    def test_title_to_filename(self):
        filename = obsidian._title_to_filename('My Note: "Test"')
        assert ":" not in filename
        assert '"' not in filename

    def test_title_to_filename_empty(self):
        filename = obsidian._title_to_filename("")
        assert filename == "untitled"

    def test_vault_cache(self):
        obsidian.clear_vault_cache()
        # Test with nonexistent path
        p = Path(__file__).parent / f"__nonexistent_vault_cache_{os.getpid()}__"
        result = obsidian.get_vault(str(p))
        assert result is None


class TestDisabledVault:
    """Test behavior when vault is disabled."""

    def _nonexistent_path(self):
        """Return a path that definitely doesn't exist and can't be created."""
        return Path(__file__).parent / f"__nonexistent_vault_{os.getpid()}__"

    def test_list_notes_disabled(self):
        p = self._nonexistent_path()
        v = obsidian.ObsidianVault(p)
        notes = v.list_notes()
        assert notes == []

    def test_get_note_disabled(self):
        p = self._nonexistent_path()
        v = obsidian.ObsidianVault(p)
        note = v.get_note("any-id")
        assert note is None

    def test_read_note_content_disabled(self):
        p = self._nonexistent_path()
        v = obsidian.ObsidianVault(p)
        content = v.read_note_content("any-id")
        assert content is None

    def test_write_note_disabled(self):
        p = self._nonexistent_path()
        v = obsidian.ObsidianVault(p)
        note = v.write_note("Folder", "Note", "# Note")
        assert note is None

    def test_write_session_summary_disabled(self):
        p = self._nonexistent_path()
        v = obsidian.ObsidianVault(p)
        note = v.write_session_summary("id", "Title", [])
        assert note is None
