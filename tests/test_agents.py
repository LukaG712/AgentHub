"""Tests for hub/agents.py"""

import os
import tempfile
from pathlib import Path

import pytest

from hub import agents
from hub.config import load_config, save_config


@pytest.fixture
def hub_env(tmp_path):
    """Set up a temporary hub config for testing."""
    config_path = tmp_path / "hub.yaml"
    config = {
        "runners": {
            "junie": {
                "command": ["junie", "--task", "{task}", "--project", "{project}"],
                "skills_dir": ".junie/skills",
                "guidelines_file": ".junie/AGENTS.md",
            }
        },
        "agents": {},
    }
    save_config(config, config_path)
    old = os.environ.get("HUB_CONFIG")
    os.environ["HUB_CONFIG"] = str(config_path)
    yield config_path
    if old is not None:
        os.environ["HUB_CONFIG"] = old
    else:
        os.environ.pop("HUB_CONFIG", None)


class TestListAgents:
    def test_empty_list(self, hub_env):
        assert agents.list_agents() == []

    def test_list_after_create(self, hub_env):
        agents.create_agent("vault", runner="junie", project_dir="/mnt/vault")
        assert "vault" in agents.list_agents()


class TestCreateAgent:
    def test_create_basic(self, hub_env):
        result = agents.create_agent("vault", runner="junie", project_dir="/mnt/vault")
        assert result["runner"] == "junie"
        assert result["project_dir"] == "/mnt/vault"
        assert agents.agent_exists("vault")

    def test_create_with_all_fields(self, hub_env):
        result = agents.create_agent(
            "vault",
            runner="junie",
            project_dir="/mnt/vault",
            title="Vault Librarian",
            description="Manages vault notes",
            skills=["skill-a"],
            guidelines="Be nice",
        )
        assert result["title"] == "Vault Librarian"
        assert result["skills"] == ["skill-a"]

    def test_create_invalid_name(self, hub_env):
        with pytest.raises(ValueError, match="Invalid"):
            agents.create_agent("Bad Name", runner="junie", project_dir="/mnt")

    def test_create_duplicate(self, hub_env):
        agents.create_agent("vault", runner="junie", project_dir="/mnt")
        with pytest.raises(ValueError, match="already exists"):
            agents.create_agent("vault", runner="junie", project_dir="/mnt")


class TestGetAgent:
    def test_get_existing(self, hub_env):
        agents.create_agent("vault", runner="junie", project_dir="/mnt")
        agent = agents.get_agent("vault")
        assert agent["runner"] == "junie"

    def test_get_nonexistent(self, hub_env):
        with pytest.raises(KeyError, match="not found"):
            agents.get_agent("nonexistent")


class TestUpdateAgent:
    def test_update_title(self, hub_env):
        agents.create_agent("vault", runner="junie", project_dir="/mnt")
        updated = agents.update_agent_data("vault", {"title": "New Title"})
        assert updated["title"] == "New Title"

    def test_update_forbidden_field(self, hub_env):
        agents.create_agent("vault", runner="junie", project_dir="/mnt")
        with pytest.raises(ValueError, match="Cannot update"):
            agents.update_agent_data("vault", {"command": ["bad"]})

    def test_update_nonexistent(self, hub_env):
        with pytest.raises(KeyError, match="not found"):
            agents.update_agent_data("nonexistent", {"title": "X"})


class TestDeleteAgent:
    def test_delete_existing(self, hub_env):
        agents.create_agent("vault", runner="junie", project_dir="/mnt")
        agents.delete_agent_by_name("vault")
        assert not agents.agent_exists("vault")

    def test_delete_nonexistent(self, hub_env):
        with pytest.raises(KeyError, match="not found"):
            agents.delete_agent_by_name("nonexistent")


class TestAgentExists:
    def test_exists_true(self, hub_env):
        agents.create_agent("vault", runner="junie", project_dir="/mnt")
        assert agents.agent_exists("vault")

    def test_exists_false(self, hub_env):
        assert not agents.agent_exists("nonexistent")
