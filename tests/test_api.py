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

    old_config = os.environ.get("HUB_CONFIG")
    old_api_key = os.environ.get("HUB_API_KEY")
    old_junie = os.environ.get("JUNIE_BIN")

    os.environ["HUB_CONFIG"] = str(config_path)
    os.environ["HUB_API_KEY"] = "test-secret-key"
    os.environ["JUNIE_BIN"] = str(Path(__file__).parent / "fake_agent.py")

    with patch("hub.runner._RUNS_DIR", runs_dir), \
         patch("hub.runner._LOCKS_DIR", locks_dir), \
         patch("hub.runner._PROJECT_ROOT", tmp_path), \
         patch("hub.skills._SKILLS_DIR", skills_dir):
        from hub import api as api_module
        yield TestClient(api_module.app)

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
