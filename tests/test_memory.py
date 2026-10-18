"""Tests for hub/memory.py — SQLite persistence layer."""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from hub import memory


@pytest.fixture(autouse=True)
def temp_db():
    """Use a temporary database for each test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_hub.db")
        old = os.environ.get("HUB_DB_PATH")
        os.environ["HUB_DB_PATH"] = db_path
        # Reset thread-local connection
        memory.close_connection()
        yield db_path
        os.environ["HUB_DB_PATH"] = db_path  # keep for teardown
        memory.close_connection()
        if old is not None:
            os.environ["HUB_DB_PATH"] = old
        else:
            os.environ.pop("HUB_DB_PATH", None)


@pytest.fixture(autouse=True)
def reset_connection():
    """Reset the thread-local connection before each test."""
    memory.close_connection()
    yield
    memory.close_connection()


class TestSchemaInit:
    def test_tables_created(self, temp_db):
        """Schema initialization creates all tables."""
        conn = memory._get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row["name"] for row in cursor.fetchall()]
        assert "sessions" in tables
        assert "messages" in tables
        assert "memories" in tables

    def test_indexes_created(self, temp_db):
        """Schema initialization creates indexes."""
        conn = memory._get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )
        indexes = [row["name"] for row in cursor.fetchall()]
        assert len(indexes) >= 5  # We create 6 indexes

    def test_foreign_keys_enabled(self, temp_db):
        """Foreign key enforcement is enabled."""
        conn = memory._get_connection()
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1


class TestSessions:
    def test_create_session(self, temp_db):
        session = memory.create_session(title="Test Session", agent_id="vault")
        assert session["id"] is not None
        assert session["title"] == "Test Session"
        assert session["agent_id"] == "vault"
        assert session["created_at"] is not None
        assert session["updated_at"] is not None

    def test_create_session_defaults(self, temp_db):
        session = memory.create_session()
        assert session["id"] is not None
        assert session["title"] == ""

    def test_get_session(self, temp_db):
        session = memory.create_session(title="Get Test", agent_id="vault")
        fetched = memory.get_session(session["id"])
        assert fetched is not None
        assert fetched["title"] == "Get Test"

    def test_get_missing_session(self, temp_db):
        result = memory.get_session("nonexistent-id")
        assert result is None

    def test_list_sessions(self, temp_db):
        memory.create_session(title="First", agent_id="vault")
        memory.create_session(title="Second", agent_id="vault")
        sessions = memory.list_sessions()
        assert len(sessions) == 2

    def test_list_sessions_filtered_by_agent(self, temp_db):
        memory.create_session(title="A", agent_id="vault")
        memory.create_session(title="B", agent_id="other")
        sessions = memory.list_sessions(agent_id="vault")
        assert len(sessions) == 1
        assert sessions[0]["title"] == "A"

    def test_delete_session(self, temp_db):
        session = memory.create_session(title="To Delete")
        deleted = memory.delete_session(session["id"])
        assert deleted is True
        assert memory.get_session(session["id"]) is None

    def test_delete_missing_session(self, temp_db):
        deleted = memory.delete_session("nonexistent-id")
        assert deleted is False

    def test_delete_session_cascades_messages(self, temp_db):
        session = memory.create_session(title="Cascade Test")
        memory.add_message(session["id"], "user", "Hello")
        memory.add_message(session["id"], "assistant", "Hi there")
        memory.delete_session(session["id"])
        # Messages should be cascade deleted
        conn = memory._get_connection()
        count = conn.execute(
            "SELECT COUNT(*) as c FROM messages WHERE session_id = ?",
            (session["id"],)
        ).fetchone()["c"]
        assert count == 0

    def test_session_timestamps(self, temp_db):
        session = memory.create_session(title="Timestamp Test")
        created = session["created_at"]
        updated = session["updated_at"]
        assert created is not None
        assert updated is not None
        # After adding a message, updated_at should change
        memory.add_message(session["id"], "user", "Test message")
        fetched = memory.get_session(session["id"])
        assert fetched["updated_at"] >= created


class TestMessages:
    def test_add_message(self, temp_db):
        session = memory.create_session(title="Message Test")
        msg = memory.add_message(session["id"], "user", "Hello world")
        assert msg["id"] is not None
        assert msg["session_id"] == session["id"]
        assert msg["role"] == "user"
        assert msg["content"] == "Hello world"

    def test_add_message_with_run_id(self, temp_db):
        session = memory.create_session(title="Run Test")
        msg = memory.add_message(session["id"], "assistant", "Done", run_id="run-123")
        assert msg["run_id"] == "run-123"

    def test_add_message_invalid_role(self, temp_db):
        session = memory.create_session()
        with pytest.raises(ValueError):
            memory.add_message(session["id"], "invalid_role", "test")

    def test_get_session_messages_chronological(self, temp_db):
        session = memory.create_session()
        memory.add_message(session["id"], "user", "First")
        memory.add_message(session["id"], "assistant", "Second")
        memory.add_message(session["id"], "user", "Third")
        messages = memory.get_session_messages(session["id"])
        assert len(messages) == 3
        assert messages[0]["content"] == "First"
        assert messages[1]["content"] == "Second"
        assert messages[2]["content"] == "Third"

    def test_get_session_with_messages(self, temp_db):
        session = memory.create_session(title="Full Test")
        memory.add_message(session["id"], "user", "Hello")
        result = memory.get_session_with_messages(session["id"])
        assert result is not None
        assert result["title"] == "Full Test"
        assert "messages" in result
        assert len(result["messages"]) == 1

    def test_get_session_with_messages_missing(self, temp_db):
        result = memory.get_session_with_messages("nonexistent")
        assert result is None

    def test_messages_empty_for_new_session(self, temp_db):
        session = memory.create_session()
        messages = memory.get_session_messages(session["id"])
        assert messages == []

    def test_last_message_preview(self, temp_db):
        session = memory.create_session(title="Preview Test")
        memory.add_message(session["id"], "user", "Hello world")
        sessions = memory.list_sessions()
        assert len(sessions) == 1
        assert "last_message_preview" in sessions[0]
        assert sessions[0]["last_message_preview"] == "Hello world"


class TestMemories:
    def test_create_memory(self, temp_db):
        mem = memory.create_memory(content="Important fact", agent_id="vault")
        assert mem["id"] is not None
        assert mem["content"] == "Important fact"
        assert mem["agent_id"] == "vault"

    def test_get_memory(self, temp_db):
        mem = memory.create_memory(content="Find me")
        fetched = memory.get_memory(mem["id"])
        assert fetched is not None
        assert fetched["content"] == "Find me"

    def test_get_missing_memory(self, temp_db):
        result = memory.get_memory("nonexistent")
        assert result is None

    def test_list_memories(self, temp_db):
        memory.create_memory(content="First")
        memory.create_memory(content="Second")
        mems = memory.list_memories()
        assert len(mems) == 2

    def test_list_memories_filtered_by_agent(self, temp_db):
        memory.create_memory(content="A", agent_id="vault")
        memory.create_memory(content="B", agent_id="other")
        mems = memory.list_memories(agent_id="vault")
        assert len(mems) == 1
        assert mems[0]["content"] == "A"

    def test_list_memories_filtered_by_project(self, temp_db):
        memory.create_memory(content="A", project_path="/proj/a")
        memory.create_memory(content="B", project_path="/proj/b")
        mems = memory.list_memories(project_path="/proj/a")
        assert len(mems) == 1

    def test_search_memories(self, temp_db):
        memory.create_memory(content="Database connection string")
        memory.create_memory(content="API endpoint design")
        memory.create_memory(content="Database migration plan")
        results = memory.search_memories("Database")
        assert len(results) == 2

    def test_search_memories_no_results(self, temp_db):
        memory.create_memory(content="Something else")
        results = memory.search_memories("nonexistent")
        assert len(results) == 0

    def test_delete_memory(self, temp_db):
        mem = memory.create_memory(content="Delete me")
        deleted = memory.delete_memory(mem["id"])
        assert deleted is True
        assert memory.get_memory(mem["id"]) is None

    def test_delete_missing_memory(self, temp_db):
        deleted = memory.delete_memory("nonexistent")
        assert deleted is False

    def test_update_memory(self, temp_db):
        mem = memory.create_memory(content="Original")
        updated = memory.update_memory(mem["id"], content="Updated")
        assert updated is not None
        assert updated["content"] == "Updated"

    def test_memory_with_tags(self, temp_db):
        mem = memory.create_memory(content="Tagged", tags="important,review")
        assert mem["tags"] == "important,review"
        results = memory.search_memories("important")
        assert len(results) == 1

    def test_memory_with_session(self, temp_db):
        session = memory.create_session()
        mem = memory.create_memory(content="Session memory", session_id=session["id"])
        assert mem["session_id"] == session["id"]


class TestPersistence:
    def test_persistence_across_connections(self, temp_db):
        """Data persists across separate connections."""
        # First connection
        session = memory.create_session(title="Persist Test")
        memory.add_message(session["id"], "user", "Persistent message")
        memory.close_connection()

        # Second connection
        memory.close_connection()
        fetched = memory.get_session(session["id"])
        assert fetched is not None
        assert fetched["title"] == "Persist Test"
        messages = memory.get_session_messages(session["id"])
        assert len(messages) == 1
        assert messages[0]["content"] == "Persistent message"

    def test_database_file_created(self, temp_db):
        """Database file is created at the expected path."""
        memory._get_connection()
        assert Path(temp_db).exists()


class TestProjectDiscovery:
    def test_discover_no_roots(self):
        """Empty result for non-existent roots."""
        results = memory.discover_projects(workspace_roots=["/nonexistent/path"])
        assert results == []

    def test_discover_git_repos(self, tmp_path):
        """Discover git repos in workspace roots."""
        # Create a mock git repo
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        # Create a non-git directory
        other = tmp_path / "not-a-repo"
        other.mkdir()

        results = memory.discover_projects(workspace_roots=[str(tmp_path)])
        assert len(results) == 1
        assert results[0]["name"] == "my-project"
        assert "my-project" in results[0]["path"]

    def test_discover_multiple_repos(self, tmp_path):
        """Discover multiple git repos."""
        (tmp_path / "repo-a" / ".git").mkdir(parents=True)
        (tmp_path / "repo-b" / ".git").mkdir(parents=True)

        results = memory.discover_projects(workspace_roots=[str(tmp_path)])
        names = {r["name"] for r in results}
        assert "repo-a" in names
        assert "repo-b" in names

    def test_discover_no_duplicates(self, tmp_path):
        """Same repo should not appear twice."""
        repo = tmp_path / "unique-repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        results = memory.discover_projects(
            workspace_roots=[str(tmp_path), str(tmp_path)]
        )
        assert len(results) == 1
