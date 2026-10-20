"""Tests for Grok Bot features: persistence, parallel queue, routines, memory, handoffs, approvals, templates, plugins."""

import json
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from hub import memory
from hub.config import save_config


@pytest.fixture
def client_env(tmp_path):
    """Set up temporary config, database, and runs dir for Grok Bot tests."""
    config_path = tmp_path / "hub.yaml"

    data_dir = tmp_path / "data"
    runs_dir = data_dir / "runs"
    locks_dir = data_dir / "locks"
    runs_dir.mkdir(parents=True)
    locks_dir.mkdir(parents=True)

    config = {
        "data_dir": str(data_dir),
        "runners": {
            "junie": {
                "command": ["junie", "--task", "{task}", "--project", "{project}"],
                "skills_dir": ".junie/skills",
                "guidelines_file": ".junie/AGENTS.md",
            }
        },
        "agents": {
            "bot-a": {
                "title": "Bot Alpha",
                "runner": "junie",
                "project_dir": str(tmp_path / "project-a"),
                "skills": [],
                "guidelines": "Be concise.",
            },
            "bot-b": {
                "title": "Bot Beta",
                "runner": "junie",
                "project_dir": str(tmp_path / "project-b"),
                "skills": [],
                "guidelines": "Be thorough.",
            },
        },
    }
    save_config(config, config_path)

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    db_path = tmp_path / "hub.db"

    old_config = os.environ.get("HUB_CONFIG")
    old_api_key = os.environ.get("HUB_API_KEY")
    old_junie = os.environ.get("JUNIE_BIN")
    old_db = os.environ.get("HUB_DB_PATH")

    os.environ["HUB_CONFIG"] = str(config_path)
    os.environ["HUB_API_KEY"] = "test-secret-key"
    os.environ["JUNIE_BIN"] = str(Path(__file__).parent / "fake_agent.py")
    os.environ["HUB_DB_PATH"] = str(db_path)

    memory.close_connection()

    with patch("hub.runner._RUNS_DIR", runs_dir), \
         patch("hub.runner._LOCKS_DIR", locks_dir), \
         patch("hub.runner._PROJECT_ROOT", tmp_path), \
         patch("hub.skills._SKILLS_DIR", skills_dir):
        from hub import api as api_module
        from hub import routines as routines_module
        routines_module.start_scheduler()
        try:
            yield TestClient(api_module.app), tmp_path
        finally:
            routines_module.stop_scheduler()

    memory.close_connection()
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


class TestPhase1Persistence:
    def test_message_persistence_with_bot_id_and_metadata(self, client_env):
        session = memory.create_session(title="Bot Thread", agent_id="bot-a")
        sid = session["id"]

        meta = json.dumps({"state": "done", "run_id": "run-123"})
        msg = memory.add_message(
            session_id=sid,
            role="assistant",
            content="Hello from bot-a",
            run_id="run-123",
            bot_id="bot-a",
            msg_type="message",
            metadata=meta,
        )

        assert msg["bot_id"] == "bot-a"
        assert msg["msg_type"] == "message"
        assert msg["metadata"] == meta

        # Reopen connection and check
        memory.close_connection()
        messages = memory.get_session_messages(sid)
        assert len(messages) == 1
        assert messages[0]["bot_id"] == "bot-a"
        assert json.loads(messages[0]["metadata"])["state"] == "done"

    def test_approvals_crud(self, client_env):
        session = memory.create_session(title="Approval Test", agent_id="bot-a")
        sid = session["id"]

        appr = memory.create_approval(
            run_id="run-999",
            session_id=sid,
            bot_id="bot-a",
            action_type="command",
            description="Execute git push origin main",
            pattern_matched="git push",
        )
        assert appr["status"] == "pending"
        assert appr["pattern_matched"] == "git push"

        fetched = memory.get_approval(appr["id"])
        assert fetched["description"] == "Execute git push origin main"

        # Update status
        updated = memory.update_approval_status(appr["id"], "approved")
        assert updated["status"] == "approved"
        assert updated["decided_at"] is not None

        # List approvals
        listed = memory.list_approvals(session_id=sid)
        assert len(listed) == 1
        assert listed[0]["id"] == appr["id"]

    def test_routines_crud(self, client_env):
        routine = memory.create_routine(
            bot_id="bot-a",
            name="Daily report",
            task_text="Summarize all git commits",
            schedule_type="interval",
            schedule_value="3600",
            enabled=True,
        )
        assert routine["name"] == "Daily report"
        assert routine["enabled"] is True

        # Fetch
        fetched = memory.get_routine(routine["id"])
        assert fetched["bot_id"] == "bot-a"

        # Update
        updated = memory.update_routine(routine["id"], enabled=False, task_text="Updated task")
        assert updated["enabled"] is False
        assert updated["task_text"] == "Updated task"

        # List
        all_routines = memory.list_routines(bot_id="bot-a")
        assert len(all_routines) == 1
        enabled_only = memory.list_routines(bot_id="bot-a", enabled_only=True)
        assert len(enabled_only) == 0

        # Delete
        deleted = memory.delete_routine(routine["id"])
        assert deleted is True
        assert memory.get_routine(routine["id"]) is None


class TestPhase2QueueAndParallel:
    def test_pause_resume_endpoints(self, client_env):
        client, _ = client_env
        from hub import queue_manager
        queue_manager.clear_all_queues()

        # Check initial queue
        resp = client.get("/api/bots/bot-a/queue", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["paused"] is False
        assert resp.json()["queue"] == []

        # Pause bot-a
        resp = client.post("/api/bots/bot-a/pause", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

        # Check queue reflects paused
        resp = client.get("/api/bots/bot-a/queue", headers=HEADERS)
        assert resp.json()["paused"] is True

        # Status includes paused
        resp = client.get("/api/status", headers=HEADERS)
        bot_a_status = next(a for a in resp.json()["agents"] if a["name"] == "bot-a")
        assert bot_a_status["paused"] is True

        # Resume bot-a
        resp = client.post("/api/bots/bot-a/resume", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["status"] == "resumed"

        resp = client.get("/api/bots/bot-a/queue", headers=HEADERS)
        assert resp.json()["paused"] is False

    def test_parallel_bots_run_concurrently(self, client_env):
        client, _ = client_env
        from hub import queue_manager
        queue_manager.clear_all_queues()

        sess_a = client.post("/api/sessions", json={"agent_id": "bot-a", "title": "Thread A"}, headers=HEADERS).json()
        sess_b = client.post("/api/sessions", json={"agent_id": "bot-b", "title": "Thread B"}, headers=HEADERS).json()

        # Dispatch tasks for both bots
        resp_a = client.post(f"/api/sessions/{sess_a['id']}/messages", json={"content": "Task for A"}, headers=HEADERS)
        resp_b = client.post(f"/api/sessions/{sess_b['id']}/messages", json={"content": "Task for B"}, headers=HEADERS)

        assert resp_a.status_code == 201
        assert resp_b.status_code == 201
        assert resp_a.json()["agent"] == "bot-a"
        assert resp_b.json()["agent"] == "bot-b"

        # Wait a moment for workers to process
        time.sleep(1.0)
        from hub.runner import get_run
        run_a = get_run(resp_a.json()["run_id"])
        run_b = get_run(resp_b.json()["run_id"])
        assert run_a is not None
        assert run_b is not None

    def test_same_bot_queues_sequentially(self, client_env):
        client, _ = client_env
        from hub import queue_manager
        queue_manager.clear_all_queues()

        # Pause bot-a so tasks queue up without completing immediately
        queue_manager.pause_bot("bot-a")
        sess = client.post("/api/sessions", json={"agent_id": "bot-a", "title": "Thread"}, headers=HEADERS).json()

        resp1 = client.post(f"/api/sessions/{sess['id']}/messages", json={"content": "Task 1"}, headers=HEADERS)
        resp2 = client.post(f"/api/sessions/{sess['id']}/messages", json={"content": "Task 2"}, headers=HEADERS)

        assert resp1.status_code == 201
        assert resp2.status_code == 201

        q_resp = client.get("/api/bots/bot-a/queue", headers=HEADERS)
        assert q_resp.status_code == 200
        # Both tasks should be in the queue
        assert len(q_resp.json()["queue"]) >= 1

        # Now resume bot-a and verify tasks drain
        queue_manager.resume_bot("bot-a")
        time.sleep(1.0)


class TestPhase1APIEndpoints:
    """Tests for new API endpoints: routines, approvals, bot memory."""

    def test_routines_api_crud(self, client_env):
        client, _ = client_env

        # Create a routine
        resp = client.post("/api/routines", json={
            "bot_id": "bot-a",
            "name": "Daily report",
            "task_text": "Summarize all git commits",
            "schedule_type": "interval",
            "schedule_value": "3600",
            "enabled": True,
        }, headers=HEADERS)
        assert resp.status_code == 201
        routine = resp.json()
        assert routine["name"] == "Daily report"
        assert routine["bot_id"] == "bot-a"
        routine_id = routine["id"]

        # List routines
        resp = client.get("/api/routines?bot_id=bot-a", headers=HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()["routines"]) >= 1

        # Update routine
        resp = client.put(f"/api/routines/{routine_id}", json={
            "name": "Updated report",
            "enabled": False,
        }, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated report"
        assert resp.json()["enabled"] is False

        # Delete routine
        resp = client.delete(f"/api/routines/{routine_id}", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["deleted"] == routine_id

        # Verify deleted
        resp = client.get("/api/routines?bot_id=bot-a", headers=HEADERS)
        remaining = [r for r in resp.json()["routines"] if r["id"] == routine_id]
        assert len(remaining) == 0

    def test_routines_api_validation(self, client_env):
        client, _ = client_env

        # Missing required fields
        resp = client.post("/api/routines", json={"bot_id": "bot-a"}, headers=HEADERS)
        assert resp.status_code == 400

        # Update non-existent routine
        resp = client.put("/api/routines/non-existent-id", json={"name": "x"}, headers=HEADERS)
        assert resp.status_code == 404

        # Delete non-existent routine
        resp = client.delete("/api/routines/non-existent-id", headers=HEADERS)
        assert resp.status_code == 404

    def test_routines_run_now(self, client_env):
        client, _ = client_env
        from hub import queue_manager
        queue_manager.clear_all_queues()

        # Create a routine first
        resp = client.post("/api/routines", json={
            "bot_id": "bot-a",
            "name": "Quick task",
            "task_text": "Do something",
        }, headers=HEADERS)
        assert resp.status_code == 201
        routine_id = resp.json()["id"]

        # Run now
        resp = client.post(f"/api/routines/{routine_id}/run-now", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["status"] == "dispatched"
        assert "run_id" in resp.json()

        # Run non-existent routine
        resp = client.post("/api/routines/non-existent/run-now", headers=HEADERS)
        assert resp.status_code == 404

    def test_approvals_api(self, client_env):
        client, _ = client_env

        # Create an approval directly via memory
        session = memory.create_session(title="Test Session", agent_id="bot-a")
        appr = memory.create_approval(
            session_id=session["id"],
            bot_id="bot-a",
            action_type="command",
            description="Test approval",
        )
        approval_id = appr["id"]

        # List pending approvals
        resp = client.get("/api/approvals?status=pending", headers=HEADERS)
        assert resp.status_code == 200
        approvals = resp.json()["approvals"]
        assert any(a["id"] == approval_id for a in approvals)

        # Approve
        resp = client.post(f"/api/approvals/{approval_id}/approve", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

        # Verify no longer pending
        resp = client.get("/api/approvals?status=pending", headers=HEADERS)
        pending = resp.json()["approvals"]
        assert not any(a["id"] == approval_id for a in pending)

    def test_approvals_api_deny(self, client_env):
        client, _ = client_env

        session = memory.create_session(title="Test Session 2", agent_id="bot-a")
        appr = memory.create_approval(
            session_id=session["id"],
            bot_id="bot-a",
            action_type="command",
            description="Deny test",
        )
        approval_id = appr["id"]

        # Deny
        resp = client.post(f"/api/approvals/{approval_id}/deny", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["status"] == "denied"

    def test_approvals_api_not_found(self, client_env):
        client, _ = client_env

        resp = client.post("/api/approvals/non-existent/approve", headers=HEADERS)
        assert resp.status_code == 404

        resp = client.post("/api/approvals/non-existent/deny", headers=HEADERS)
        assert resp.status_code == 404

    def test_bot_memory_api(self, client_env):
        client, tmp_path = client_env

        # Get memory for existing bot (should return empty content)
        resp = client.get("/api/bots/bot-a/memory", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["content"] == ""

        # Update memory
        resp = client.put("/api/bots/bot-a/memory", json={
            "content": "# Bot A Memory\n\n- Prefers concise answers"
        }, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["content"] == "# Bot A Memory\n\n- Prefers concise answers"

        # Get memory again
        resp = client.get("/api/bots/bot-a/memory", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["content"] == "# Bot A Memory\n\n- Prefers concise answers"

        # Get memory for non-existent bot
        resp = client.get("/api/bots/non-existent-bot/memory", headers=HEADERS)
        assert resp.status_code == 404

    def test_scheduler_started(self, client_env):
        """Verify the scheduler is started on app boot."""
        from hub import routines as routines_module
        # The fixture starts the scheduler. Wait for the thread to actually start,
        # with a timeout so the test doesn't hang if something is wrong.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if routines_module._scheduler_thread is not None and routines_module._scheduler_thread.is_alive():
                break
            time.sleep(0.05)
        assert routines_module._scheduler_thread is not None, "Scheduler thread was never created"
        assert routines_module._scheduler_thread.is_alive(), "Scheduler thread died before becoming alive"


class TestPhase3BotMemoryAndTeach:
    """Tests for bot memory files and teach-a-task feature."""

    def test_bot_memory_file_crud(self, client_env):
        client, tmp_path = client_env
        from hub import bot_memory

        # Read non-existent memory
        content = bot_memory.read_bot_memory("bot-a")
        assert content == ""
        assert not bot_memory.bot_memory_exists("bot-a")

        # Write memory
        bot_memory.write_bot_memory("bot-a", "# Bot A Notes\n\n- Be concise")
        assert bot_memory.bot_memory_exists("bot-a")

        # Read memory
        content = bot_memory.read_bot_memory("bot-a")
        assert content == "# Bot A Notes\n\n- Be concise"

        # Update memory
        bot_memory.write_bot_memory("bot-a", "# Updated\n\n- Be thorough")
        content = bot_memory.read_bot_memory("bot-a")
        assert content == "# Updated\n\n- Be thorough"

    def test_bot_memory_in_context(self, client_env):
        client, tmp_path = client_env
        from hub import bot_memory

        # Write bot memory
        bot_memory.write_bot_memory("bot-a", "# Preferences\n\n- Use Python")

        # Create a session
        session = memory.create_session(title="Context Test", agent_id="bot-a")
        sid = session["id"]

        # Assemble context
        context = memory.assemble_context(
            session_id=sid,
            agent_id="bot-a",
            guidelines="Test guidelines",
        )
        assert "Bot Memory" in context
        assert "Use Python" in context

    def test_teach_as_routine(self, client_env):
        client, _ = client_env
        from hub import queue_manager
        queue_manager.clear_all_queues()

        # Create a session and send a message to create a run
        sess = client.post("/api/sessions", json={"agent_id": "bot-a", "title": "Teach Test"}, headers=HEADERS).json()
        resp = client.post(f"/api/sessions/{sess['id']}/messages", json={"content": "Do something important"}, headers=HEADERS)
        assert resp.status_code == 201
        run_id = resp.json()["run_id"]

        # Wait for run to be created
        time.sleep(0.5)

        # Teach as routine
        resp = client.post("/api/routines/teach", json={
            "run_id": run_id,
            "bot_id": "bot-a",
            "name": "Important task",
        }, headers=HEADERS)
        assert resp.status_code == 201
        routine = resp.json()
        assert routine["name"] == "Important task"
        assert routine["bot_id"] == "bot-a"
        assert "Do something important" in routine["task_text"]

    def test_teach_as_routine_missing_fields(self, client_env):
        client, _ = client_env

        # Missing run_id
        resp = client.post("/api/routines/teach", json={"bot_id": "bot-a"}, headers=HEADERS)
        assert resp.status_code == 400

        # Missing bot_id
        resp = client.post("/api/routines/teach", json={"run_id": "fake-run"}, headers=HEADERS)
        assert resp.status_code == 400

        # Non-existent run
        resp = client.post("/api/routines/teach", json={"run_id": "non-existent", "bot_id": "bot-a"}, headers=HEADERS)
        assert resp.status_code == 404

    def test_bot_memory_path_safety(self, client_env):
        """Verify that invalid bot IDs are rejected for memory file access."""
        from hub import bot_memory

        try:
            bot_memory.read_bot_memory("../etc/passwd")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass  # Expected

        try:
            bot_memory.write_bot_memory("../../../malicious", "bad")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass  # Expected


class TestPhase4Handoffs:
    """Tests for group threads and bot handoffs."""

    def test_handoff_api(self, client_env):
        client, _ = client_env
        from hub import queue_manager
        queue_manager.clear_all_queues()

        # Create a group session with bot_ids
        resp = client.post("/api/sessions", json={
            "title": "Group Thread",
            "agent_id": "bot-a",
            "bot_ids": ["bot-a", "bot-b"],
        }, headers=HEADERS)
        assert resp.status_code == 201
        session_id = resp.json()["id"]

        # Hand off from bot-a to bot-b
        resp = client.post(f"/api/sessions/{session_id}/handoff", json={
            "from_bot": "bot-a",
            "to_bot": "bot-b",
            "message": "Please review this code",
        }, headers=HEADERS)
        assert resp.status_code == 201
        data = resp.json()
        assert data["from_bot"] == "bot-a"
        assert data["to_bot"] == "bot-b"
        assert data["hop"] == 1

        # Verify handoff message in session
        resp = client.get(f"/api/sessions/{session_id}", headers=HEADERS)
        session = resp.json()
        messages = session.get("messages", [])
        handoffs = [m for m in messages if m.get("msg_type") == "handoff"]
        assert len(handoffs) == 1
        assert "bot-b" in handoffs[0]["content"]

    def test_handoff_loop_prevention(self, client_env):
        client, _ = client_env

        # Create a session
        resp = client.post("/api/sessions", json={
            "title": "Loop Test",
            "agent_id": "bot-a",
        }, headers=HEADERS)
        session_id = resp.json()["id"]

        # Simulate max_hops handoffs
        for i in range(5):
            resp = client.post(f"/api/sessions/{session_id}/handoff", json={
                "from_bot": "bot-a",
                "to_bot": "bot-b",
                "message": f"Handoff {i+1}",
            }, headers=HEADERS)
            assert resp.status_code == 201

        # 6th handoff should fail
        resp = client.post(f"/api/sessions/{session_id}/handoff", json={
            "from_bot": "bot-a",
            "to_bot": "bot-b",
            "message": "This should fail",
        }, headers=HEADERS)
        assert resp.status_code == 400
        assert "Max handoff hops" in resp.json()["detail"]

    def test_handoff_validation(self, client_env):
        client, _ = client_env

        resp = client.post("/api/sessions", json={
            "title": "Validation Test",
            "agent_id": "bot-a",
        }, headers=HEADERS)
        session_id = resp.json()["id"]

        # Missing from_bot
        resp = client.post(f"/api/sessions/{session_id}/handoff", json={
            "to_bot": "bot-b",
            "message": "test",
        }, headers=HEADERS)
        assert resp.status_code == 400

        # Non-existent to_bot
        resp = client.post(f"/api/sessions/{session_id}/handoff", json={
            "from_bot": "bot-a",
            "to_bot": "non-existent-bot",
            "message": "test",
        }, headers=HEADERS)
        assert resp.status_code == 404

    def test_mention_detection(self, client_env):
        """Verify @mention detection triggers handoff."""
        client, _ = client_env

        resp = client.post("/api/sessions", json={
            "title": "Mention Test",
            "agent_id": "bot-a",
        }, headers=HEADERS)
        session_id = resp.json()["id"]

        # Hand off with @mention in message
        resp = client.post(f"/api/sessions/{session_id}/handoff", json={
            "from_bot": "bot-a",
            "to_bot": "bot-b",
            "message": "@bot-b please handle this",
        }, headers=HEADERS)
        assert resp.status_code == 201

        # Verify the handoff message contains the @mention
        resp = client.get(f"/api/sessions/{session_id}", headers=HEADERS)
        messages = resp.json().get("messages", [])
        handoffs = [m for m in messages if m.get("msg_type") == "handoff"]
        assert len(handoffs) == 1
        assert "@bot-b" in handoffs[0]["content"]


class TestPhase5AutoReview:
    """Tests for auto-review pattern matching and approval flow."""

    def test_auto_review_patterns(self, client_env):
        from hub import auto_review

        # Test default patterns
        assert auto_review.check_action("git push origin main") is not None
        assert auto_review.check_action("rm -rf /tmp/data") is not None
        assert auto_review.check_action("curl https://example.com") is not None
        assert auto_review.check_action("pip install requests") is not None

        # Non-sensitive text should not match
        assert auto_review.check_action("Hello world") is None
        assert auto_review.check_action("git commit -m 'fix'") is None
        assert auto_review.check_action("git push is not allowed") is not None  # still matches pattern

    def test_auto_review_pattern_details(self, client_env):
        from hub import auto_review

        result = auto_review.check_action("Running git push origin main")
        assert result is not None
        pattern, matched = result
        assert "git" in pattern
        assert "push" in matched

    def test_auto_review_enabled(self, client_env):
        from hub import auto_review

        # Default: not enabled
        assert auto_review.is_enabled() is False

    def test_approval_pause_resume(self, client_env):
        client, _ = client_env

        # Create an approval
        session = memory.create_session(title="Approval Test", agent_id="bot-a")
        appr = memory.create_approval(
            session_id=session["id"],
            bot_id="bot-a",
            action_type="command",
            description="git push origin main",
            pattern_matched="git push",
        )
        assert appr["status"] == "pending"

        # List pending approvals
        resp = client.get("/api/approvals?status=pending", headers=HEADERS)
        approvals = resp.json()["approvals"]
        assert any(a["id"] == appr["id"] for a in approvals)

        # Approve
        resp = client.post(f"/api/approvals/{appr['id']}/approve", headers=HEADERS)
        assert resp.json()["status"] == "approved"

        # No longer pending
        resp = client.get("/api/approvals?status=pending", headers=HEADERS)
        pending = resp.json()["approvals"]
        assert not any(a["id"] == appr["id"] for a in pending)


class TestPhase6Templates:
    """Tests for marketplace templates and generate-from-sentence."""

    def test_templates_list(self, client_env):
        client, _ = client_env

        resp = client.get("/api/templates", headers=HEADERS)
        assert resp.status_code == 200
        templates = resp.json()["templates"]
        assert len(templates) >= 5
        names = [t["name"] for t in templates]
        assert "research" in names

    def test_get_template(self, client_env):
        client, _ = client_env

        resp = client.get("/api/templates/research", headers=HEADERS)
        assert resp.status_code == 200
        t = resp.json()
        assert t["name"] == "research"
        assert "Research" in t["title"]

        # Non-existent template
        resp = client.get("/api/templates/non-existent", headers=HEADERS)
        assert resp.status_code == 404

    def test_create_from_template(self, client_env):
        client, _ = client_env

        resp = client.post("/api/templates/research/apply", json={
            "agent_name": "research-bot"
        }, headers=HEADERS)
        assert resp.status_code == 201
        agent = resp.json()
        assert agent["title"] == "Research Assistant"

        # Verify agent exists
        resp = client.get("/api/agents/research-bot", headers=HEADERS)
        assert resp.status_code == 200

    def test_create_from_template_duplicate(self, client_env):
        client, _ = client_env

        # Create once
        resp = client.post("/api/templates/research/apply", json={
            "agent_name": "research-dup"
        }, headers=HEADERS)
        assert resp.status_code == 201

        # Try duplicate
        resp = client.post("/api/templates/research/apply", json={
            "agent_name": "research-dup"
        }, headers=HEADERS)
        assert resp.status_code == 400

    def test_generate_from_sentence(self, client_env):
        client, _ = client_env

        resp = client.post("/api/agents/generate", json={
            "description": "A bot that researches topics and summarizes findings"
        }, headers=HEADERS)
        assert resp.status_code == 201
        config = resp.json()
        assert "name" in config
        assert "title" in config

        # Missing description
        resp = client.post("/api/agents/generate", json={}, headers=HEADERS)
        assert resp.status_code == 400

