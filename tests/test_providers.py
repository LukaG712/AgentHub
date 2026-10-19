"""Tests for hub/providers.py"""

import os
from unittest.mock import patch, MagicMock

import pytest

from hub.providers import (
    AgentPermissions,
    AgentProvider,
    JunieProvider,
    SSHProvider,
    ProviderRunResult,
    get_provider,
    list_providers,
    register_provider,
    ensure_default_providers,
)


class TestAgentPermissions:
    def test_default_permissions_all_true(self):
        """Default permissions should all be enabled."""
        perms = AgentPermissions()
        assert perms.file_read is True
        assert perms.file_write is True
        assert perms.command_exec is True
        assert perms.git_ops is True
        assert perms.network is True

    def test_from_dict_empty(self):
        """Empty dict should return default permissions."""
        perms = AgentPermissions.from_dict({})
        assert perms.file_read is True

    def test_from_dict_none(self):
        """None should return default permissions."""
        perms = AgentPermissions.from_dict(None)
        assert perms.file_read is True

    def test_from_dict_partial(self):
        """Partial dict should fill missing with defaults."""
        perms = AgentPermissions.from_dict({"file_write": False, "network": False})
        assert perms.file_read is True
        assert perms.file_write is False
        assert perms.command_exec is True
        assert perms.git_ops is True
        assert perms.network is False

    def test_from_dict_all_disabled(self):
        """All permissions can be disabled."""
        perms = AgentPermissions.from_dict({
            "file_read": False,
            "file_write": False,
            "command_exec": False,
            "git_ops": False,
            "network": False,
        })
        assert all(v is False for v in perms.to_dict().values())

    def test_to_dict(self):
        """Serialization should produce correct dict."""
        perms = AgentPermissions(file_write=False, network=False)
        d = perms.to_dict()
        assert d["file_read"] is True
        assert d["file_write"] is False
        assert d["network"] is False

    def test_permission_flags_empty(self):
        """All enabled permissions produce no flags."""
        perms = AgentPermissions()
        assert perms.permission_flags() == []

    def test_permission_flags_some_disabled(self):
        """Disabled permissions produce --no- flags."""
        perms = AgentPermissions(file_write=False, network=False)
        flags = perms.permission_flags()
        assert "--no-file-write" in flags
        assert "--no-network" in flags
        assert "--no-file-read" not in flags

    def test_permission_flags_all_disabled(self):
        """All disabled permissions produce all flags."""
        perms = AgentPermissions(
            file_read=False,
            file_write=False,
            command_exec=False,
            git_ops=False,
            network=False,
        )
        flags = perms.permission_flags()
        assert len(flags) == 5
        assert "--no-file-read" in flags
        assert "--no-git-ops" in flags


class TestJunieProvider:
    def test_name(self):
        """Provider name should be 'junie'."""
        p = JunieProvider()
        assert p.name == "junie"

    def test_check_available_with_env(self):
        """Check available respects JUNIE_BIN env var."""
        with patch("os.environ", {"JUNIE_BIN": "/usr/bin/junie"}), \
             patch("shutil.which", return_value="/usr/bin/junie"):
            p = JunieProvider()
            assert p.check_available() is True

    def test_check_available_without_env(self):
        """Check available falls back to 'junie' on PATH."""
        with patch("os.environ", {}), \
             patch("shutil.which", return_value="/usr/bin/junie"):
            p = JunieProvider()
            assert p.check_available() is True

    def test_check_available_not_found(self):
        """Check available returns False when binary is missing."""
        with patch("os.environ", {}), \
             patch("shutil.which", return_value=None):
            p = JunieProvider()
            assert p.check_available() is False

    def test_build_command_basic(self):
        """Build command includes task and project."""
        with patch("os.environ", {}):
            p = JunieProvider()
            perms = AgentPermissions()
            cmd = p.build_command("fix bug", "/path/to/project", perms)
            assert "junie" in cmd
            assert "--task" in cmd
            assert "fix bug" in cmd
            assert "--project" in cmd
            assert "/path/to/project" in cmd

    def test_build_command_with_permissions(self):
        """Build command includes permission flags."""
        with patch("os.environ", {}):
            p = JunieProvider()
            perms = AgentPermissions(file_write=False, network=False)
            cmd = p.build_command("fix bug", "/path/to/project", perms)
            assert "--no-file-write" in cmd
            assert "--no-network" in cmd

    def test_build_command_with_junie_bin(self):
        """Build command uses JUNIE_BIN when set."""
        with patch("os.environ", {"JUNIE_BIN": "/custom/junie"}):
            p = JunieProvider()
            perms = AgentPermissions()
            cmd = p.build_command("fix bug", "/path/to/project", perms)
            assert cmd[0] == "/custom/junie"

    def test_build_command_with_extra_args(self):
        """Build command includes extra arguments."""
        with patch("os.environ", {}):
            p = JunieProvider()
            perms = AgentPermissions()
            cmd = p.build_command("fix bug", "/path/to/project", perms, extra_args=["--verbose"])
            assert "--verbose" in cmd

    def test_parse_answer_default(self):
        """Default parse_answer returns raw output."""
        p = JunieProvider()
        assert p.parse_answer("hello") == "hello"


class TestProviderRegistry:
    def test_default_junie_registered(self):
        """Junie provider is registered by default."""
        ensure_default_providers()
        assert get_provider("junie") is not None

    def test_list_providers_includes_junie(self):
        """List providers includes junie."""
        ensure_default_providers()
        names = list_providers()
        assert "junie" in names

    def test_register_custom_provider(self):
        """Custom providers can be registered."""
        class MockProvider(AgentProvider):
            @property
            def name(self):
                return "mock"

            def check_available(self):
                return True

            def build_command(self, task, project_dir, permissions, extra_args=None):
                return []

            def run(self, task, project_dir, permissions, timeout=1800, extra_args=None):
                return ProviderRunResult(exit_code=0, raw_output="")

        register_provider(MockProvider())
        assert get_provider("mock") is not None

    def test_get_unknown_provider(self):
        """Getting unknown provider returns None."""
        assert get_provider("nonexistent") is None


class TestProviderRunResult:
    def test_success_result(self):
        """Success result has exit code 0."""
        result = ProviderRunResult(exit_code=0, raw_output="done", answer="done")
        assert result.exit_code == 0
        assert result.error is None

    def test_error_result(self):
        """Error result has error message."""
        result = ProviderRunResult(exit_code=-1, raw_output="", error="timeout")
        assert result.error == "timeout"


class TestSSHProvider:
    """Tests for SSHProvider."""

    def test_name_default(self):
        """Default name is 'ssh'."""
        p = SSHProvider()
        assert p.name == "ssh"

    def test_name_custom(self):
        """Custom name is respected."""
        p = SSHProvider(name="remote-vm")
        assert p.name == "remote-vm"

    def test_check_available_no_ssh(self):
        """Returns False when SSH is not available."""
        with patch("shutil.which", return_value=None):
            p = SSHProvider()
            assert p.check_available() is False

    def test_check_available_with_ssh(self):
        """Returns True when SSH is available."""
        with patch("shutil.which", return_value="/usr/bin/ssh"):
            p = SSHProvider()
            assert p.check_available() is True

    def test_build_command(self):
        """Build command returns placeholder."""
        p = SSHProvider()
        perms = AgentPermissions()
        cmd = p.build_command("task", "/project", perms)
        assert "ssh" in cmd

    def test_run_no_remote_config(self):
        """Run returns error when no remote config."""
        p = SSHProvider()
        perms = AgentPermissions()
        with patch("hub.config.load_config", return_value={"agents": {}}):
            result = p.run("task", "/project", perms)
            assert result.exit_code == -1
            assert "not configured" in (result.error or "")

    def test_run_remote_unavailable(self):
        """Run returns error when remote host is unreachable."""
        p = SSHProvider()
        perms = AgentPermissions()
        config = {
            "agents": {
                "remote-agent": {
                    "runner": "ssh",
                    "remote": {
                        "host": "unreachable.com",
                        "user": "root",
                    }
                }
            }
        }
        with patch("hub.config.load_config", return_value=config), \
             patch("shutil.which", return_value="/usr/bin/ssh"):
            result = p.run("task", "/project", perms)
            assert result.exit_code == -1
            assert "Cannot connect" in (result.error or "")

    def test_run_success(self):
        """Run returns success when remote execution succeeds."""
        p = SSHProvider()
        perms = AgentPermissions()
        config = {
            "agents": {
                "remote-agent": {
                    "runner": "ssh",
                    "remote": {
                        "host": "remote.com",
                        "user": "root",
                        "sync_before_run": False,
                    }
                }
            }
        }
        with patch("hub.config.load_config", return_value=config), \
             patch("shutil.which", return_value="/usr/bin/ssh"):
            # Mock RemoteTarget
            mock_target = MagicMock()
            mock_target.is_available.return_value = True
            mock_target.execute.return_value = (0, '{"answer": "done"}', "")
            mock_target.build_remote_command.return_value = "junie --task 'test'"
            with patch("hub.remote.RemoteTarget", return_value=mock_target):
                result = p.run("task", "/project", perms)
                assert result.exit_code == 0
                assert "done" in result.raw_output
