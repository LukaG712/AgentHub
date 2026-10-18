"""Tests for hub/config.py"""

import os
import tempfile
from pathlib import Path

import pytest

from hub.config import (
    validate_name,
    load_config,
    save_config,
    resolve_command,
    get_runner_config,
    get_agent_config,
    add_agent,
    update_agent,
    delete_agent,
    get_hub_timeout,
)


class TestValidateName:
    def test_valid_names(self):
        assert validate_name("vault")
        assert validate_name("a")
        assert validate_name("my-agent-1")
        assert validate_name("agent123")
        assert validate_name("a-b-c-d-e-f-g-h-i-j-k-l-m-n-o-p")

    def test_invalid_names(self):
        assert not validate_name("")
        assert not validate_name("-vault")
        assert not validate_name("Vault")
        assert not validate_name("vault agent")
        assert not validate_name("vault/agent")
        assert not validate_name("a" * 42)  # too long


class TestLoadConfig:
    def test_load_nonexistent(self, tmp_path):
        cfg = load_config(tmp_path / "nope.yaml")
        assert cfg == {"runners": {}, "agents": {}}

    def test_load_empty(self, tmp_path):
        p = tmp_path / "hub.yaml"
        p.write_text("")
        cfg = load_config(p)
        assert cfg == {"runners": {}, "agents": {}}

    def test_load_full(self, tmp_path):
        p = tmp_path / "hub.yaml"
        p.write_text(
            "runners:\n"
            "  junie:\n"
            "    command: ['junie', '--task', '{task}']\n"
            "agents:\n"
            "  vault:\n"
            "    title: 'Vault'\n"
            "    runner: junie\n"
            "    project_dir: /mnt/vault\n"
        )
        cfg = load_config(p)
        assert "junie" in cfg["runners"]
        assert "vault" in cfg["agents"]
        assert cfg["agents"]["vault"]["title"] == "Vault"


class TestSaveConfig:
    def test_save_creates_backup(self, tmp_path):
        p = tmp_path / "hub.yaml"
        p.write_text("agents: {}\nrunners: {}\n")
        config = {"runners": {}, "agents": {"vault": {"runner": "junie"}}}
        save_config(config, p)
        assert (p.with_suffix(".yaml.bak")).exists()

    def test_save_no_backup_if_new(self, tmp_path):
        p = tmp_path / "hub.yaml"
        config = {"runners": {}, "agents": {}}
        save_config(config, p)
        assert not (p.with_suffix(".yaml.bak")).exists()


class TestResolveCommand:
    def test_resolve_placeholders(self):
        cmd = ["junie", "--task", "{task}", "--project", "{project}"]
        resolved = resolve_command(cmd, "my task", "/my/project")
        assert resolved == ["junie", "--task", "my task", "--project", "/my/project"]

    def test_junie_bin_override(self):
        os.environ["JUNIE_BIN"] = "/usr/local/bin/junie"
        try:
            cmd = ["junie", "--task", "{task}"]
            resolved = resolve_command(cmd, "test", "")
            assert resolved[0] == "/usr/local/bin/junie"
        finally:
            del os.environ["JUNIE_BIN"]


class TestAgentCRUD:
    def test_add_agent(self):
        config = {"runners": {}, "agents": {}}
        config = add_agent(config, "vault", {"runner": "junie", "project_dir": "/mnt"})
        assert "vault" in config["agents"]

    def test_add_duplicate(self):
        config = {"runners": {}, "agents": {"vault": {}}}
        with pytest.raises(ValueError, match="already exists"):
            add_agent(config, "vault", {"runner": "junie"})

    def test_add_invalid_name(self):
        config = {"runners": {}, "agents": {}}
        with pytest.raises(ValueError, match="Invalid"):
            add_agent(config, "Bad Name", {"runner": "junie"})

    def test_update_agent(self):
        config = {"runners": {}, "agents": {"vault": {"title": "Old"}}}
        config = update_agent(config, "vault", {"title": "New"})
        assert config["agents"]["vault"]["title"] == "New"

    def test_update_forbidden_field(self):
        config = {"runners": {}, "agents": {"vault": {}}}
        with pytest.raises(ValueError, match="Cannot update"):
            update_agent(config, "vault", {"command": ["bad"]})

    def test_delete_agent(self):
        config = {"runners": {}, "agents": {"vault": {}}}
        config = delete_agent(config, "vault")
        assert "vault" not in config["agents"]


class TestGetHubTimeout:
    def test_default_timeout(self):
        if "HUB_TIMEOUT" in os.environ:
            del os.environ["HUB_TIMEOUT"]
        assert get_hub_timeout() == 1800

    def test_custom_timeout(self):
        os.environ["HUB_TIMEOUT"] = "300"
        try:
            assert get_hub_timeout() == 300
        finally:
            del os.environ["HUB_TIMEOUT"]

    def test_invalid_timeout(self):
        os.environ["HUB_TIMEOUT"] = "not-a-number"
        try:
            assert get_hub_timeout() == 1800
        finally:
            del os.environ["HUB_TIMEOUT"]
