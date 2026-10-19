"""Tests for hub/api.py"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from hub.config import save_config


@pytest.fixture
def client(tmp_path):
    """Set up a temporary hub config for API testing."""
    config_path = tmp_path / "hub.yaml"
    config = {
        "runners": {
            "junie": {
                "command": ["junie", "--task", "{task}", "--project", "{project}"],
                "skills_dir": ".junie/skills",
                "guidelines_file": ".junie/AGENTS.md",
            }
        },
        "agents": {
            "vault": {
                "title": "Vault Librarian",
                "runner": "junie",
                "project_dir": str(tmp_path / "vault-project"),
                "skills": [],
                "guidelines": "Never delete files.",
            }
        },
    }
    save_config(config, config_path)

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    data_dir = tmp_path / "data"
    runs_dir = data_dir / "runs"
    locks_dir = data_dir / "locks"
    runs_dir.mkdir(parents=True)
    locks_dir.mkdir(parents=True)

    # Set up temporary database for memory layer
    db_path = tmp_path / "hub.db"

    old_config = os.environ.get("HUB_CONFIG")
    old_api_key = os.environ.get("HUB_API_KEY")
    old_junie = os.environ.get("JUNIE_BIN")
    old_db = os.environ.get("HUB_DB_PATH")

    os.environ["HUB_CONFIG"] = str(config_path)
    os.environ["HUB_API_KEY"] = "test-secret-key"
    os.environ["JUNIE_BIN"] = str(Path(__file__).parent / "fake_agent.py")
    os.environ["HUB_DB_PATH"] = str(db_path)

    # Reset memory connection to pick up new DB path
    from hub import memory as memory_module
    memory_module.close_connection()

    with patch("hub.runner._RUNS_DIR", runs_dir), \
         patch("hub.runner._LOCKS_DIR", locks_dir), \
         patch("hub.runner._PROJECT_ROOT", tmp_path), \
         patch("hub.skills._SKILLS_DIR", skills_dir):
        from hub import api as api_module
        yield TestClient(api_module.app)

    memory_module.close_connection()
    if old_config is not None:
        os.environ["HUB_CONFIG"] = old_config
    else:
        os.environ.pop("HUB_CONFIG", None)
    if old_api_key is not None:
        os.environ["HUB_API_KEY"] = old_api_key
    else:
        os.environ.pop("HUB_API_KEY", None)
    if old_junie is not None:
        os.environ["JUNIE_BIN"] = old_junie
    else:
        os.environ.pop("JUNIE_BIN", None)
    if old_db is not None:
        os.environ["HUB_DB_PATH"] = old_db
    else:
        os.environ.pop("HUB_DB_PATH", None)


HEADERS = {"Authorization": "Bearer test-secret-key"}


class TestAuth:
    def test_no_auth(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 401

    def test_wrong_auth(self, client):
        resp = client.get("/api/status", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401

    def test_correct_auth(self, client):
        resp = client.get("/api/status", headers=HEADERS)
        assert resp.status_code == 200


class TestStatus:
    def test_status_returns_agents(self, client):
        resp = client.get("/api/status", headers=HEADERS)
        data = resp.json()
        assert "agents" in data
        assert len(data["agents"]) >= 1


class TestAgentsCRUD:
    def test_list_agents(self, client):
        resp = client.get("/api/agents", headers=HEADERS)
        data = resp.json()
        names = [a["name"] for a in data["agents"]]
        assert "vault" in names

    def test_get_agent(self, client):
        resp = client.get("/api/agents/vault", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["name"] == "vault"

    def test_get_nonexistent(self, client):
        resp = client.get("/api/agents/nonexistent", headers=HEADERS)
        assert resp.status_code == 404

    def test_create_agent(self, client):
        resp = client.post(
            "/api/agents/test-agent",
            headers=HEADERS,
            json={"runner": "junie", "project_dir": "/tmp/test"},
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "test-agent"

    def test_create_duplicate(self, client):
        client.post(
            "/api/agents/test-agent",
            headers=HEADERS,
            json={"runner": "junie", "project_dir": "/tmp/test"},
        )
        resp = client.post(
            "/api/agents/test-agent",
            headers=HEADERS,
            json={"runner": "junie", "project_dir": "/tmp/test"},
        )
        assert resp.status_code == 400

    def test_update_agent(self, client):
        resp = client.put(
            "/api/agents/vault",
            headers=HEADERS,
            json={"title": "Updated Title"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Title"

    def test_delete_agent(self, client):
        client.post(
            "/api/agents/to-delete",
            headers=HEADERS,
            json={"runner": "junie", "project_dir": "/tmp"},
        )
        resp = client.delete("/api/agents/to-delete", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["deleted"] == "to-delete"

    def test_runner_commands_protected(self, client):
        """API should not allow changing runner commands."""
        resp = client.put(
            "/api/agents/vault",
            headers=HEADERS,
            json={"command": ["evil", "--hack"]},
        )
        assert resp.status_code == 200
        # Command should not be in the response
        assert "command" not in resp.json()


class TestSkillsCRUD:
    def test_list_skills(self, client):
        resp = client.get("/api/skills", headers=HEADERS)
        assert resp.status_code == 200
        assert "skills" in resp.json()

    def test_create_skill(self, client):
        resp = client.post(
            "/api/skills/test-skill",
            headers=HEADERS,
            json={"description": "A test skill", "content": "# Test\n"},
        )
        assert resp.status_code == 201

    def test_get_skill(self, client):
        client.post(
            "/api/skills/test-skill",
            headers=HEADERS,
            json={"description": "A test skill"},
        )
        resp = client.get("/api/skills/test-skill", headers=HEADERS)
        assert resp.status_code == 200
        assert "content" in resp.json()

    def test_delete_skill(self, client):
        client.post(
            "/api/skills/test-skill",
            headers=HEADERS,
            json={"description": "A test skill"},
        )
        resp = client.delete("/api/skills/test-skill", headers=HEADERS)
        assert resp.status_code == 200


class TestAgentSkills:
    def test_enable_skill(self, client):
        client.post(
            "/api/skills/test-skill",
            headers=HEADERS,
            json={"description": "A test skill"},
        )
        resp = client.post(
            "/api/agents/vault/skills/test-skill",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    def test_disable_skill(self, client):
        client.post(
            "/api/skills/test-skill",
            headers=HEADERS,
            json={"description": "A test skill"},
        )
        client.post("/api/agents/vault/skills/test-skill", headers=HEADERS)
        resp = client.delete(
            "/api/agents/vault/skills/test-skill",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False


class TestRuns:
    def test_list_runs(self, client):
        resp = client.get("/api/runs", headers=HEADERS)
        assert resp.status_code == 200
        assert "runs" in resp.json()

    def test_dispatch_run(self, client):
        resp = client.post(
            "/api/agents/vault/runs",
            headers=HEADERS,
            json={"task": "test task"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["agent"] == "vault"
        assert data["task"] == "test task"

    def test_dispatch_missing_task(self, client):
        resp = client.post(
            "/api/agents/vault/runs",
            headers=HEADERS,
            json={},
        )
        assert resp.status_code == 400

    def test_dispatch_nonexistent_agent(self, client):
        resp = client.post(
            "/api/agents/nonexistent/runs",
            headers=HEADERS,
            json={"task": "test"},
        )
        assert resp.status_code == 404


class TestStaticFiles:
    def test_root_without_auth(self, client):
        """Root should be accessible without auth."""
        resp = client.get("/")
        # Should return something (either the HTML or a JSON message)
        assert resp.status_code in (200, 404)


class TestSessions:
    def test_list_sessions_empty(self, client):
        resp = client.get("/api/sessions", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []

    def test_create_session(self, client):
        resp = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Test Session", "agent_id": "vault"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Test Session"
        assert data["agent_id"] == "vault"
        assert "id" in data

    def test_get_session(self, client):
        # Create session first
        create = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Get Test", "agent_id": "vault"},
        )
        session_id = create.json()["id"]
        resp = client.get(f"/api/sessions/{session_id}", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Get Test"
        assert "messages" in data

    def test_get_missing_session(self, client):
        resp = client.get("/api/sessions/nonexistent-id", headers=HEADERS)
        assert resp.status_code == 404

    def test_delete_session(self, client):
        create = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Delete Test", "agent_id": "vault"},
        )
        session_id = create.json()["id"]
        resp = client.delete(f"/api/sessions/{session_id}", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["deleted"] == session_id
        # Verify it's gone
        resp2 = client.get(f"/api/sessions/{session_id}", headers=HEADERS)
        assert resp2.status_code == 404

    def test_delete_missing_session(self, client):
        resp = client.delete("/api/sessions/nonexistent-id", headers=HEADERS)
        assert resp.status_code == 404

    def test_list_sessions_with_data(self, client):
        client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "First", "agent_id": "vault"},
        )
        client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Second", "agent_id": "vault"},
        )
        resp = client.get("/api/sessions", headers=HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()["sessions"]) == 2

    def test_list_sessions_filtered_by_agent(self, client):
        client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "A", "agent_id": "vault"},
        )
        client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "B", "agent_id": "other"},
        )
        resp = client.get("/api/sessions?agent=vault", headers=HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()["sessions"]) == 1


class TestMessageDispatch:
    def test_dispatch_missing_content(self, client):
        create = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Dispatch Test", "agent_id": "vault"},
        )
        session_id = create.json()["id"]
        resp = client.post(
            f"/api/sessions/{session_id}/messages",
            headers=HEADERS,
            json={},
        )
        assert resp.status_code == 400

    def test_dispatch_missing_session(self, client):
        resp = client.post(
            "/api/sessions/nonexistent-id/messages",
            headers=HEADERS,
            json={"content": "test"},
        )
        assert resp.status_code == 404

    def test_dispatch_no_agent_id(self, client):
        # Create session without agent_id
        create = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "No Agent"},
        )
        session_id = create.json()["id"]
        resp = client.post(
            f"/api/sessions/{session_id}/messages",
            headers=HEADERS,
            json={"content": "test"},
        )
        assert resp.status_code == 400

    def test_dispatch_missing_agent(self, client):
        create = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Bad Agent", "agent_id": "nonexistent-agent"},
        )
        session_id = create.json()["id"]
        resp = client.post(
            f"/api/sessions/{session_id}/messages",
            headers=HEADERS,
            json={"content": "test"},
        )
        assert resp.status_code == 404


class TestMemories:
    def test_list_memories_empty(self, client):
        resp = client.get("/api/memories", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["memories"] == []

    def test_create_memory(self, client):
        resp = client.post(
            "/api/memories",
            headers=HEADERS,
            json={"content": "Important fact"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["content"] == "Important fact"
        assert "id" in data

    def test_create_memory_missing_content(self, client):
        resp = client.post(
            "/api/memories",
            headers=HEADERS,
            json={},
        )
        assert resp.status_code == 400

    def test_search_memories(self, client):
        client.post(
            "/api/memories",
            headers=HEADERS,
            json={"content": "Database connection"},
        )
        client.post(
            "/api/memories",
            headers=HEADERS,
            json={"content": "API design"},
        )
        resp = client.get("/api/memories?q=Database", headers=HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()["memories"]) == 1

    def test_delete_memory(self, client):
        create = client.post(
            "/api/memories",
            headers=HEADERS,
            json={"content": "Delete me"},
        )
        memory_id = create.json()["id"]
        resp = client.delete(f"/api/memories/{memory_id}", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["deleted"] == memory_id

    def test_delete_missing_memory(self, client):
        resp = client.delete("/api/memories/nonexistent-id", headers=HEADERS)
        assert resp.status_code == 404

    def test_update_memory_content(self, client):
        create = client.post(
            "/api/memories",
            headers=HEADERS,
            json={"content": "Original content"},
        )
        memory_id = create.json()["id"]
        resp = client.put(
            f"/api/memories/{memory_id}",
            headers=HEADERS,
            json={"content": "Updated content"},
        )
        assert resp.status_code == 200
        assert resp.json()["content"] == "Updated content"

    def test_update_missing_memory(self, client):
        resp = client.put(
            "/api/memories/nonexistent-id",
            headers=HEADERS,
            json={"content": "Updated"},
        )
        assert resp.status_code == 404


class TestProjects:
    def test_list_projects(self, client):
        resp = client.get("/api/projects", headers=HEADERS)
        assert resp.status_code == 200
        assert "projects" in resp.json()


class TestProviders:
    def test_list_providers(self, client):
        resp = client.get("/api/providers", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
        # Junie should be registered by default
        names = [p["name"] for p in data["providers"]]
        assert "junie" in names

    def test_provider_has_available_field(self, client):
        resp = client.get("/api/providers", headers=HEADERS)
        data = resp.json()
        for provider in data["providers"]:
            assert "name" in provider
            assert "available" in provider


class TestStatusValidation:
    def test_status_includes_providers(self, client):
        resp = client.get("/api/status", headers=HEADERS)
        data = resp.json()
        assert "providers" in data
        assert "issues" in data
        assert "healthy" in data

    def test_status_healthy_with_available_provider(self, client):
        resp = client.get("/api/status", headers=HEADERS)
        data = resp.json()
        # Should be healthy since no error-level issues
        assert data["healthy"] is True


class TestPermissions:
    def test_agent_list_includes_permissions(self, client):
        """Agents with permissions in config should show them."""
        resp = client.get("/api/agents", headers=HEADERS)
        data = resp.json()
        # The vault agent in the fixture doesn't have permissions set,
        # so it won't appear in the response
        for agent in data["agents"]:
            if "permissions" in agent:
                assert isinstance(agent["permissions"], dict)

    def test_create_agent_with_permissions(self, client):
        """Create an agent with permissions."""
        resp = client.post(
            "/api/agents/test-perms",
            headers=HEADERS,
            json={
                "runner": "junie",
                "project_dir": "/tmp/test",
                "permissions": {
                    "file_read": True,
                    "file_write": False,
                    "command_exec": True,
                    "git_ops": True,
                    "network": False,
                },
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["permissions"]["file_write"] is False
        assert data["permissions"]["network"] is False

    def test_update_agent_permissions(self, client):
        """Update agent permissions."""
        # Create agent first
        client.post(
            "/api/agents/test-perms-update",
            headers=HEADERS,
            json={
                "runner": "junie",
                "project_dir": "/tmp/test",
            },
        )
        # Update permissions
        resp = client.put(
            "/api/agents/test-perms-update",
            headers=HEADERS,
            json={
                "permissions": {
                    "file_read": True,
                    "file_write": False,
                    "command_exec": True,
                    "git_ops": False,
                    "network": True,
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["permissions"]["file_write"] is False
        assert data["permissions"]["git_ops"] is False


class TestSSE:
    def test_stream_missing_session(self, client):
        resp = client.get("/api/sessions/nonexistent-id/stream", headers=HEADERS)
        assert resp.status_code == 404

    def test_stream_idle_session(self, client):
        # Create session without any runs
        create = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Idle Test", "agent_id": "vault"},
        )
        session_id = create.json()["id"]
        resp = client.get(f"/api/sessions/{session_id}/stream", headers=HEADERS)
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        # Should contain idle event
        text = resp.text
        assert "event:" in text


class TestObsidian:
    def test_obsidian_status_not_configured(self, client):
        """Obsidian status should return enabled=false when not configured."""
        resp = client.get("/api/obsidian/status", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False

    def test_obsidian_notes_not_configured(self, client):
        """Listing notes should fail when Obsidian is not configured."""
        resp = client.get("/api/obsidian/notes", headers=HEADERS)
        assert resp.status_code == 400

    def test_obsidian_get_note_not_configured(self, client):
        """Getting a note should fail when Obsidian is not configured."""
        resp = client.get("/api/obsidian/notes/some-note", headers=HEADERS)
        assert resp.status_code == 400

    def test_obsidian_sync_not_configured(self, client):
        """Sync should fail when Obsidian is not configured."""
        resp = client.post(
            "/api/obsidian/sync",
            headers=HEADERS,
            json={"session_id": "some-session"},
        )
        assert resp.status_code == 400

    def test_obsidian_sync_missing_session_id(self, client):
        """Sync should fail without session_id even if configured."""
        resp = client.post(
            "/api/obsidian/sync",
            headers=HEADERS,
            json={},
        )
        # Will fail with 400 (not configured) or 400 (missing session_id)
        assert resp.status_code == 400

    def test_obsidian_sync_missing_session(self, client):
        """Sync should return 404 for nonexistent session."""
        resp = client.post(
            "/api/obsidian/sync",
            headers=HEADERS,
            json={"session_id": "nonexistent-session-id"},
        )
        assert resp.status_code in (400, 404)


class TestSSEStreaming:
    def test_sse_buffer_bounded(self, client):
        """Test that SSE buffer has bounded size."""
        from hub.api import _SSE_MAX_EVENTS
        assert _SSE_MAX_EVENTS == 1000

    def test_sse_send_event_bounded_retention(self, client):
        """Test that _sse_send_event evicts oldest events when buffer is full."""
        from hub.api import _sse_send_event, _sse_remove_buffer, _SSE_MAX_EVENTS, \
            _sse_event_store, _sse_event_store_lock
        run_id = "test-full-buffer"
        # Temporarily lower the max for testing
        old_max = _SSE_MAX_EVENTS
        import hub.api as api_mod
        api_mod._SSE_MAX_EVENTS = 3
        try:
            _sse_send_event(run_id, "output", '{"text": "line1"}')
            _sse_send_event(run_id, "output", '{"text": "line2"}')
            _sse_send_event(run_id, "output", '{"text": "line3"}')
            # Buffer is full — next event should evict the oldest
            _sse_send_event(run_id, "output", '{"text": "line4"}')
            with _sse_event_store_lock:
                store = _sse_event_store.get(run_id)
            assert store is not None
            assert len(store.events) == 3
            # Oldest event should be evicted
            evicted_strings = [ev_str for _, ev_str in store.events]
            assert "line1" not in evicted_strings[0]
            # Eviction should be tracked
            assert store.evicted_before_id is not None
        finally:
            api_mod._SSE_MAX_EVENTS = old_max
            _sse_remove_buffer(run_id)

    def test_sse_terminal_event_never_dropped(self, client):
        """Test that terminal events (complete, error, end) are never silently dropped."""
        from hub.api import _sse_send_event, _sse_remove_buffer, \
            _sse_event_store, _sse_event_store_lock
        import hub.api as api_mod
        run_id = "test-terminal"
        old_max = api_mod._SSE_MAX_EVENTS
        api_mod._SSE_MAX_EVENTS = 3
        try:
            # Fill the buffer with non-terminal events
            _sse_send_event(run_id, "output", '{"text": "line1"}')
            _sse_send_event(run_id, "output", '{"text": "line2"}')
            _sse_send_event(run_id, "output", '{"text": "line3"}')
            # Terminal event must be delivered even though buffer is full
            _sse_send_event(run_id, "complete", '{"state": "done"}')
            with _sse_event_store_lock:
                store = _sse_event_store.get(run_id)
            # The complete event must be present
            assert store is not None
            ev_strings = [ev_str for _, ev_str in store.events]
            found_complete = any("event: complete" in ev for ev in ev_strings)
            assert found_complete, "Terminal event was silently dropped"
        finally:
            api_mod._SSE_MAX_EVENTS = old_max
            _sse_remove_buffer(run_id)

    def test_sse_buffer_cleanup(self, client):
        """Test that SSE buffer is cleaned up after run ends."""
        from hub.api import _sse_event_store, _sse_event_store_lock, _sse_remove_buffer
        run_id = "test-cleanup"
        from hub.api import _sse_buffer_for_run
        buf = _sse_buffer_for_run(run_id)
        with _sse_event_store_lock:
            assert run_id in _sse_event_store
        _sse_remove_buffer(run_id)
        with _sse_event_store_lock:
            assert run_id not in _sse_event_store

    def test_sse_multi_client_independent(self, client):
        """Test that multiple SSE clients each receive the full event stream."""
        from hub.api import _sse_send_event, _sse_remove_buffer, \
            _sse_event_store, _sse_event_store_lock
        run_id = "test-multi-client"
        try:
            # Simulate events being sent
            _sse_send_event(run_id, "start", '{"state": "working"}')
            _sse_send_event(run_id, "output", '{"text": "line1"}')
            _sse_send_event(run_id, "output", '{"text": "line2"}')
            _sse_send_event(run_id, "complete", '{"state": "done"}')
            _sse_send_event(run_id, "end", "")
            # Both "clients" read the full store independently
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            assert s is not None
            # Client 1 reads all events by scanning event IDs
            client1_events = [ev_str for _, ev_str in s.events]
            assert len(client1_events) == 5
            assert "event: start" in client1_events[0]
            assert "event: complete" in client1_events[3]
            assert "event: end" in client1_events[4]
            # Client 2 reads the same full list (not consumed by client 1)
            with _sse_event_store_lock:
                s2 = _sse_event_store.get(run_id)
            client2_events = [ev_str for _, ev_str in s2.events]
            assert len(client2_events) == 5
        finally:
            _sse_remove_buffer(run_id)

    def test_sse_auth_via_query_param(self, client):
        """Test that SSE endpoint accepts token via query parameter."""
        create = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Auth Test", "agent_id": "vault"},
        )
        session_id = create.json()["id"]
        # Connect using query param instead of header
        resp = client.get(
            f"/api/sessions/{session_id}/stream?token=test-secret-key",
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_sse_auth_rejects_bad_token(self, client):
        """Test that SSE endpoint rejects invalid query token."""
        create = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Bad Auth Test", "agent_id": "vault"},
        )
        session_id = create.json()["id"]
        resp = client.get(
            f"/api/sessions/{session_id}/stream?token=wrong-token",
        )
        assert resp.status_code == 401

    def test_sse_dispatch_returns_run_id_immediately(self, client):
        """Test that dispatch returns run_id without waiting for the run to finish."""
        create = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Dispatch Test", "agent_id": "vault"},
        )
        session_id = create.json()["id"]
        resp = client.post(
            f"/api/sessions/{session_id}/messages",
            headers=HEADERS,
            json={"content": "quick task"},
        )
        data = resp.json()
        assert data["status"] == "queued"
        assert "run_id" in data
        assert data["run_id"] is not None

    def test_sse_stream_emits_start_event(self, client):
        """Test that the SSE stream emits a start event for a new run."""
        create = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Start Event Test", "agent_id": "vault"},
        )
        session_id = create.json()["id"]
        # Dispatch a message
        dispatch = client.post(
            f"/api/sessions/{session_id}/messages",
            headers=HEADERS,
            json={"content": "start event task"},
        )
        run_id = dispatch.json()["run_id"]
        # Wait for the run to complete (fake_agent is fast)
        import time
        time.sleep(2)
        # Connect to the stream — run should be done, so we get the final state
        resp = client.get(
            f"/api/sessions/{session_id}/stream?token=test-secret-key",
        )
        assert resp.status_code == 200
        text = resp.text
        # Should contain either complete or end event
        assert "event:" in text

    def test_sse_completed_run_replay(self, client):
        """Test that connecting to a finished run replays the final state."""
        create = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Replay Test", "agent_id": "vault"},
        )
        session_id = create.json()["id"]
        # Dispatch and wait for completion
        client.post(
            f"/api/sessions/{session_id}/messages",
            headers=HEADERS,
            json={"content": "replay task"},
        )
        import time
        time.sleep(2)
        # Connect after run is done
        resp = client.get(
            f"/api/sessions/{session_id}/stream?token=test-secret-key",
        )
        assert resp.status_code == 200
        text = resp.text
        # Should contain complete event with answer
        assert "event: complete" in text or "event: end" in text

    def test_sse_concurrent_runs_isolated(self, client):
        """Test that two concurrent runs do not mix their SSE events."""
        # Create two sessions
        s1 = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Concurrent 1", "agent_id": "vault"},
        ).json()["id"]
        s2 = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Concurrent 2", "agent_id": "vault"},
        ).json()["id"]
        # Dispatch both
        d1 = client.post(
            f"/api/sessions/{s1}/messages",
            headers=HEADERS,
            json={"content": "session one task"},
        ).json()
        d2 = client.post(
            f"/api/sessions/{s2}/messages",
            headers=HEADERS,
            json={"content": "session two task"},
        ).json()
        run_id_1 = d1["run_id"]
        run_id_2 = d2["run_id"]
        assert run_id_1 != run_id_2, "Run IDs must be different"
        # Wait for both to complete
        import time
        time.sleep(3)
        # Stream session 1 — should only contain run_id_1
        resp1 = client.get(
            f"/api/sessions/{s1}/stream?token=test-secret-key",
        )
        text1 = resp1.text
        assert run_id_1 in text1
        # Stream session 2 — should only contain run_id_2
        resp2 = client.get(
            f"/api/sessions/{s2}/stream?token=test-secret-key",
        )
        text2 = resp2.text
        assert run_id_2 in text2
        # Events should not cross
        assert run_id_2 not in text1
        assert run_id_1 not in text2

    def test_sse_failed_run_replay(self, client):
        """Test that connecting to a failed run replays the error state."""
        from hub.config import load_config
        config = load_config()
        config["runners"]["junie"]["command"] = [
            "junie", "--task", "{task}", "--project", "{project}", "--fail"
        ]
        save_config(config, Path(os.environ.get("HUB_CONFIG", "")))
        create = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Failed Replay Test", "agent_id": "vault"},
        )
        session_id = create.json()["id"]
        client.post(
            f"/api/sessions/{session_id}/messages",
            headers=HEADERS,
            json={"content": "fail task"},
        )
        import time
        time.sleep(2)
        resp = client.get(
            f"/api/sessions/{session_id}/stream?token=test-secret-key",
        )
        assert resp.status_code == 200
        text = resp.text
        assert "event: error" in text or "event: end" in text

    def test_sse_stream_specific_run_id(self, client):
        """Test streaming a specific run_id via query parameter."""
        create = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Run ID Test", "agent_id": "vault"},
        )
        session_id = create.json()["id"]
        # Dispatch and get run_id
        dispatch = client.post(
            f"/api/sessions/{session_id}/messages",
            headers=HEADERS,
            json={"content": "specific run task"},
        )
        run_id = dispatch.json()["run_id"]
        import time
        time.sleep(2)
        # Stream using specific run_id
        resp = client.get(
            f"/api/sessions/{session_id}/stream?token=test-secret-key&run_id={run_id}",
        )
        assert resp.status_code == 200
        text = resp.text
        assert run_id in text

    def test_sse_stream_invalid_run_id(self, client):
        """Test streaming a non-existent run_id returns 404."""
        create = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Invalid Run Test", "agent_id": "vault"},
        )
        session_id = create.json()["id"]
        resp = client.get(
            f"/api/sessions/{session_id}/stream?token=test-secret-key&run_id=nonexistent-run-id",
        )
        assert resp.status_code == 404

    def test_sse_overlapping_runs_same_session(self, client):
        """Test that two runs in the same session keep their events separate."""
        create = client.post(
            "/api/sessions",
            headers=HEADERS,
            json={"title": "Overlapping Test", "agent_id": "vault"},
        )
        session_id = create.json()["id"]
        # First run
        d1 = client.post(
            f"/api/sessions/{session_id}/messages",
            headers=HEADERS,
            json={"content": "first overlapping task"},
        ).json()
        run_id_1 = d1["run_id"]
        import time
        time.sleep(2)
        # Second run in the same session
        d2 = client.post(
            f"/api/sessions/{session_id}/messages",
            headers=HEADERS,
            json={"content": "second overlapping task"},
        ).json()
        run_id_2 = d2["run_id"]
        time.sleep(2)
        # Stream run 1 specifically
        resp1 = client.get(
            f"/api/sessions/{session_id}/stream?token=test-secret-key&run_id={run_id_1}",
        )
        text1 = resp1.text
        assert run_id_1 in text1
        assert run_id_2 not in text1
        # Stream run 2 specifically
        resp2 = client.get(
            f"/api/sessions/{session_id}/stream?token=test-secret-key&run_id={run_id_2}",
        )
        text2 = resp2.text
        assert run_id_2 in text2
        assert run_id_1 not in text2
        # Default stream (no run_id) should return the latest run
        resp_default = client.get(
            f"/api/sessions/{session_id}/stream?token=test-secret-key",
        )
        text_default = resp_default.text
        assert run_id_2 in text_default

    def test_sse_event_ids_monotonic(self, client):
        """Test that event IDs are monotonically increasing within a run."""
        from hub.api import _sse_send_event, _sse_remove_buffer, \
            _sse_event_store, _sse_event_store_lock
        run_id = "test-monotonic-ids"
        try:
            for i in range(10):
                _sse_send_event(run_id, "output", f'{{"text": "line{i}"}}')
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            assert s is not None
            ids = [ev_id for ev_id, _ in s.events]
            # IDs should be strictly increasing
            for i in range(1, len(ids)):
                assert ids[i] > ids[i - 1], f"Event IDs not monotonic: {ids}"
        finally:
            _sse_remove_buffer(run_id)

    def test_sse_cursor_survives_eviction(self, client):
        """Test that event ID cursors remain valid after events are evicted."""
        from hub.api import _sse_send_event, _sse_remove_buffer, _SSE_MAX_EVENTS, \
            _sse_event_store, _sse_event_store_lock
        import hub.api as api_mod
        run_id = "test-cursor-eviction"
        old_max = api_mod._SSE_MAX_EVENTS
        api_mod._SSE_MAX_EVENTS = 3
        try:
            # Fill buffer
            _sse_send_event(run_id, "output", '{"text": "a"}')
            _sse_send_event(run_id, "output", '{"text": "b"}')
            _sse_send_event(run_id, "output", '{"text": "c"}')
            # Client reads up to event ID of "b"
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            assert s is not None
            # Find the ID of the second event ("b")
            client_last_id = s.events[1][0]
            # Now send more events, causing eviction
            _sse_send_event(run_id, "output", '{"text": "d"}')
            _sse_send_event(run_id, "output", '{"text": "e"}')
            _sse_send_event(run_id, "output", '{"text": "f"}')
            # Client resumes from last_id — should only get events after client_last_id
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            new_events = [ev_str for ev_id, ev_str in s.events if ev_id > client_last_id]
            # Should get some new events, not duplicates of old ones
            assert len(new_events) > 0
            # Should not contain "a" which was evicted
            for ev in new_events:
                assert '{"text": "a"}' not in ev
        finally:
            api_mod._SSE_MAX_EVENTS = old_max
            _sse_remove_buffer(run_id)

    def test_sse_retention_gap_notification(self, client):
        """Test that evicted_before_id is set when events are evicted."""
        from hub.api import _sse_send_event, _sse_remove_buffer, _SSE_MAX_EVENTS, \
            _sse_event_store, _sse_event_store_lock
        import hub.api as api_mod
        run_id = "test-retention-gap"
        old_max = api_mod._SSE_MAX_EVENTS
        api_mod._SSE_MAX_EVENTS = 3
        try:
            # No eviction yet
            _sse_send_event(run_id, "output", '{"text": "a"}')
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            assert s.evicted_before_id is None
            # Fill and overflow
            _sse_send_event(run_id, "output", '{"text": "b"}')
            _sse_send_event(run_id, "output", '{"text": "c"}')
            _sse_send_event(run_id, "output", '{"text": "d"}')  # evicts "a"
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            # Should track that events were evicted
            assert s.evicted_before_id is not None
        finally:
            api_mod._SSE_MAX_EVENTS = old_max
            _sse_remove_buffer(run_id)

    def test_sse_terminal_recovery_after_overflow(self, client):
        """Test that terminal state is recoverable even after many evictions."""
        from hub.api import _sse_send_event, _sse_remove_buffer, _SSE_MAX_EVENTS, \
            _sse_event_store, _sse_event_store_lock
        import hub.api as api_mod
        run_id = "test-terminal-recovery"
        old_max = api_mod._SSE_MAX_EVENTS
        api_mod._SSE_MAX_EVENTS = 3
        try:
            # Fill with non-terminal events
            for i in range(10):
                _sse_send_event(run_id, "output", f'{{"text": "line{i}"}}')
            # Send terminal event — must survive
            _sse_send_event(run_id, "complete", '{"state": "done"}')
            _sse_send_event(run_id, "end", "")
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            assert s is not None
            ev_strings = [ev_str for _, ev_str in s.events]
            # Terminal events must be present
            assert any("event: complete" in ev for ev in ev_strings), \
                "Complete event lost after overflow"
            assert any("event: end" in ev for ev in ev_strings), \
                "End event lost after overflow"
        finally:
            api_mod._SSE_MAX_EVENTS = old_max
            _sse_remove_buffer(run_id)

    def test_sse_reconnect_after_eviction(self, client):
        """Test that a reconnecting client sees retention gap and remaining events."""
        from hub.api import _sse_send_event, _sse_remove_buffer, _SSE_MAX_EVENTS, \
            _sse_event_store, _sse_event_store_lock
        import hub.api as api_mod
        run_id = "test-reconnect"
        old_max = api_mod._SSE_MAX_EVENTS
        api_mod._SSE_MAX_EVENTS = 4
        try:
            # Client connects, reads first 3 events
            _sse_send_event(run_id, "start", '{"state": "working"}')
            _sse_send_event(run_id, "output", '{"text": "line1"}')
            _sse_send_event(run_id, "output", '{"text": "line2"}')
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            assert s is not None
            client_last_id = s.events[-1][0]
            # Disconnect, then many more events cause eviction
            for i in range(10):
                _sse_send_event(run_id, "output", f'{{"text": "late{i}"}}')
            _sse_send_event(run_id, "complete", '{"state": "done"}')
            _sse_send_event(run_id, "end", "")
            # Client reconnects — should see retention gap and remaining events
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            # Retention gap should be recorded
            assert s.evicted_before_id is not None
            # Remaining events after client's cursor
            remaining = [ev_str for ev_id, ev_str in s.events if ev_id > client_last_id]
            # Should have some events, including terminal
            assert any("event: complete" in ev for ev in remaining), \
                "Terminal event not in remaining events after reconnect"
        finally:
            api_mod._SSE_MAX_EVENTS = old_max
            _sse_remove_buffer(run_id)

    def test_sse_multiple_clients_different_positions(self, client):
        """Test two clients at different cursor positions each get correct events."""
        from hub.api import _sse_send_event, _sse_remove_buffer, _SSE_MAX_EVENTS, \
            _sse_event_store, _sse_event_store_lock
        import hub.api as api_mod
        run_id = "test-diff-positions"
        old_max = api_mod._SSE_MAX_EVENTS
        api_mod._SSE_MAX_EVENTS = 5
        try:
            # Send 3 events
            _sse_send_event(run_id, "output", '{"text": "a"}')
            _sse_send_event(run_id, "output", '{"text": "b"}')
            _sse_send_event(run_id, "output", '{"text": "c"}')
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            assert s is not None
            # Client 1 is at event 1, Client 2 is at event 2
            client1_last = s.events[0][0]
            client2_last = s.events[1][0]
            # Send more events
            _sse_send_event(run_id, "output", '{"text": "d"}')
            _sse_send_event(run_id, "output", '{"text": "e"}')
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            # Client 1 gets events after its cursor
            c1_new = [ev_str for ev_id, ev_str in s.events if ev_id > client1_last]
            # Client 2 gets events after its cursor (fewer)
            c2_new = [ev_str for ev_id, ev_str in s.events if ev_id > client2_last]
            assert len(c1_new) > len(c2_new), \
                "Client behind should receive more events than client ahead"
            assert len(c2_new) >= 1, "Client 2 should still get new events"
        finally:
            api_mod._SSE_MAX_EVENTS = old_max
            _sse_remove_buffer(run_id)

    def test_sse_client_behind_evicted_event(self, client):
        """Test a client at cursor 0 when event 1 has already been evicted."""
        from hub.api import _sse_send_event, _sse_remove_buffer, _SSE_MAX_EVENTS, \
            _sse_event_store, _sse_event_store_lock
        import hub.api as api_mod
        run_id = "test-behind-evicted"
        old_max = api_mod._SSE_MAX_EVENTS
        api_mod._SSE_MAX_EVENTS = 3
        try:
            # Fill buffer with events 1, 2, 3
            _sse_send_event(run_id, "output", '{"text": "a"}')
            _sse_send_event(run_id, "output", '{"text": "b"}')
            _sse_send_event(run_id, "output", '{"text": "c"}')
            # Record event 1's ID
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            assert s is not None
            event1_id = s.events[0][0]
            # Overflow so event 1 is evicted
            _sse_send_event(run_id, "output", '{"text": "d"}')
            _sse_send_event(run_id, "output", '{"text": "e"}')
            # Client at cursor 0 should detect retention gap
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            # evicted_before_id should be > 0 (some event was evicted)
            assert s.evicted_before_id is not None
            assert s.evicted_before_id >= event1_id
            # A client with last_event_id=0 is behind the evicted history
            last_event_id = 0
            has_gap = (
                s.evicted_before_id is not None
                and s.evicted_before_id > last_event_id
            )
            assert has_gap, "Client at cursor 0 should detect retention gap"
        finally:
            api_mod._SSE_MAX_EVENTS = old_max
            _sse_remove_buffer(run_id)

    def test_sse_continued_overflow_updates_highest_evicted(self, client):
        """Test that continued buffer overflow updates the highest evicted ID correctly."""
        from hub.api import _sse_send_event, _sse_remove_buffer, _SSE_MAX_EVENTS, \
            _sse_event_store, _sse_event_store_lock
        import hub.api as api_mod
        run_id = "test-continued-overflow"
        old_max = api_mod._SSE_MAX_EVENTS
        api_mod._SSE_MAX_EVENTS = 3
        try:
            # Fill buffer
            _sse_send_event(run_id, "output", '{"text": "a"}')
            _sse_send_event(run_id, "output", '{"text": "b"}')
            _sse_send_event(run_id, "output", '{"text": "c"}')
            first_evicted_id = None
            # First overflow — evicts "a"
            _sse_send_event(run_id, "output", '{"text": "d"}')
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            first_evicted_id = s.evicted_before_id
            assert first_evicted_id is not None
            # Second overflow — evicts "b" (higher ID than "a")
            _sse_send_event(run_id, "output", '{"text": "e"}')
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            # evicted_before_id should have increased to the higher evicted ID
            assert s.evicted_before_id > first_evicted_id, \
                f"Expected evicted_before_id to increase, got {s.evicted_before_id} vs {first_evicted_id}"
            # Third overflow
            _sse_send_event(run_id, "output", '{"text": "f"}')
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            # Should continue increasing
            assert s.evicted_before_id > first_evicted_id
        finally:
            api_mod._SSE_MAX_EVENTS = old_max
            _sse_remove_buffer(run_id)

    def test_sse_cursor_advances_from_snapshot(self, client):
        """Test that new events arriving while a client consumes a snapshot are not skipped.

        Simulates the cursor race: client snapshots events, new events arrive,
        client advances cursor from snapshot IDs (not from the store), then
        fetches again — should get the events that arrived in between.
        """
        from hub.api import _sse_send_event, _sse_remove_buffer, _SSE_MAX_EVENTS, \
            _sse_event_store, _sse_event_store_lock
        import hub.api as api_mod
        run_id = "test-cursor-snapshot"
        old_max = api_mod._SSE_MAX_EVENTS
        api_mod._SSE_MAX_EVENTS = 100
        try:
            # Initial events
            _sse_send_event(run_id, "output", '{"text": "a"}')
            _sse_send_event(run_id, "output", '{"text": "b"}')
            # Client snapshots events after cursor 0
            last_event_id = 0
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            assert s is not None
            snapshot = [
                (ev_id, ev_str)
                for ev_id, ev_str in s.events
                if ev_id > last_event_id
            ]
            # New events arrive while client processes snapshot
            _sse_send_event(run_id, "output", '{"text": "c"}')
            _sse_send_event(run_id, "output", '{"text": "d"}')
            # Client advances cursor from snapshot IDs (not from store)
            last_event_id = snapshot[-1][0]
            # Client fetches again — should get c and d, not skip them
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            new_events = [
                ev_str for ev_id, ev_str in s.events
                if ev_id > last_event_id
            ]
            assert len(new_events) == 2, \
                f"Expected 2 new events (c, d), got {len(new_events)}"
            assert '{"text": "c"}' in new_events[0]
            assert '{"text": "d"}' in new_events[1]
        finally:
            api_mod._SSE_MAX_EVENTS = old_max
            _sse_remove_buffer(run_id)

    def test_sse_lock_not_held_during_yield(self, client):
        """Test that the event-store lock is not held while a client is suspended.

        Verifies the lock can be acquired by a producer while a consumer
        would be suspended (simulated by checking lock state).
        """
        from hub.api import _sse_send_event, _sse_remove_buffer, _SSE_MAX_EVENTS, \
            _sse_event_store, _sse_event_store_lock
        import hub.api as api_mod
        import threading
        run_id = "test-lock-not-held"
        old_max = api_mod._SSE_MAX_EVENTS
        api_mod._SSE_MAX_EVENTS = 100
        try:
            # Send initial event
            _sse_send_event(run_id, "output", '{"text": "start"}')
            # Verify the lock is not held after _sse_send_event returns
            # (it should be released since the with block exited)
            acquired = _sse_event_store_lock.acquire(blocking=False)
            assert acquired, "Lock should not be held after _sse_send_event returns"
            _sse_event_store_lock.release()
            # Send more events to confirm normal operation
            _sse_send_event(run_id, "output", '{"text": "middle"}')
            _sse_send_event(run_id, "output", '{"text": "end"}')
            with _sse_event_store_lock:
                s = _sse_event_store.get(run_id)
            assert s is not None
            assert len(s.events) == 3
        finally:
            api_mod._SSE_MAX_EVENTS = old_max
            _sse_remove_buffer(run_id)


class TestRemote:
    def test_remote_status(self, client):
        """Remote status should return SSH availability and targets."""
        resp = client.get("/api/remote/status", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "ssh_available" in data
        assert "targets" in data
        assert isinstance(data["targets"], list)
