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


class TestContextAssembly:
    def test_empty_context(self, temp_db):
        """No context for empty session."""
        session = memory.create_session(title="Test")
        context = memory.assemble_context(session_id=session["id"])
        assert context == ""

    def test_conversation_history(self, temp_db):
        """Context includes recent messages."""
        session = memory.create_session(title="Test", agent_id="vault")
        memory.add_message(session["id"], "user", "Fix the bug")
        memory.add_message(session["id"], "assistant", "I fixed it.")
        memory.add_message(session["id"], "user", "Great, now add tests")

        context = memory.assemble_context(session_id=session["id"])
        assert "Conversation History" in context
        assert "Fix the bug" in context
        assert "I fixed it." in context

    def test_memories_in_context(self, temp_db):
        """Context includes relevant memories."""
        session = memory.create_session(title="Test", agent_id="vault")
        memory.create_memory(content="Use pytest for testing", agent_id="vault")
        memory.create_memory(content="Project uses FastAPI", agent_id="vault")

        context = memory.assemble_context(session_id=session["id"], agent_id="vault")
        assert "Relevant Memories" in context
        assert "Use pytest for testing" in context
        assert "Project uses FastAPI" in context

    def test_guidelines_in_context(self, temp_db):
        """Context includes agent guidelines."""
        session = memory.create_session(title="Test", agent_id="vault")
        memory.add_message(session["id"], "user", "Hello")

        context = memory.assemble_context(
            session_id=session["id"],
            guidelines="Always write tests first.",
        )
        assert "Agent Guidelines" in context
        assert "Always write tests first." in context

    def test_agents_md_in_context(self, temp_db, tmp_path):
        """Context includes AGENTS.md from project directory."""
        project = tmp_path / "my-project"
        project.mkdir()
        junie_dir = project / ".junie"
        junie_dir.mkdir()
        agents_md = junie_dir / "AGENTS.md"
        agents_md.write_text("Follow PEP 8 style.")

        session = memory.create_session(title="Test", agent_id="vault")
        memory.add_message(session["id"], "user", "Hello")

        context = memory.assemble_context(
            session_id=session["id"],
            project_path=str(project),
        )
        assert "Project Instructions" in context
        assert "Follow PEP 8 style." in context

    def test_readme_in_context(self, temp_db, tmp_path):
        """Context includes README.md from project directory."""
        project = tmp_path / "my-project"
        project.mkdir()
        readme = project / "README.md"
        readme.write_text("# My Project\n\nA sample project.")

        session = memory.create_session(title="Test", agent_id="vault")
        memory.add_message(session["id"], "user", "Hello")

        context = memory.assemble_context(
            session_id=session["id"],
            project_path=str(project),
        )
        assert "README.md" in context
        assert "My Project" in context

    def test_context_truncation(self, temp_db):
        """Context is truncated when too long."""
        session = memory.create_session(title="Test", agent_id="vault")
        # Add a long assistant message (not excluded as current task)
        long_content = "x" * 50000
        memory.add_message(session["id"], "assistant", long_content)
        # Add current user message (will be excluded)
        memory.add_message(session["id"], "user", "Current task")

        context = memory.assemble_context(
            session_id=session["id"],
            max_context_chars=1000,
        )
        assert len(context) <= 1100  # Allow some margin for truncation message
        assert "truncated" in context

    def test_max_messages_limit(self, temp_db):
        """Only last N messages are included."""
        session = memory.create_session(title="Test", agent_id="vault")
        for i in range(30):
            memory.add_message(session["id"], "user", f"Message {i}")
            memory.add_message(session["id"], "assistant", f"Reply {i}")

        context = memory.assemble_context(
            session_id=session["id"],
            max_messages=10,
        )
        # Should include messages 25-29 (last 10 messages = 5 user + 5 assistant pairs)
        assert "Message 29" in context
        # Earlier messages should not be in context
        assert "Message 0" not in context

    def test_max_memories_limit(self, temp_db):
        """Only last N memories are included."""
        session = memory.create_session(title="Test", agent_id="vault")
        for i in range(20):
            memory.create_memory(content=f"Memory {i}", agent_id="vault")

        context = memory.assemble_context(
            session_id=session["id"],
            agent_id="vault",
            max_memories=5,
        )
        # Should include only 5 memories
        assert "Relevant Memories" in context
        mem_count = context.count("- Memory")
        assert mem_count <= 5

    def test_full_context_assembly(self, temp_db, tmp_path):
        """Context combines all sources."""
        project = tmp_path / "my-project"
        project.mkdir()
        junie_dir = project / ".junie"
        junie_dir.mkdir()
        (junie_dir / "AGENTS.md").write_text("Project guidelines here.")

        session = memory.create_session(title="Test", agent_id="vault")
        memory.add_message(session["id"], "user", "Previous question")
        memory.add_message(session["id"], "assistant", "Previous answer")
        memory.create_memory(content="Important decision", agent_id="vault")

        context = memory.assemble_context(
            session_id=session["id"],
            agent_id="vault",
            project_path=str(project),
            guidelines="Agent guidelines",
        )
        assert "Conversation History" in context
        assert "Relevant Memories" in context
        assert "Agent Guidelines" in context
        assert "Project Instructions" in context
        assert "Previous question" in context
        assert "Important decision" in context
        assert "Agent guidelines" in context
        assert "Project guidelines here." in context

    def test_excludes_current_user_message(self, temp_db):
        """The most recent user message (current task) is excluded from context."""
        session = memory.create_session(title="Test", agent_id="vault")
        memory.add_message(session["id"], "user", "Previous question")
        memory.add_message(session["id"], "assistant", "Previous answer")
        # This is the current task — should be excluded
        memory.add_message(session["id"], "user", "Current task")

        context = memory.assemble_context(session_id=session["id"])
        assert "Previous question" in context
        assert "Previous answer" in context
        assert "Current task" not in context

    def test_no_session_returns_empty(self, temp_db):
        """Empty session returns empty context."""
        session = memory.create_session(title="Test", agent_id="vault")
        context = memory.assemble_context(session_id=session["id"])
        assert context == ""

    def test_memory_deduplication(self, temp_db):
        """Memories matching both agent and project are not duplicated."""
        session = memory.create_session(title="Test", agent_id="vault")
        memory.create_memory(
            content="Shared memory",
            agent_id="vault",
            project_path="/tmp/project",
        )
        memory.add_message(session["id"], "user", "Hello")

        context = memory.assemble_context(
            session_id=session["id"],
            agent_id="vault",
            project_path="/tmp/project",
        )
        # Should appear only once
        assert context.count("Shared memory") == 1

    def test_missing_project_files_handled(self, temp_db):
        """Missing project files don't break context assembly."""
        session = memory.create_session(title="Test", agent_id="vault")
        memory.add_message(session["id"], "user", "Previous question")
        memory.add_message(session["id"], "assistant", "Previous answer")
        # Current task — will be excluded
        memory.add_message(session["id"], "user", "Current task")

        context = memory.assemble_context(
            session_id=session["id"],
            project_path="/nonexistent/path",
        )
        # Should not crash — just no project files included
        assert "Conversation History" in context

    def test_messages_ordered_chronologically(self, temp_db):
        """Messages in context are in chronological order."""
        session = memory.create_session(title="Test", agent_id="vault")
        memory.add_message(session["id"], "user", "First")
        memory.add_message(session["id"], "assistant", "Reply first")
        memory.add_message(session["id"], "user", "Second")
        memory.add_message(session["id"], "assistant", "Reply second")
        # Current task — excluded
        memory.add_message(session["id"], "user", "Current")

        context = memory.assemble_context(session_id=session["id"])
        # First should appear before Second
        first_pos = context.index("First")
        second_pos = context.index("Second")
        assert first_pos < second_pos

    def test_no_duplicate_project_files(self, temp_db, tmp_path):
        """AGENTS.md is not included twice when both root and .junie versions exist."""
        project = tmp_path / "my-project"
        project.mkdir()
        junie_dir = project / ".junie"
        junie_dir.mkdir()
        (junie_dir / "AGENTS.md").write_text("Junie guidelines")
        (project / "AGENTS.md").write_text("Root guidelines")

        session = memory.create_session(title="Test", agent_id="vault")
        memory.add_message(session["id"], "user", "Hello")

        context = memory.assemble_context(
            session_id=session["id"],
            project_path=str(project),
        )
        assert "Junie guidelines" in context
        assert "Root guidelines" in context
        # Each should appear once
        assert context.count("Junie guidelines") == 1
        assert context.count("Root guidelines") == 1
