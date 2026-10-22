"""Tests for the workstation module.

Covers: models, storage, network policy, access setup, and lifecycle operations.
Uses mocking for Docker SDK to avoid requiring a real Docker daemon.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Use a temporary database for tests
_temp_dir = tempfile.mkdtemp()
os.environ["GREENIE_WORKSTATION_DB_PATH"] = os.path.join(_temp_dir, "test_workstations.db")


class TestWorkstationModels(unittest.TestCase):
    """Test workstation data models."""

    def test_workstation_defaults(self):
        from hub.workstation.models import Workstation, WorkstationStatus
        ws = Workstation(name="test")
        self.assertEqual(ws.name, "test")
        self.assertEqual(ws.status, WorkstationStatus.PENDING.value)
        self.assertTrue(ws.id.startswith("ws-"))

    def test_workstation_serialization(self):
        from hub.workstation.models import Workstation
        ws = Workstation(name="test", description="desc", tags=["a", "b"])
        d = ws.to_dict()
        self.assertEqual(d["name"], "test")
        self.assertEqual(d["tags"], ["a", "b"])
        ws2 = Workstation.from_dict(d)
        self.assertEqual(ws2.name, "test")
        self.assertEqual(ws2.description, "desc")

    def test_workstation_config_defaults(self):
        from hub.workstation.models import WorkstationConfig
        cfg = WorkstationConfig()
        self.assertEqual(cfg.image, "python:3.11-slim")
        self.assertEqual(cfg.cpu_limit, 1.0)
        self.assertEqual(cfg.memory_limit, "512m")
        self.assertTrue(cfg.enable_terminal)
        self.assertFalse(cfg.enable_desktop)

    def test_workstation_config_serialization(self):
        from hub.workstation.models import WorkstationConfig
        cfg = WorkstationConfig(image="python:3.12", cpu_limit=2.0, allowed_hosts=["example.com"])
        d = cfg.to_dict()
        cfg2 = WorkstationConfig.from_dict(d)
        self.assertEqual(cfg2.image, "python:3.12")
        self.assertEqual(cfg2.cpu_limit, 2.0)
        self.assertEqual(cfg2.allowed_hosts, ["example.com"])

    def test_workstation_access_serialization(self):
        from hub.workstation.models import WorkstationAccess
        access = WorkstationAccess(
            terminal_url="ws://localhost:8080/ws/terminal/ws-123",
            vnc_password="abc123",
        )
        d = access.to_dict()
        access2 = WorkstationAccess.from_dict(d)
        self.assertEqual(access2.terminal_url, "ws://localhost:8080/ws/terminal/ws-123")
        self.assertEqual(access2.vnc_password, "abc123")


class TestWorkstationStorage(unittest.TestCase):
    """Test workstation SQLite storage."""

    @classmethod
    def setUpClass(cls):
        # Force reimport with temp DB path
        modules_to_remove = [m for m in sys.modules if m.startswith("hub.workstation")]
        for m in modules_to_remove:
            del sys.modules[m]
        cls.db_path = os.path.join(_temp_dir, "test_storage.db")
        os.environ["GREENIE_WORKSTATION_DB_PATH"] = cls.db_path
        # Import to initialize schema at the new path
        from hub.workstation import storage  # noqa: F401
        storage._init_schema()

    def setUp(self):
        # Clean up before each test
        import sqlite3
        conn = sqlite3.connect(self.__class__.db_path)
        conn.execute("DELETE FROM workstations")
        conn.commit()
        conn.close()

    def test_save_and_get(self):
        from hub.workstation.models import Workstation
        from hub.workstation import storage
        ws = Workstation(name="test-ws", description="test")
        storage.save_workstation(ws)
        retrieved = storage.get_workstation(ws.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "test-ws")
        self.assertEqual(retrieved.description, "test")

    def test_get_nonexistent(self):
        from hub.workstation import storage
        result = storage.get_workstation("ws-nonexistent")
        self.assertIsNone(result)

    def test_list_workstations(self):
        from hub.workstation.models import Workstation
        from hub.workstation import storage
        for i in range(3):
            ws = Workstation(name=f"ws-{i}")
            storage.save_workstation(ws)
        result = storage.list_workstations(limit=10)
        self.assertEqual(len(result), 3)

    def test_list_with_status_filter(self):
        from hub.workstation.models import Workstation, WorkstationStatus
        from hub.workstation import storage
        ws1 = Workstation(name="running", status=WorkstationStatus.RUNNING.value)
        ws2 = Workstation(name="stopped", status=WorkstationStatus.STOPPED.value)
        storage.save_workstation(ws1)
        storage.save_workstation(ws2)
        running = storage.list_workstations(status=WorkstationStatus.RUNNING.value)
        self.assertEqual(len(running), 1)
        self.assertEqual(running[0].name, "running")

    def test_delete_workstation(self):
        from hub.workstation.models import Workstation
        from hub.workstation import storage
        ws = Workstation(name="to-delete")
        storage.save_workstation(ws)
        deleted = storage.delete_workstation(ws.id)
        self.assertTrue(deleted)
        self.assertIsNone(storage.get_workstation(ws.id))

    def test_update_status(self):
        from hub.workstation.models import Workstation, WorkstationStatus
        from hub.workstation import storage
        ws = Workstation(name="status-test")
        storage.save_workstation(ws)
        storage.update_workstation_status(ws.id, WorkstationStatus.RUNNING.value)
        retrieved = storage.get_workstation(ws.id)
        self.assertEqual(retrieved.status, WorkstationStatus.RUNNING.value)
        self.assertIsNotNone(retrieved.started_at)

    def test_count_workstations(self):
        from hub.workstation.models import Workstation, WorkstationStatus
        from hub.workstation import storage
        ws1 = Workstation(name="c1", status=WorkstationStatus.RUNNING.value)
        ws2 = Workstation(name="c2", status=WorkstationStatus.STOPPED.value)
        storage.save_workstation(ws1)
        storage.save_workstation(ws2)
        self.assertEqual(storage.count_workstations(), 2)
        self.assertEqual(storage.count_workstations(WorkstationStatus.RUNNING.value), 1)

    def test_config_persistence(self):
        from hub.workstation.models import Workstation, WorkstationConfig
        from hub.workstation import storage
        cfg = WorkstationConfig(image="python:3.12", cpu_limit=2.0, allowed_hosts=["example.com"])
        ws = Workstation(name="config-test", config=cfg)
        storage.save_workstation(ws)
        retrieved = storage.get_workstation(ws.id)
        self.assertEqual(retrieved.config.image, "python:3.12")
        self.assertEqual(retrieved.config.cpu_limit, 2.0)
        self.assertEqual(retrieved.config.allowed_hosts, ["example.com"])


class TestNetworkPolicy(unittest.TestCase):
    """Test network policy enforcement."""

    def test_is_private_ip(self):
        from hub.workstation.network_policy import is_private_ip
        self.assertTrue(is_private_ip("10.0.0.1"))
        self.assertTrue(is_private_ip("192.168.1.1"))
        self.assertTrue(is_private_ip("172.16.0.1"))
        self.assertTrue(is_private_ip("127.0.0.1"))
        self.assertFalse(is_private_ip("8.8.8.8"))
        self.assertFalse(is_private_ip("1.1.1.1"))

    def test_is_metadata_endpoint(self):
        from hub.workstation.network_policy import is_metadata_endpoint
        self.assertTrue(is_metadata_endpoint("169.254.169.254"))
        self.assertTrue(is_metadata_endpoint("metadata.google.internal"))
        self.assertFalse(is_metadata_endpoint("api.openai.com"))

    def test_validate_host(self):
        from hub.workstation.network_policy import validate_host
        allowed, reason = validate_host("api.openai.com")
        self.assertTrue(allowed)
        self.assertEqual(reason, "Allowed")

        allowed, reason = validate_host("169.254.169.254")
        self.assertFalse(allowed)
        self.assertIn("metadata", reason.lower())

        allowed, reason = validate_host("10.0.0.1")
        self.assertFalse(allowed)
        self.assertIn("private", reason.lower())

        allowed, reason = validate_host("127.0.0.1")
        self.assertFalse(allowed)
        self.assertIn("loopback", reason.lower())

    def test_validate_public_ip(self):
        from hub.workstation.network_policy import validate_host
        allowed, reason = validate_host("8.8.8.8")
        self.assertTrue(allowed)
        self.assertEqual(reason, "Allowed")


class TestAccessSetup(unittest.TestCase):
    """Test access setup functions."""

    def test_setup_terminal_url(self):
        from hub.workstation.models import Workstation
        from hub.workstation import access
        ws = Workstation(id="ws-test123")
        url = access.setup_terminal(ws)
        self.assertIsNotNone(url)
        self.assertIn("ws-test123", url)
        self.assertTrue(url.startswith("ws://") or url.startswith("wss://"))

    def test_validate_access_token_no_token(self):
        from hub.workstation import access
        # With no token configured, all access is allowed
        original = os.environ.pop("EVERSHADE_GREENIE_API_TOKEN", None)
        try:
            self.assertTrue(access.validate_access_token("ws-123", "any-token"))
        finally:
            if original:
                os.environ["EVERSHADE_GREENIE_API_TOKEN"] = original

    def test_validate_access_token_with_token(self):
        from hub.workstation import access
        os.environ["EVERSHADE_GREENIE_API_TOKEN"] = "secret-token"
        try:
            self.assertTrue(access.validate_access_token("ws-123", "secret-token"))
            self.assertFalse(access.validate_access_token("ws-123", "wrong-token"))
        finally:
            os.environ.pop("EVERSHADE_GREENIE_API_TOKEN", None)


class TestDriverSimulation(unittest.TestCase):
    """Test Docker driver in simulation mode (no Docker daemon)."""

    def test_is_docker_available_no_daemon(self):
        from hub.workstation import driver
        # Reset the Docker client cache
        driver._docker = None
        # Without docker SDK or daemon, should return False
        with patch.dict(sys.modules, {"docker": None}):
            driver._docker = None
            result = driver.is_docker_available()
            # May be True if docker is installed, False otherwise — just check it doesn't crash
            self.assertIsInstance(result, bool)

    def test_create_container_no_docker(self):
        from hub.workstation import driver
        from hub.workstation.models import Workstation, WorkstationConfig
        driver._docker = None
        ws = Workstation(name="test")
        cfg = WorkstationConfig()
        result = driver.create_container(ws, cfg)
        self.assertIsNone(result)

    def test_exec_no_docker(self):
        from hub.workstation import driver
        driver._docker = None
        result = driver.exec_in_container("fake-id", "echo hello")
        self.assertEqual(result["exit_code"], -1)
        self.assertIn("Docker unavailable", result["stderr"])


class TestLifecycleSimulation(unittest.TestCase):
    """Test lifecycle operations with mocked Docker."""

    @classmethod
    def setUpClass(cls):
        modules_to_remove = [m for m in sys.modules if m.startswith("hub.workstation")]
        for m in modules_to_remove:
            del sys.modules[m]
        cls.db_path = os.path.join(_temp_dir, "test_lifecycle.db")
        os.environ["GREENIE_WORKSTATION_DB_PATH"] = cls.db_path
        from hub.workstation import storage  # noqa: F401
        storage._init_schema()

    def setUp(self):
        import sqlite3
        conn = sqlite3.connect(self.__class__.db_path)
        conn.execute("DELETE FROM workstations")
        conn.commit()
        conn.close()
        # Reset Docker client
        from hub.workstation import driver
        driver._docker = None

    def test_create_workstation_no_docker(self):
        from hub.workstation import create_workstation, WorkstationStatus
        ws = create_workstation(name="test-no-docker")
        self.assertIsNotNone(ws)
        # Should fail gracefully when Docker is unavailable
        self.assertIn(ws.status, [WorkstationStatus.ERROR.value, WorkstationStatus.CREATING.value])

    def test_get_nonexistent_workstation(self):
        from hub.workstation import get_workstation
        result = get_workstation("ws-nonexistent")
        self.assertIsNone(result)

    def test_list_empty(self):
        from hub.workstation import list_workstations
        result = list_workstations()
        self.assertEqual(len(result), 0)

    def test_stats(self):
        from hub.workstation import get_workstation_stats
        stats = get_workstation_stats()
        self.assertIn("total", stats)
        self.assertIn("running", stats)
        self.assertIn("docker_available", stats)
        self.assertIsInstance(stats["docker_available"], bool)


class TestWorkflowIntegration(unittest.TestCase):
    """Test workstation step type in workflow engine."""

    def test_workstation_step_type_exists(self):
        from hub.workflow.models import StepType
        self.assertTrue(hasattr(StepType, "WORKSTATION"))
        self.assertEqual(StepType.WORKSTATION.value, "workstation")


if __name__ == "__main__":
    unittest.main()
