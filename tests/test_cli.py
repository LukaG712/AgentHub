"""Tests for hub/cli.py"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from hub.config import save_config
from hub.cli import main


@pytest.fixture
def hub_env(tmp_path):
    """Set up a temporary hub config for CLI testing."""
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
                "guidelines": "",
            }
        },
    }
    save_config(config, config_path)

    data_dir = tmp_path / "data"
    runs_dir = data_dir / "runs"
    locks_dir = data_dir / "locks"
    runs_dir.mkdir(parents=True)
    locks_dir.mkdir(parents=True)

    old_config = os.environ.get("HUB_CONFIG")
    old_junie = os.environ.get("JUNIE_BIN")
    old_timeout = os.environ.get("HUB_TIMEOUT")

    os.environ["HUB_CONFIG"] = str(config_path)
    os.environ["JUNIE_BIN"] = str(Path(__file__).parent / "fake_agent.py")
    os.environ["HUB_TIMEOUT"] = "10"

    with patch("hub.runner._RUNS_DIR", runs_dir), \
         patch("hub.runner._LOCKS_DIR", locks_dir), \
         patch("hub.runner._PROJECT_ROOT", tmp_path):
        yield tmp_path, config_path

    if old_config is not None:
        os.environ["HUB_CONFIG"] = old_config
    else:
        os.environ.pop("HUB_CONFIG", None)
    if old_junie is not None:
        os.environ["JUNIE_BIN"] = old_junie
    else:
        os.environ.pop("JUNIE_BIN", None)
    if old_timeout is not None:
        os.environ["HUB_TIMEOUT"] = old_timeout
    else:
        os.environ.pop("HUB_TIMEOUT", None)


class TestCLIAgents:
    def test_list_agents(self, hub_env, capsys):
        main(["agents"])
        captured = capsys.readouterr()
        assert "vault" in captured.out


class TestCLIRun:
    def test_run_successful(self, hub_env, capsys):
        main(["run", "vault", "test task"])
        captured = capsys.readouterr()
        assert "Done" in captured.out

    def test_run_missing_agent(self, hub_env, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["run", "nonexistent", "test"])
        assert exc_info.value.code == 1


class TestCLIRuns:
    def test_list_runs_empty(self, hub_env, capsys):
        main(["runs"])
        captured = capsys.readouterr()
        assert "No runs" in captured.out

    def test_list_runs_after_run(self, hub_env, capsys):
        main(["run", "vault", "test task"])
        main(["runs"])
        captured = capsys.readouterr()
        assert "vault" in captured.out


class TestCLIStop:
    def test_stop_nonexistent(self, hub_env, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["stop", "nonexistent-id"])
        assert exc_info.value.code == 1
