"""Tests for hub/remote.py — Remote execution support."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from hub.remote import (
    RemoteConfig,
    RemoteError,
    RemoteTarget,
    get_remote_config,
    get_agent_remote_config,
)


class TestRemoteConfig:
    """Tests for RemoteConfig dataclass."""

    def test_from_dict_minimal(self):
        """Minimal config with just host."""
        cfg = RemoteConfig.from_dict({"host": "192.168.1.1"})
        assert cfg.host == "192.168.1.1"
        assert cfg.user == "root"
        assert cfg.port == 22
        assert cfg.key_path is None

    def test_from_dict_full(self):
        """Full config with all fields."""
        cfg = RemoteConfig.from_dict({
            "host": "example.com",
            "user": "deploy",
            "port": 2222,
            "key_path": "~/.ssh/id_rsa",
            "remote_project_dir": "/opt/project",
            "remote_junie_path": "/usr/local/bin/junie",
            "sync_before_run": False,
            "connection_timeout": 60,
            "command_timeout": 3600,
        })
        assert cfg.host == "example.com"
        assert cfg.user == "deploy"
        assert cfg.port == 2222
        assert cfg.key_path == "~/.ssh/id_rsa"
        assert cfg.remote_project_dir == "/opt/project"
        assert cfg.remote_junie_path == "/usr/local/bin/junie"
        assert cfg.sync_before_run is False
        assert cfg.connection_timeout == 60
        assert cfg.command_timeout == 3600

    def test_from_dict_empty(self):
        """Empty dict returns None."""
        assert RemoteConfig.from_dict({}) is None

    def test_from_dict_no_host(self):
        """Dict without host returns None."""
        assert RemoteConfig.from_dict({"user": "root"}) is None

    def test_from_dict_none(self):
        """None returns None."""
        assert RemoteConfig.from_dict(None) is None

    def test_to_dict(self):
        """Serialization round-trip."""
        cfg = RemoteConfig(host="test.com", user="admin", port=2222)
        d = cfg.to_dict()
        assert d["host"] == "test.com"
        assert d["user"] == "admin"
        assert d["port"] == 2222

    def test_remote_project_default(self):
        """Default remote project directory."""
        cfg = RemoteConfig(host="test.com")
        assert cfg.remote_project == "~/agent-project"

    def test_remote_project_custom(self):
        """Custom remote project directory."""
        cfg = RemoteConfig(host="test.com", remote_project_dir="/srv/project")
        assert cfg.remote_project == "/srv/project"


class TestRemoteTarget:
    """Tests for RemoteTarget class."""

    def _make_config(self, **kwargs):
        return RemoteConfig(host="test.com", user="root", **kwargs)

    def test_ssh_not_available(self):
        """Target should detect missing SSH."""
        with patch("shutil.which", return_value=None):
            target = RemoteTarget(self._make_config())
            assert target._ssh_available is False
            assert target.is_available() is False

    def test_ssh_available(self):
        """Target should detect SSH when present."""
        with patch("shutil.which", return_value="/usr/bin/ssh"):
            target = RemoteTarget(self._make_config())
            assert target._ssh_available is True

    def test_is_available_no_ssh(self):
        """is_available returns False when SSH is missing."""
        with patch("shutil.which", return_value=None):
            target = RemoteTarget(self._make_config())
            assert target.is_available() is False

    def test_is_available_ssh_fails(self):
        """is_available returns False when SSH connection fails."""
        with patch("shutil.which", return_value="/usr/bin/ssh"), \
             patch("subprocess.run", side_effect=RemoteError("connection refused")):
            target = RemoteTarget(self._make_config())
            assert target.is_available() is False

    def test_is_available_ssh_succeeds(self):
        """is_available returns True when SSH connection succeeds."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        with patch("shutil.which", return_value="/usr/bin/ssh"), \
             patch("subprocess.run", return_value=mock_result):
            target = RemoteTarget(self._make_config())
            assert target.is_available() is True

    def test_ssh_args_basic(self):
        """SSH args should include security options."""
        target = RemoteTarget(self._make_config())
        args = target._ssh_args()
        assert "ssh" in args
        assert "-o" in args
        assert "StrictHostKeyChecking=no" in args
        assert "-p" in args
        assert "22" in args

    def test_ssh_args_with_key(self):
        """SSH args should include key path when configured."""
        with tempfile.NamedTemporaryFile(delete=False) as key_file:
            key_path = key_file.name
        try:
            cfg = self._make_config(key_path=key_path)
            target = RemoteTarget(cfg)
            args = target._ssh_args()
            assert "-i" in args
            assert key_path in args
        finally:
            os.unlink(key_path)

    def test_ssh_args_custom_port(self):
        """SSH args should use custom port."""
        cfg = self._make_config(port=2222)
        target = RemoteTarget(cfg)
        args = target._ssh_args()
        assert "2222" in args

    def test_execute_no_ssh(self):
        """Execute should raise RemoteError when SSH is missing."""
        with patch("shutil.which", return_value=None):
            target = RemoteTarget(self._make_config())
            with pytest.raises(RemoteError, match="SSH client not found"):
                target.execute("echo hello")

    def test_execute_success(self):
        """Execute should return exit code, stdout, stderr."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output\n"
        mock_result.stderr = ""
        with patch("shutil.which", return_value="/usr/bin/ssh"), \
             patch("subprocess.run", return_value=mock_result):
            target = RemoteTarget(self._make_config())
            code, stdout, stderr = target.execute("echo hello")
            assert code == 0
            assert stdout == "output\n"
            assert stderr == ""

    def test_execute_failure(self):
        """Execute should return non-zero exit code on failure."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error\n"
        with patch("shutil.which", return_value="/usr/bin/ssh"), \
             patch("subprocess.run", return_value=mock_result):
            target = RemoteTarget(self._make_config())
            code, stdout, stderr = target.execute("false")
            assert code == 1
            assert stderr == "error\n"

    def test_execute_timeout(self):
        """Execute should raise RemoteError on timeout."""
        import subprocess as sp
        with patch("shutil.which", return_value="/usr/bin/ssh"), \
             patch("subprocess.run", side_effect=sp.TimeoutExpired(cmd="ssh", timeout=5)):
            target = RemoteTarget(self._make_config())
            with pytest.raises(RemoteError, match="timed out"):
                target.execute("sleep 100", timeout=5)

    def test_sync_project_no_ssh(self):
        """Sync should return False when SSH is missing."""
        with patch("shutil.which", return_value=None):
            target = RemoteTarget(self._make_config())
            assert target.sync_project("/tmp") is False

    def test_sync_project_dir_not_exists(self):
        """Sync should return False when local dir doesn't exist."""
        with patch("shutil.which", return_value="/usr/bin/ssh"):
            target = RemoteTarget(self._make_config())
            assert target.sync_project("/nonexistent/path") is False

    def test_sync_project_success(self):
        """Sync should return True on success."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("hello")

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stderr = b""

            with patch("shutil.which", return_value="/usr/bin/ssh"), \
                 patch("subprocess.run", return_value=mock_result):
                target = RemoteTarget(self._make_config())
                assert target.sync_project(tmpdir) is True

    def test_build_remote_command(self):
        """Build remote command should replace local paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = RemoteTarget(self._make_config())
            cmd = target.build_remote_command(
                ["junie", "--task", "do something", "--project", tmpdir],
                tmpdir,
            )
            assert "~/agent-project" in cmd
            assert tmpdir not in cmd

    def test_build_remote_command_escapes_quotes(self):
        """Build remote command should escape single quotes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = RemoteTarget(self._make_config())
            cmd = target.build_remote_command(
                ["echo", "it's working"],
                tmpdir,
            )
            # Single quotes should be escaped
            assert "\\'" in cmd or "it" in cmd


class TestRemoteConfigHelpers:
    """Tests for get_remote_config and get_agent_remote_config."""

    def test_get_remote_config_top_level(self):
        """Get remote config from top-level section."""
        config = {
            "remote": {
                "host": "remote.example.com",
                "user": "deploy",
            },
        }
        cfg = get_remote_config(config)
        assert cfg is not None
        assert cfg.host == "remote.example.com"
        assert cfg.user == "deploy"

    def test_get_remote_config_missing(self):
        """Returns None when no remote config."""
        config = {"agents": {}}
        assert get_remote_config(config) is None

    def test_get_agent_remote_config_agent_specific(self):
        """Agent-specific remote config takes priority."""
        config = {
            "remote": {
                "host": "global.example.com",
                "user": "root",
            },
            "agents": {
                "my-agent": {
                    "remote": {
                        "host": "agent.example.com",
                        "user": "agent",
                    }
                }
            }
        }
        cfg = get_agent_remote_config(config, "my-agent")
        assert cfg is not None
        assert cfg.host == "agent.example.com"
        assert cfg.user == "agent"

    def test_get_agent_remote_config_fallback(self):
        """Falls back to top-level when agent has no remote config."""
        config = {
            "remote": {
                "host": "global.example.com",
                "user": "root",
            },
            "agents": {
                "my-agent": {}
            }
        }
        cfg = get_agent_remote_config(config, "my-agent")
        assert cfg is not None
        assert cfg.host == "global.example.com"

    def test_get_agent_remote_config_none(self):
        """Returns None when no remote config at all."""
        config = {"agents": {"my-agent": {}}}
        assert get_agent_remote_config(config, "my-agent") is None

    def test_get_agent_remote_config_unknown_agent(self):
        """Returns None for unknown agent."""
        config = {"agents": {}}
        assert get_agent_remote_config(config, "unknown") is None
