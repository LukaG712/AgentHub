"""Tests for hub/providers.py — Provider abstraction and permissions."""

import os
import sys
from unittest.mock import patch

import pytest

from hub.providers import (
    AgentPermissions,
    JunieProvider,
    SSHProvider,
)


class TestAgentPermissions:
    def test_default_permissions(self):
        """Default permissions are all enabled."""
        perms = AgentPermissions()
        assert perms.file_read is True
        assert perms.file_write is True
        assert perms.command_exec is True
        assert perms.git_ops is True
        assert perms.network is True

    def test_permission_flags_empty(self):
        """No flags when all permissions enabled."""
        perms = AgentPermissions()
        flags = perms.permission_flags()
        assert flags == []

    def test_permission_flags_disabled(self):
        """Flags generated for disabled permissions."""
        perms = AgentPermissions(file_write=False, network=False)
        flags = perms.permission_flags()
        assert "--no-file-write" in flags
        assert "--no-network" in flags
        assert "--no-file-read" not in flags

    def test_from_dict(self):
        """Create permissions from dict."""
        perms = AgentPermissions.from_dict({
            "file_read": True,
            "file_write": False,
            "command_exec": True,
            "git_ops": False,
            "network": True,
        })
        assert perms.file_write is False
        assert perms.git_ops is False
        assert perms.file_read is True

    def test_from_dict_empty(self):
        """Empty dict returns default permissions."""
        perms = AgentPermissions.from_dict({})
        assert perms.file_read is True

    def test_to_dict(self):
        """Serialize permissions to dict."""
        perms = AgentPermissions(file_write=False)
        d = perms.to_dict()
        assert d["file_write"] is False
        assert d["file_read"] is True


class TestJunieProvider:
    def test_build_command_list_based(self):
        """build_command returns a list, not a shell string."""
        provider = JunieProvider()
        perms = AgentPermissions()
        with patch.dict(os.environ, {"JUNIE_BIN": str(__file__.replace("test_providers.py", "fake_agent.py"))}):
            cmd = provider.build_command("test task", "/tmp/project", perms)
        assert isinstance(cmd, list)
        assert len(cmd) >= 3

    def test_build_command_no_shell_interpolation(self):
        """Command arguments are separate list items, not interpolated."""
        provider = JunieProvider()
        perms = AgentPermissions()
        # Task with special characters
        task = "test; rm -rf /"
        with patch.dict(os.environ, {"JUNIE_BIN": str(__file__.replace("test_providers.py", "fake_agent.py"))}):
            cmd = provider.build_command(task, "/tmp/project", perms)
        # The dangerous characters should be in a single argument, not split
        assert isinstance(cmd, list)
        # No argument should be just "rm" or "-rf"
        for arg in cmd:
            assert arg != "rm"
            assert arg != "-rf"

    def test_build_command_with_permissions(self):
        """Permission flags are included in command."""
        provider = JunieProvider()
        perms = AgentPermissions(file_write=False, network=False)
        with patch.dict(os.environ, {"JUNIE_BIN": str(__file__.replace("test_providers.py", "fake_agent.py"))}):
            cmd = provider.build_command("test", "/tmp/project", perms)
        assert "--no-file-write" in cmd
        assert "--no-network" in cmd

    def test_build_command_with_template(self):
        """Command template from config is used."""
        provider = JunieProvider()
        perms = AgentPermissions()
        template = ["junie", "--task", "{task}", "--project", "{project}", "--fail"]
        cmd = provider.build_command("test", "/tmp/project", perms, command_template=template)
        assert "--fail" in cmd
        assert "test" in cmd
        assert "/tmp/project" in cmd

    def test_check_available_env_var(self):
        """check_available respects JUNIE_BIN env var."""
        provider = JunieProvider()
        fake = str(__file__.replace("test_providers.py", "fake_agent.py"))
        with patch.dict(os.environ, {"JUNIE_BIN": fake}):
            assert provider.check_available() is True

    def test_check_available_not_found(self):
        """check_available returns False when binary not found."""
        provider = JunieProvider()
        with patch.dict(os.environ, {}, clear=False) as env:
            env.pop("JUNIE_BIN", None)
            with patch("shutil.which", return_value=None):
                assert provider.check_available() is False


class TestSSHProvider:
    def test_check_available(self):
        """SSH provider checks for ssh binary."""
        provider = SSHProvider()
        # Just verify it doesn't crash
        result = provider.check_available()
        assert isinstance(result, bool)
