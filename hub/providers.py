"""Agent provider abstraction layer.

Defines an interface for agent execution backends so that Junie CLI is one
provider among many, not the only way to run agents.
"""

import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ProviderRunResult:
    """Result of a provider run."""
    exit_code: int
    raw_output: str
    answer: str = ""
    error: Optional[str] = None


@dataclass
class AgentPermissions:
    """Tool permissions for an agent."""
    file_read: bool = True
    file_write: bool = True
    command_exec: bool = True
    git_ops: bool = True
    network: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentPermissions":
        """Create permissions from a dict (config file)."""
        if not data:
            return cls()
        return cls(
            file_read=data.get("file_read", True),
            file_write=data.get("file_write", True),
            command_exec=data.get("command_exec", True),
            git_ops=data.get("git_ops", True),
            network=data.get("network", True),
        )

    def to_dict(self) -> Dict[str, bool]:
        """Serialize permissions to a dict."""
        return {
            "file_read": self.file_read,
            "file_write": self.file_write,
            "command_exec": self.command_exec,
            "git_ops": self.git_ops,
            "network": self.network,
        }

    def permission_flags(self) -> List[str]:
        """Return command-line flags for permissions.

        Returns a list of --no-<permission> flags for disabled permissions.
        """
        flags = []
        if not self.file_read:
            flags.append("--no-file-read")
        if not self.file_write:
            flags.append("--no-file-write")
        if not self.command_exec:
            flags.append("--no-command-exec")
        if not self.git_ops:
            flags.append("--no-git-ops")
        if not self.network:
            flags.append("--no-network")
        return flags


class AgentProvider(ABC):
    """Abstract base class for agent execution providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g., 'junie', 'claude-code')."""
        ...

    @abstractmethod
    def check_available(self) -> bool:
        """Check if the provider binary/CLI is available on the system."""
        ...

    @abstractmethod
    def build_command(
        self,
        task: str,
        project_dir: str,
        permissions: AgentPermissions,
        extra_args: Optional[List[str]] = None,
    ) -> List[str]:
        """Build the command to run the agent.

        Args:
            task: The task prompt for the agent.
            project_dir: The project directory path.
            permissions: Tool permissions for this run.
            extra_args: Additional command-line arguments.

        Returns:
            List of command arguments.
        """
        ...

    @abstractmethod
    def run(
        self,
        task: str,
        project_dir: str,
        permissions: AgentPermissions,
        timeout: int = 1800,
        extra_args: Optional[List[str]] = None,
    ) -> ProviderRunResult:
        """Execute an agent task.

        Args:
            task: The task prompt for the agent.
            project_dir: The project directory path.
            permissions: Tool permissions for this run.
            timeout: Maximum execution time in seconds.
            extra_args: Additional command-line arguments.

        Returns:
            ProviderRunResult with exit code, output, and parsed answer.
        """
        ...

    def parse_answer(self, raw_output: str) -> str:
        """Parse the agent's answer from raw output.

        Override this if the provider has a specific output format.
        Default implementation returns the raw output as-is.
        """
        return raw_output


class JunieProvider(AgentProvider):
    """Provider for Junie CLI agent execution."""

    @property
    def name(self) -> str:
        return "junie"

    def check_available(self) -> bool:
        """Check if Junie CLI is available."""
        junie_bin = os.environ.get("JUNIE_BIN")
        if junie_bin:
            if sys.platform == "win32" and junie_bin.endswith(".py"):
                return os.path.isfile(junie_bin)
            return shutil.which(junie_bin) is not None or os.path.isfile(junie_bin)
        return shutil.which("junie") is not None

    def _resolve_binary(self, binary_name: str) -> List[str]:
        """Resolve a binary name to executable path(s).
        
        Returns a list of one or two strings (e.g., ["python", "fake_agent.py"] or ["junie"]).
        """
        if binary_name == "junie":
            junie_bin = os.environ.get("JUNIE_BIN")
            if junie_bin:
                if sys.platform == "win32" and junie_bin.endswith(".py"):
                    return [sys.executable, junie_bin]
                return [junie_bin]
        return [binary_name]

    def build_command(
        self,
        task: str,
        project_dir: str,
        permissions: AgentPermissions,
        extra_args: Optional[List[str]] = None,
        command_template: Optional[List[str]] = None,
    ) -> List[str]:
        """Build the Junie CLI command.
        
        Args:
            task: The task prompt for the agent.
            project_dir: The project directory path.
            permissions: Tool permissions for this run.
            extra_args: Additional command-line arguments.
            command_template: Optional command template from runner config.
                If provided, uses the template's binary and arguments, substituting
                {task}, {project}, and {permissions} placeholders.
        """
        cmd_parts: List[str] = []

        if command_template:
            # Use the config's command template
            for i, part in enumerate(command_template):
                if part == "{task}":
                    cmd_parts.append(task)
                elif part == "{project}":
                    cmd_parts.append(project_dir)
                elif part == "{permissions}":
                    cmd_parts.extend(permissions.permission_flags())
                elif i == 0:
                    # First element is the binary — resolve it
                    cmd_parts.extend(self._resolve_binary(part))
                else:
                    cmd_parts.append(part)
            if extra_args:
                cmd_parts.extend(extra_args)
            return cmd_parts

        # Determine the binary
        cmd_parts.extend(self._resolve_binary("junie"))

        # Core arguments
        cmd_parts.extend(["--task", task, "--project", project_dir, "--output-format", "json"])

        # Permission flags
        cmd_parts.extend(permissions.permission_flags())

        # Extra arguments
        if extra_args:
            cmd_parts.extend(extra_args)

        return cmd_parts

    def run(
        self,
        task: str,
        project_dir: str,
        permissions: AgentPermissions,
        timeout: int = 1800,
        extra_args: Optional[List[str]] = None,
    ) -> ProviderRunResult:
        """Run Junie CLI with the given task."""
        cmd = self.build_command(task, project_dir, permissions, extra_args)

        popen_kwargs: Dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if sys.platform != "win32":
            popen_kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(cmd, **popen_kwargs)
            stdout, stderr = process.communicate(timeout=timeout)
            raw = stdout + stderr

            answer = self.parse_answer(raw)
            return ProviderRunResult(
                exit_code=process.returncode or 0,
                raw_output=raw,
                answer=answer,
            )
        except subprocess.TimeoutExpired:
            process.kill()
            return ProviderRunResult(
                exit_code=-1,
                raw_output="",
                error="timeout",
            )
        except FileNotFoundError:
            return ProviderRunResult(
                exit_code=-1,
                raw_output="",
                error=f"Binary not found: {cmd[0]}",
            )
        except Exception as e:
            return ProviderRunResult(
                exit_code=-1,
                raw_output="",
                error=str(e),
            )


class SSHProvider(AgentProvider):
    """Provider for running agents on a remote machine via SSH.

    Uses the remote module to sync the project and execute the agent
    command on a remote host.
    """

    def __init__(self, name: str = "ssh"):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def check_available(self) -> bool:
        """Check if SSH client is available."""
        return shutil.which("ssh") is not None

    def build_command(
        self,
        task: str,
        project_dir: str,
        permissions: AgentPermissions,
        extra_args: Optional[List[str]] = None,
    ) -> List[str]:
        """Build a command for remote execution.

        Returns a placeholder command — actual execution happens via SSH.
        """
        return ["ssh", "remote-exec"]

    def run(
        self,
        task: str,
        project_dir: str,
        permissions: AgentPermissions,
        timeout: int = 1800,
        extra_args: Optional[List[str]] = None,
    ) -> ProviderRunResult:
        """Run an agent task on a remote host via SSH."""
        from hub.remote import RemoteConfig, RemoteTarget, RemoteError, get_agent_remote_config
        from hub.config import load_config

        config = load_config()
        # Find the agent that uses this provider
        agent_name = None
        for an, acfg in config.get("agents", {}).items():
            if acfg.get("runner", "junie") == self._name:
                agent_name = an
                break

        remote_cfg = get_agent_remote_config(config, agent_name or "")
        if remote_cfg is None:
            return ProviderRunResult(
                exit_code=-1,
                raw_output="",
                error="Remote execution not configured — add 'remote' section to agent config",
            )

        target = RemoteTarget(remote_cfg)
        if not target.is_available():
            return ProviderRunResult(
                exit_code=-1,
                raw_output="",
                error=f"Cannot connect to remote host {remote_cfg.host}",
            )

        # Sync project if configured
        if remote_cfg.sync_before_run and project_dir:
            if not target.sync_project(project_dir):
                return ProviderRunResult(
                    exit_code=-1,
                    raw_output="",
                    error="Failed to sync project to remote host",
                )

        # Build the remote command
        # Use JunieProvider to build the base command, then adapt for remote
        junie = JunieProvider()
        local_cmd = junie.build_command(task, project_dir, permissions, extra_args)
        remote_cmd = target.build_remote_command(local_cmd, project_dir)

        # Execute remotely
        try:
            exit_code, stdout, stderr = target.execute(remote_cmd, timeout=timeout)
            raw = stdout + stderr
            answer = self.parse_answer(raw)
            return ProviderRunResult(
                exit_code=exit_code,
                raw_output=raw,
                answer=answer,
            )
        except RemoteError as e:
            return ProviderRunResult(
                exit_code=-1,
                raw_output="",
                error=str(e),
            )


# --- Provider registry ---

_providers: Dict[str, AgentProvider] = {}


def register_provider(provider: AgentProvider) -> None:
    """Register a provider by name."""
    _providers[provider.name] = provider


def get_provider(name: str) -> Optional[AgentProvider]:
    """Get a provider by name."""
    return _providers.get(name)


def list_providers() -> List[str]:
    """List registered provider names."""
    return list(_providers.keys())


def default_junie_provider() -> JunieProvider:
    """Return the default Junie provider instance."""
    if "junie" not in _providers:
        register_provider(JunieProvider())
    return _providers["junie"]


def ensure_default_providers() -> None:
    """Register default providers if not already registered."""
    if "junie" not in _providers:
        register_provider(JunieProvider())


# Auto-register defaults on import
ensure_default_providers()
