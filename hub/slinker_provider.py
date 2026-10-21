"""Slinker provider — delegates agent execution to the Slinker service.

This provider sends tasks to a running Slinker HTTP service instead of
invoking the Junie CLI directly.  Slinker provides Git worktree isolation,
persistent task storage, and structured changed-file reporting.

Configuration via environment variables:
    Slinker_URL     — Base URL of the Slinker service (default: http://localhost:8000)
    Slinker_API_KEY — Bearer token for authentication
    Slinker_TIMEOUT — Per-task timeout in seconds (default: 1800)

The task format is detected automatically:
    - If the task starts with "TASK:", it submits a task and returns immediately.
    - If the task starts with "STATUS:", it polls for a task's status by ID.
    - If the task starts with "WORKERS:", it lists active workers.
    - If the task starts with "QUEUE:", it returns the queue status.
    - Otherwise, the task is executed synchronously via chat completions.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from hub.providers import AgentPermissions, AgentProvider, ProviderRunResult

logger = logging.getLogger(__name__)


class SlinkerProvider(AgentProvider):
    """Provider that delegates task execution to a Slinker HTTP service.

    Slinker handles worktree isolation, Junie CLI execution, and changed-file
    detection.  This provider simply forwards the task and translates the
    result back to the Greenie ProviderRunResult format.
    """

    @property
    def name(self) -> str:
        return "Slinker"

    def _get_base_url(self) -> str:
        return os.environ.get("Slinker_URL", "http://localhost:8000").rstrip("/")

    def _get_api_key(self) -> str:
        return os.environ.get("Slinker_API_KEY", "")

    def check_available(self) -> bool:
        """Check if the Slinker service is reachable."""
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self._get_base_url()}/health")
                return resp.status_code == 200
        except Exception as e:
            logger.warning(f"Slinker health check failed: {e}")
            return False

    def build_command(
        self,
        task: str,
        project_dir: str,
        permissions: AgentPermissions,
        extra_args: Optional[List[str]] = None,
    ) -> List[str]:
        """Build a placeholder command — execution happens via HTTP."""
        return ["Slinker", "execute", "--task", task, "--project", project_dir]

    def _parse_task(self, task: str) -> tuple[str, str]:
        """Parse the task string to determine the operation and target.

        Returns:
            Tuple of (operation, target) where operation is one of
            'chat', 'task', 'status', 'workers', 'queue'.
        """
        task_upper = task.upper().strip()
        if task_upper.startswith("TASK:"):
            return "task", task[len("TASK:"):].strip()
        if task_upper.startswith("STATUS:"):
            return "status", task[len("STATUS:"):].strip()
        if task_upper.startswith("WORKERS:"):
            return "workers", task[len("WORKERS:"):].strip()
        if task_upper.startswith("QUEUE:"):
            return "queue", task[len("QUEUE:"):].strip()
        # Default: synchronous chat execution
        return "chat", task

    def run(
        self,
        task: str,
        project_dir: str,
        permissions: AgentPermissions,
        timeout: int = 1800,
        extra_args: Optional[List[str]] = None,
    ) -> ProviderRunResult:
        """Execute a task via the Slinker HTTP service.

        Supports multiple operations:
        - Default: synchronous chat completion
        - TASK: — submit a task and return immediately
        - STATUS: — poll for task status by ID
        - WORKERS: — list active workers
        - QUEUE: — get queue status
        """
        api_key = self._get_api_key()
        base_url = self._get_base_url()

        operation, target = self._parse_task(task)

        headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async def _execute() -> ProviderRunResult:
                async with httpx.AsyncClient(timeout=min(timeout, 1800)) as client:
                    if operation == "chat":
                        return await self._chat(client, base_url, target, headers, project_dir, timeout)
                    elif operation == "task":
                        return await self._submit_task(client, base_url, target, headers, project_dir)
                    elif operation == "status":
                        return await self._get_task_status(client, base_url, target, headers)
                    elif operation == "workers":
                        return await self._list_workers(client, base_url, headers)
                    elif operation == "queue":
                        return await self._get_queue_status(client, base_url, headers)
                    else:
                        return ProviderRunResult(
                            exit_code=-1,
                            raw_output="",
                            error=f"Unknown operation: {operation}",
                        )

            try:
                loop = asyncio.new_event_loop()
            except Exception:
                loop = asyncio.get_running_loop()
            if loop.is_running():
                # Already in async context — use run_in_executor to avoid blocking
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(loop.run_until_complete, _execute())
                    return future.result()
            else:
                try:
                    return loop.run_until_complete(_execute())
                finally:
                    loop.close()

        except httpx.ConnectError as e:
            return ProviderRunResult(
                exit_code=-1,
                raw_output="",
                error=f"Cannot connect to Slinker at {base_url}: {e}",
            )
        except httpx.TimeoutException as e:
            return ProviderRunResult(
                exit_code=-1,
                raw_output="",
                error=f"Slinker request timed out after {timeout}s: {e}",
            )
        except Exception as e:
            return ProviderRunResult(
                exit_code=-1,
                raw_output="",
                error=f"Slinker execution failed: {e}",
            )

    async def _chat(
        self, client: httpx.AsyncClient, base_url: str, task: str, headers: Dict[str, str],
        project_dir: str, timeout: int
    ) -> ProviderRunResult:
        """Execute a task synchronously via chat completions."""
        messages = [{"role": "user", "content": task}]
        payload = {
            "messages": messages,
            "stream": False,
            "project_path": project_dir,
        }

        resp = await client.post(
            f"{base_url}/v1/chat/completions",
            json=payload,
            headers=headers,
        )

        if resp.status_code == 503:
            return ProviderRunResult(
                exit_code=-1,
                raw_output="",
                error="Slinker is busy. Please try again later.",
            )

        if resp.status_code != 200:
            return ProviderRunResult(
                exit_code=-1,
                raw_output=resp.text,
                error=f"Slinker returned HTTP {resp.status_code}: {resp.text}",
            )

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return ProviderRunResult(
                exit_code=-1,
                raw_output=str(data),
                error="No choices in Slinker response",
            )

        message = choices[0].get("message", {})
        answer = message.get("content", "")
        return ProviderRunResult(
            exit_code=0,
            raw_output=answer,
            answer=answer,
        )

    async def _submit_task(
        self, client: httpx.AsyncClient, base_url: str, task: str, headers: Dict[str, str],
        project_dir: str
    ) -> ProviderRunResult:
        """Submit a task and return immediately with the task ID."""
        messages = [{"role": "user", "content": task}]
        payload = {
            "messages": messages,
            "stream": False,
            "project_path": project_dir,
        }

        resp = await client.post(
            f"{base_url}/v1/chat/completions",
            json=payload,
            headers=headers,
        )

        if resp.status_code == 503:
            return ProviderRunResult(
                exit_code=-1,
                raw_output="",
                error="Slinker is busy. Please try again later.",
            )

        if resp.status_code != 200:
            return ProviderRunResult(
                exit_code=-1,
                raw_output=resp.text,
                error=f"Slinker returned HTTP {resp.status_code}: {resp.text}",
            )

        data = resp.json()
        answer = json.dumps(data, indent=2)
        return ProviderRunResult(
            exit_code=0,
            raw_output=answer,
            answer=answer,
        )

    async def _get_task_status(
        self, client: httpx.AsyncClient, base_url: str, task_id: str, headers: Dict[str, str]
    ) -> ProviderRunResult:
        """Get the status and output of a specific task."""
        resp = await client.get(
            f"{base_url}/api/v1/tasks/{task_id}",
            headers=headers,
        )

        if resp.status_code != 200:
            return ProviderRunResult(
                exit_code=-1,
                raw_output=resp.text,
                error=f"Slinker returned HTTP {resp.status_code}: {resp.text}",
            )

        data = resp.json()
        answer_parts = [f"# Task Status: {task_id}\n"]
        answer_parts.append(f"**Status:** {data.get('status', 'unknown')}")
        if data.get("project_id"):
            answer_parts.append(f"**Project:** {data.get('project_id')}")
        if data.get("created_at"):
            answer_parts.append(f"**Created:** {data.get('created_at')}")
        if data.get("completed_at"):
            answer_parts.append(f"**Completed:** {data.get('completed_at')}")

        output = data.get("output", "")
        if output:
            answer_parts.append(f"\n## Output\n{output[:5000]}")

        changed_files = data.get("changed_files", [])
        if changed_files:
            answer_parts.append(f"\n## Changed Files ({len(changed_files)})")
            for f in changed_files[:20]:
                answer_parts.append(f"- {f}")

        diff_summary = data.get("diff_summary", "")
        if diff_summary:
            answer_parts.append(f"\n## Diff Summary\n{diff_summary[:3000]}")

        answer = "\n".join(answer_parts)
        return ProviderRunResult(
            exit_code=0,
            raw_output=answer,
            answer=answer,
        )

    async def _list_workers(
        self, client: httpx.AsyncClient, base_url: str, headers: Dict[str, str]
    ) -> ProviderRunResult:
        """List all active workers."""
        resp = await client.get(
            f"{base_url}/api/v1/workers",
            headers=headers,
        )

        if resp.status_code != 200:
            return ProviderRunResult(
                exit_code=-1,
                raw_output=resp.text,
                error=f"Slinker returned HTTP {resp.status_code}: {resp.text}",
            )

        data = resp.json()
        workers = data if isinstance(data, list) else data.get("workers", [])
        answer_parts = [f"# Active Workers ({len(workers)})\n"]

        for worker in workers:
            worker_id = worker.get("worker_id", "unknown")
            status = worker.get("status", "unknown")
            task_desc = worker.get("task_description", "")
            pid = worker.get("pid")
            answer_parts.append(f"## {worker_id}")
            answer_parts.append(f"- **Status:** {status}")
            if task_desc:
                answer_parts.append(f"- **Task:** {task_desc[:200]}")
            if pid:
                answer_parts.append(f"- **PID:** {pid}")
            answer_parts.append("")

        answer = "\n".join(answer_parts)
        return ProviderRunResult(
            exit_code=0,
            raw_output=answer,
            answer=answer,
        )

    async def _get_queue_status(
        self, client: httpx.AsyncClient, base_url: str, headers: Dict[str, str]
    ) -> ProviderRunResult:
        """Get the current queue status."""
        resp = await client.get(
            f"{base_url}/api/v1/queue",
            headers=headers,
        )

        if resp.status_code != 200:
            return ProviderRunResult(
                exit_code=-1,
                raw_output=resp.text,
                error=f"Slinker returned HTTP {resp.status_code}: {resp.text}",
            )

        data = resp.json()
        answer_parts = ["# Queue Status\n"]
        for key, value in data.items():
            answer_parts.append(f"- **{key}:** {value}")

        answer = "\n".join(answer_parts)
        return ProviderRunResult(
            exit_code=0,
            raw_output=answer,
            answer=answer,
        )


# Auto-register the provider
def _register() -> None:
    from hub.providers import register_provider
    register_provider(SlinkerProvider())


_register()
