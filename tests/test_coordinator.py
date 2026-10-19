"""Tests for the multi-agent task coordinator."""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

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

    db_path = tmp_path / "hub.db"

    old_config = os.environ.get("HUB_CONFIG")
    old_api_key = os.environ.get("HUB_API_KEY")
    old_junie = os.environ.get("JUNIE_BIN")
    old_db = os.environ.get("HUB_DB_PATH")

    os.environ["HUB_CONFIG"] = str(config_path)
    os.environ["HUB_API_KEY"] = "test-secret-key"
    os.environ["JUNIE_BIN"] = str(Path(__file__).parent / "fake_agent.py")
    os.environ["HUB_DB_PATH"] = str(db_path)

    from hub import memory as memory_module
    memory_module.close_connection()

    from unittest.mock import patch
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


class TestCoordinatorBasics:
    """Test coordinator creation and task management without execution."""

    def setup_method(self):
        """Set up a clean coordinator registry for each test."""
        from hub import coordinator
        coordinator._active_coordinators.clear()

    def test_create_coordinator(self):
        """Test creating a coordinator."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            assert coord is not None
            assert coord.project_dir == str(Path(tmp).resolve())
            assert coord.max_concurrency == 3
            summary = coord.get_summary()
            assert summary["total_tasks"] == 0
            assert summary["is_complete"] is True

    def test_add_task(self):
        """Test adding tasks to a coordinator."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            tid = coord.add_task("task1", "Do something", "vault")
            assert tid is not None
            task = coord.get_task(tid)
            assert task is not None
            assert task.name == "task1"
            assert task.status == "pending"
            assert task.agent == "vault"

    def test_add_task_with_dependencies(self):
        """Test adding tasks with dependencies."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            tid1 = coord.add_task("task1", "First task", "vault")
            tid2 = coord.add_task("task2", "Second task", "vault", dependencies=["task1"])
            task2 = coord.get_task(tid2)
            assert tid1 in task2.dependencies

    def test_add_task_invalid_dependency(self):
        """Test that adding a task with an invalid dependency raises an error."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            with pytest.raises(ValueError, match="not found"):
                coord.add_task("task1", "Task", "vault", dependencies=["nonexistent"])

    def test_remove_task(self):
        """Test removing a pending task."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            tid = coord.add_task("task1", "Do something", "vault")
            assert coord.remove_task(tid) is True
            assert coord.get_task(tid) is None

    def test_remove_running_task_fails(self):
        """Test that removing a running task fails."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            tid = coord.add_task("task1", "Do something", "vault")
            task = coord.get_task(tid)
            task.status = "running"
            assert coord.remove_task(tid) is False

    def test_remove_task_cleans_dependencies(self):
        """Test that removing a task removes it from other tasks' dependencies."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            tid1 = coord.add_task("task1", "First", "vault")
            tid2 = coord.add_task("task2", "Second", "vault", dependencies=["task1"])
            coord.remove_task(tid1)
            task2 = coord.get_task(tid2)
            assert tid1 not in task2.dependencies

    def test_cancel_all(self):
        """Test cancelling all tasks."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            coord.add_task("task1", "First", "vault")
            coord.add_task("task2", "Second", "vault")
            coord.cancel_all()
            for task in coord.get_all_tasks():
                assert task.status == "cancelled"

    def test_get_summary(self):
        """Test coordinator summary includes all tasks."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp, max_concurrency=5)
            coord.add_task("task1", "First", "vault")
            coord.add_task("task2", "Second", "vault")
            summary = coord.get_summary()
            assert summary["total_tasks"] == 2
            assert summary["max_concurrency"] == 5
            assert len(summary["tasks"]) == 2

    def test_coordinator_registry(self):
        """Test coordinator registry operations."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("reg-test", tmp)
            found = coordinator.get_coordinator("reg-test")
            assert found is coord
            listed = coordinator.list_coordinators()
            assert "reg-test" in listed
            assert coordinator.remove_coordinator("reg-test") is True
            assert coordinator.get_coordinator("reg-test") is None

    def test_coordinator_not_found(self):
        """Test getting a non-existent coordinator."""
        from hub import coordinator
        assert coordinator.get_coordinator("nonexistent") is None

    def test_remove_nonexistent_coordinator(self):
        """Test removing a non-existent coordinator."""
        from hub import coordinator
        assert coordinator.remove_coordinator("nonexistent") is False


class TestCoordinatorApproval:
    """Test the approval/rejection workflow."""

    def setup_method(self):
        from hub import coordinator
        coordinator._active_coordinators.clear()

    def test_approve_task(self):
        """Test approving a task in needs_approval state."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            tid = coord.add_task("task1", "Do something", "vault")
            task = coord.get_task(tid)
            task.status = "needs_approval"
            assert coord.approve_task(tid) is True
            task = coord.get_task(tid)
            assert task.status == "completed"
            assert task.approved is True

    def test_approve_wrong_state(self):
        """Test that approving a task not in needs_approval fails."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            tid = coord.add_task("task1", "Do something", "vault")
            assert coord.approve_task(tid) is False  # pending, not needs_approval

    def test_reject_task(self):
        """Test rejecting a task in needs_approval state."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            tid = coord.add_task("task1", "Do something", "vault")
            task = coord.get_task(tid)
            task.status = "needs_approval"
            task.worktree_path = "/fake/worktree"
            with mock.patch.object(coord, "_remove_worktree", return_value=True):
                assert coord.reject_task(tid) is True
            task = coord.get_task(tid)
            assert task.status == "failed"
            assert task.error == "Changes rejected by reviewer"

    def test_reject_wrong_state(self):
        """Test that rejecting a task not in needs_approval fails."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            tid = coord.add_task("task1", "Do something", "vault")
            assert coord.reject_task(tid) is False


class TestCoordinatorDependencies:
    """Test dependency resolution logic."""

    def setup_method(self):
        from hub import coordinator
        coordinator._active_coordinators.clear()

    def test_dependencies_met(self):
        """Test that dependencies are checked correctly."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            tid1 = coord.add_task("task1", "First", "vault")
            tid2 = coord.add_task("task2", "Second", "vault", dependencies=["task1"])
            task2 = coord.get_task(tid2)
            # task1 is pending, so deps not met
            assert coord._dependencies_met(task2) is False
            # Mark task1 as completed
            task1 = coord.get_task(tid1)
            task1.status = "completed"
            assert coord._dependencies_met(task2) is True

    def test_dependencies_not_met_failed(self):
        """Test that failed dependencies block dependent tasks."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            tid1 = coord.add_task("task1", "First", "vault")
            tid2 = coord.add_task("task2", "Second", "vault", dependencies=["task1"])
            task1 = coord.get_task(tid1)
            task1.status = "failed"
            task2 = coord.get_task(tid2)
            assert coord._dependencies_met(task2) is False

    def test_no_dependencies_always_met(self):
        """Test that tasks with no dependencies are always ready."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            tid = coord.add_task("task1", "First", "vault")
            task = coord.get_task(tid)
            assert coord._dependencies_met(task) is True

    def test_is_complete_all_terminal(self):
        """Test is_complete returns True when all tasks are terminal."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            coord.add_task("task1", "First", "vault")
            task = coord.get_all_tasks()[0]
            task.status = "completed"
            assert coord.is_complete() is True

    def test_is_complete_has_pending(self):
        """Test is_complete returns False when tasks are pending."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            coord.add_task("task1", "First", "vault")
            assert coord.is_complete() is False

    def test_is_complete_empty(self):
        """Test is_complete returns True for empty coordinator."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            assert coord.is_complete() is True


class TestCoordinatorWorktree:
    """Test worktree creation and cleanup."""

    def setup_method(self):
        from hub import coordinator
        coordinator._active_coordinators.clear()

    def test_create_worktree_non_git(self):
        """Test that worktree creation returns None for non-Git directories."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            from hub.coordinator import CoordinatedTask
            task = CoordinatedTask(
                id="test-task",
                name="test",
                description="test",
                agent="vault",
            )
            result = coord._create_worktree(task)
            assert result is None

    def test_remove_worktree_nonexistent(self):
        """Test that removing a non-existent worktree returns False."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            result = coord._remove_worktree("/nonexistent/path")
            assert result is False

    def test_cleanup_worktrees(self):
        """Test that cleanup removes non-approved worktrees."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            from hub.coordinator import CoordinatedTask
            task = CoordinatedTask(
                id="test-task",
                name="test",
                description="test",
                agent="vault",
                worktree_path="/fake/path",
            )
            coord._tasks["test-task"] = task
            with mock.patch.object(coord, "_remove_worktree", return_value=True) as mock_remove:
                coord._cleanup_worktrees()
                mock_remove.assert_called_once_with("/fake/path")

    def test_cleanup_skips_approved(self):
        """Test that cleanup skips approved worktrees."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            coord = coordinator.create_coordinator("test-coord", tmp)
            from hub.coordinator import CoordinatedTask
            task = CoordinatedTask(
                id="test-task",
                name="test",
                description="test",
                agent="vault",
                worktree_path="/fake/path",
                approved=True,
            )
            coord._tasks["test-task"] = task
            with mock.patch.object(coord, "_remove_worktree", return_value=True) as mock_remove:
                coord._cleanup_worktrees()
                mock_remove.assert_not_called()


class TestCoordinatorAPI:
    """Test the coordinator API endpoints."""

    def test_create_coordinator_endpoint(self, client):
        """Test creating a coordinator via API."""
        with tempfile.TemporaryDirectory() as tmp:
            resp = client.post("/api/coordinator", json={
                "coordinator_id": "api-test",
                "project_dir": tmp,
            }, headers=HEADERS)
            assert resp.status_code == 201
            data = resp.json()
            assert data["total_tasks"] == 0

    def test_create_coordinator_missing_project(self, client):
        """Test that creating without project_dir fails."""
        resp = client.post("/api/coordinator", json={}, headers=HEADERS)
        assert resp.status_code == 400

    def test_list_coordinators(self, client):
        """Test listing coordinators."""
        resp = client.get("/api/coordinator", headers=HEADERS)
        assert resp.status_code == 200

    def test_get_coordinator_not_found(self, client):
        """Test getting a non-existent coordinator."""
        resp = client.get("/api/coordinator/nonexistent", headers=HEADERS)
        assert resp.status_code == 404

    def test_add_task_endpoint(self, client):
        """Test adding a task via API."""
        with tempfile.TemporaryDirectory() as tmp:
            client.post("/api/coordinator", json={
                "coordinator_id": "api-task-test",
                "project_dir": tmp,
            }, headers=HEADERS)
            resp = client.post("/api/coordinator/api-task-test/tasks", json={
                "name": "api-task",
                "description": "Test task",
                "agent": "vault",
            }, headers=HEADERS)
            assert resp.status_code == 201
            data = resp.json()
            assert data["name"] == "api-task"

    def test_add_task_missing_name(self, client):
        """Test that adding a task without a name fails."""
        with tempfile.TemporaryDirectory() as tmp:
            client.post("/api/coordinator", json={
                "coordinator_id": "api-task-test2",
                "project_dir": tmp,
            }, headers=HEADERS)
            resp = client.post("/api/coordinator/api-task-test2/tasks", json={}, headers=HEADERS)
            assert resp.status_code == 400

    def test_execute_coordinator(self, client):
        """Test executing a coordinator."""
        with tempfile.TemporaryDirectory() as tmp:
            client.post("/api/coordinator", json={
                "coordinator_id": "api-exec-test",
                "project_dir": tmp,
            }, headers=HEADERS)
            resp = client.post("/api/coordinator/api-exec-test/execute", headers=HEADERS)
            assert resp.status_code == 200

    def test_cancel_coordinator(self, client):
        """Test cancelling a coordinator."""
        with tempfile.TemporaryDirectory() as tmp:
            client.post("/api/coordinator", json={
                "coordinator_id": "api-cancel-test",
                "project_dir": tmp,
            }, headers=HEADERS)
            resp = client.post("/api/coordinator/api-cancel-test/cancel", headers=HEADERS)
            assert resp.status_code == 200

    def test_delete_coordinator(self, client):
        """Test deleting a coordinator."""
        with tempfile.TemporaryDirectory() as tmp:
            client.post("/api/coordinator", json={
                "coordinator_id": "api-del-test",
                "project_dir": tmp,
            }, headers=HEADERS)
            resp = client.delete("/api/coordinator/api-del-test", headers=HEADERS)
            assert resp.status_code == 200
            assert resp.json()["deleted"] == "api-del-test"

    def test_approve_task_endpoint(self, client):
        """Test approving a task via API."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            client.post("/api/coordinator", json={
                "coordinator_id": "api-approve-test",
                "project_dir": tmp,
            }, headers=HEADERS)
            coord = coordinator.get_coordinator("api-approve-test")
            tid = coord.add_task("task1", "Test", "vault")
            task = coord.get_task(tid)
            task.status = "needs_approval"
            resp = client.post(f"/api/coordinator/api-approve-test/tasks/{tid}/approve", headers=HEADERS)
            assert resp.status_code == 200

    def test_reject_task_endpoint(self, client):
        """Test rejecting a task via API."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            client.post("/api/coordinator", json={
                "coordinator_id": "api-reject-test",
                "project_dir": tmp,
            }, headers=HEADERS)
            coord = coordinator.get_coordinator("api-reject-test")
            tid = coord.add_task("task1", "Test", "vault")
            task = coord.get_task(tid)
            task.status = "needs_approval"
            resp = client.post(f"/api/coordinator/api-reject-test/tasks/{tid}/reject", headers=HEADERS)
            assert resp.status_code == 200

    def test_remove_task_endpoint(self, client):
        """Test removing a task via API."""
        from hub import coordinator
        with tempfile.TemporaryDirectory() as tmp:
            client.post("/api/coordinator", json={
                "coordinator_id": "api-remove-test",
                "project_dir": tmp,
            }, headers=HEADERS)
            coord = coordinator.get_coordinator("api-remove-test")
            tid = coord.add_task("task1", "Test", "vault")
            resp = client.delete(f"/api/coordinator/api-remove-test/tasks/{tid}", headers=HEADERS)
            assert resp.status_code == 200
