"""Agent runner with cross-process file locking, queue, retry, timeout, and live output."""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from hub.config import (
    get_config_path,
    get_hub_timeout,
    load_config,
)
from hub.providers import (
    AgentPermissions,
    get_provider,
    ensure_default_providers,
)

# Import skills lazily to avoid circular imports
def _sync_agent_before_run(agent_name: str) -> None:
    """Sync skills before running an agent."""
    try:
        from hub import skills
        skills.sync_agent(agent_name)
    except Exception:
        pass  # Don't fail the run if sync fails

# Guarded POSIX imports
try:
    import fcntl
    _HAS_FLOCK = True
except ImportError:
    _HAS_FLOCK = False

# Project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_RUNS_DIR = _DATA_DIR / "runs"
_LOCKS_DIR = _DATA_DIR / "locks"

# Raw output cap in JSON (~1 MB)
_RAW_OUTPUT_CAP = 1_000_000


@dataclass
class Run:
    id: str
    agent: str
    task: str
    state: str  # queued, working, done, failed, stopped
    started: Optional[str] = None
    finished: Optional[str] = None
    exit_code: Optional[int] = None
    answer: str = ""
    log_file: str = ""
    raw_output: str = ""
    owner_pid: Optional[int] = None
    pid: Optional[int] = None
    pgid: Optional[int] = None
    fail_reason: Optional[str] = None
    session_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Run":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def _ensure_dirs() -> None:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    _LOCKS_DIR.mkdir(parents=True, exist_ok=True)


def _run_dir(agent: str) -> Path:
    d = _RUNS_DIR / agent
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_run(run: Run) -> Path:
    """Atomically save run file using temp file + os.replace."""
    d = _run_dir(run.agent)
    if run.started:
        ts = run.started[:16].replace("T", "-").replace(":", "")
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"{ts}-{run.id}.json"
    filepath = d / filename
    # Write to temp file first, then atomic replace
    fd, tmp_path = tempfile.mkstemp(dir=str(d), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(run.to_dict(), f, indent=2)
        os.replace(tmp_path, str(filepath))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    return filepath


def _load_run(run_id: str) -> Optional[Run]:
    """Search all run files for a given run ID."""
    if not _RUNS_DIR.exists():
        return None
    for json_file in _RUNS_DIR.rglob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("id") == run_id:
                return Run.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            continue
    return None


def _list_runs(agent: Optional[str] = None, state: Optional[str] = None) -> List[Run]:
    runs = []
    if not _RUNS_DIR.exists():
        return runs
    agent_dirs = [_RUNS_DIR / agent] if agent else [d for d in _RUNS_DIR.iterdir() if d.is_dir()]
    for d in agent_dirs:
        if not d.exists():
            continue
        for json_file in sorted(d.glob("*.json")):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                run = Run.from_dict(data)
                if state and run.state != state:
                    continue
                runs.append(run)
            except (json.JSONDecodeError, KeyError):
                continue
    return runs


def _is_process_alive(pid: Optional[int]) -> bool:
    """Check if a process with given PID is alive."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def recover_stale_runs() -> List[Run]:
    """Mark orphaned runs as failed. Only if owner_pid is dead."""
    _ensure_dirs()
    recovered = []
    all_runs = _list_runs()
    for run in all_runs:
        if run.state in ("queued", "working") and run.owner_pid is not None:
            if not _is_process_alive(run.owner_pid):
                run.state = "failed"
                run.fail_reason = "interrupted"
                run.finished = datetime.now(timezone.utc).isoformat()
                _save_run(run)
                recovered.append(run)
    return recovered


class _FileLock:
    """Cross-process file lock using fcntl.flock."""

    def __init__(self, agent: str):
        self.agent = agent
        _ensure_dirs()
        self.lock_path = _LOCKS_DIR / f"{agent}.lock"
        self._fh: Optional[Any] = None

    def acquire(self) -> bool:
        if not _HAS_FLOCK:
            return True  # No locking on Windows
        self._fh = open(self.lock_path, "w")
        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return True

    def release(self):
        if self._fh:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None

    def try_acquire(self) -> bool:
        """Non-blocking acquire. Returns True if acquired, False if busy."""
        if not _HAS_FLOCK:
            return True
        self._fh = open(self.lock_path, "w")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (IOError, OSError):
            self._fh.close()
            self._fh = None
            return False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


def _parse_json_output(raw: str) -> str:
    """Parse JSON output, searching for answer/text/message fields."""
    # Try to find JSON in the output
    lines = raw.strip().split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
                return _extract_answer(obj)
            except json.JSONDecodeError:
                continue
    # Try the whole output
    try:
        obj = json.loads(raw)
        return _extract_answer(obj)
    except (json.JSONDecodeError, TypeError):
        pass
    # Fallback: return raw text (last ~1MB)
    return raw[-_RAW_OUTPUT_CAP:] if len(raw) > _RAW_OUTPUT_CAP else raw


def _extract_answer(obj: Any) -> str:
    """Recursively search for answer/text/message field in parsed JSON."""
    if isinstance(obj, dict):
        for key in ("answer", "text", "message"):
            if key in obj:
                val = obj[key]
                if isinstance(val, str):
                    return val
                if isinstance(val, (dict, list)):
                    return json.dumps(val)
        # Recurse into values
        for val in obj.values():
            if isinstance(val, (dict, list)):
                result = _extract_answer(val)
                if result:
                    return result
    elif isinstance(obj, list):
        for item in obj:
            result = _extract_answer(item)
            if result:
                return result
    return ""


def _check_429(raw: str) -> bool:
    """Check if output indicates a 429 rate limit."""
    return "429" in raw or "RESOURCE_EXHAUSTED" in raw


def _kill_process_group(run: Run) -> bool:
    """Safely kill a process group, verifying PID/PGID match."""
    if run.state != "working" or run.pid is None or run.pgid is None:
        return False
    try:
        # Verify PGID still matches (POSIX only)
        if sys.platform != "win32":
            try:
                actual_pgid = os.getpgid(run.pid)
                if actual_pgid != run.pgid:
                    # PID reused, mark stale
                    run.state = "failed"
                    run.fail_reason = "stale"
                    run.finished = datetime.now(timezone.utc).isoformat()
                    _save_run(run)
                    return False
            except (OSError, ProcessLookupError):
                run.state = "failed"
                run.fail_reason = "stale"
                run.finished = datetime.now(timezone.utc).isoformat()
                _save_run(run)
                return False
        # Kill the process group (POSIX) or process (Windows)
        if sys.platform != "win32":
            try:
                os.killpg(run.pgid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
            time.sleep(0.2)
            try:
                os.killpg(run.pgid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
        else:
            try:
                os.kill(run.pid, signal.CTRL_BREAK_EVENT)
            except (OSError, ProcessLookupError):
                pass
        return True
    except (OSError, ProcessLookupError):
        run.state = "failed"
        run.fail_reason = "stale"
        run.finished = datetime.now(timezone.utc).isoformat()
        _save_run(run)
        return False


def _read_stream(
    stream,
    stream_name: str,
    log_path: Path,
    output_accumulator: list,
    lock: threading.Lock,
    output_callback: Optional[Callable[[str, str], None]] = None,
) -> None:
    """Read a single stream (stdout or stderr) and forward to log, accumulator, and callback.

    Args:
        stream: The file-like stream to read (process.stdout or process.stderr).
        stream_name: 'stdout' or 'stderr' for labeling.
        log_path: Path to the log file.
        output_accumulator: Thread-safe list for collecting output.
        lock: Lock for protecting the accumulator.
        output_callback: Optional callback(line_type, text) called for each line.
    """
    if stream is None:
        return
    # Open log file in append mode so both threads can write concurrently
    with open(log_path, "a", encoding="utf-8") as log_f:
        try:
            for line in stream:
                text = line if isinstance(line, str) else line.decode("utf-8", errors="replace")
                log_f.write(f"[{stream_name}]{text}")
                log_f.flush()
                with lock:
                    output_accumulator.append(text)
                if output_callback is not None:
                    try:
                        output_callback(stream_name, text)
                    except Exception:
                        pass  # Don't let callback failures break streaming
        except ValueError:
            pass  # Stream closed


def _stream_output(
    process: subprocess.Popen,
    log_path: Path,
    output_accumulator: list,
    lock: threading.Lock,
    output_callback: Optional[Callable[[str, str], None]] = None,
) -> None:
    """Reader thread: stream stdout/stderr concurrently to log file, accumulator, and callback.

    Reads stdout and stderr in separate threads to prevent deadlock when one pipe's
    buffer fills up while the other is still open.

    Args:
        process: The running subprocess.
        log_path: Path to the log file.
        output_accumulator: Thread-safe list for collecting output.
        lock: Lock for protecting the accumulator.
        output_callback: Optional callback(line_type, text) called for each line.
            line_type is 'stdout' or 'stderr'. Called from the reader thread.
    """
    # Create the log file (truncate) before reader threads open it in append mode
    with open(log_path, "w", encoding="utf-8") as f:
        pass

    stdout_thread = threading.Thread(
        target=_read_stream,
        args=(process.stdout, "stdout", log_path, output_accumulator, lock, output_callback),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_read_stream,
        args=(process.stderr, "stderr", log_path, output_accumulator, lock, output_callback),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    stdout_thread.join()
    stderr_thread.join()


def run_agent(
    agent_name: str,
    task: str,
    no_wait: bool = False,
    timeout: Optional[int] = None,
    session_id: Optional[str] = None,
    output_callback: Optional[Callable[[str, str], None]] = None,
    run_id: Optional[str] = None,
) -> Run:
    """Run an agent task with file locking, queue, retry, and timeout.

    If session_id is provided, the task and result are persisted as messages
    in the session via the memory layer. Context from previous messages,
    memories, and project files is assembled and prepended to the task.
    """
    _ensure_dirs()
    if timeout is None:
        timeout = get_hub_timeout()

    config = load_config()
    try:
        agent_cfg = config["agents"][agent_name]
    except KeyError:
        run = Run(
            id=str(uuid.uuid4()),
            agent=agent_name,
            task=task,
            state="failed",
            fail_reason=f"Agent '{agent_name}' not found",
            owner_pid=os.getpid(),
            finished=datetime.now(timezone.utc).isoformat(),
        )
        _save_run(run)
        return run

    runner_name = agent_cfg.get("runner", "junie")
    try:
        runner_cfg = config["runners"][runner_name]
    except KeyError:
        run = Run(
            id=str(uuid.uuid4()),
            agent=agent_name,
            task=task,
            state="failed",
            fail_reason=f"Runner '{runner_name}' not found",
            owner_pid=os.getpid(),
            finished=datetime.now(timezone.utc).isoformat(),
        )
        _save_run(run)
        return run

    project_dir = agent_cfg.get("project_dir", "")
    guidelines = agent_cfg.get("guidelines", "")

    # Validate project path exists and is accessible
    if project_dir:
        project_path = Path(project_dir).expanduser().resolve()
        if not project_path.exists():
            # Warn but don't fail — project may be created later
            pass
        # Security: ensure project is not the hub data dir
        if str(project_path).startswith(str(_DATA_DIR.resolve())):
            run = Run(
                id=str(uuid.uuid4()),
                agent=agent_name,
                task=task,
                state="failed",
                fail_reason="Project directory cannot be inside the hub data directory",
                owner_pid=os.getpid(),
                finished=datetime.now(timezone.utc).isoformat(),
            )
            _save_run(run)
            return run

    # Assemble context from session history, memories, and project files
    if session_id:
        try:
            from hub import memory
            context = memory.assemble_context(
                session_id=session_id,
                agent_id=agent_name,
                project_path=project_dir or None,
                guidelines=guidelines or None,
            )
            if context:
                task = context + "\n\n---\n\n## Current Task\n\n" + task
        except Exception:
            # Don't fail the run if context assembly fails
            pass

    # Resolve provider from runner config
    ensure_default_providers()
    provider = get_provider(runner_name)
    if provider is None:
        run = Run(
            id=str(uuid.uuid4()),
            agent=agent_name,
            task=task,
            state="failed",
            fail_reason=f"Provider '{runner_name}' not found",
            owner_pid=os.getpid(),
            finished=datetime.now(timezone.utc).isoformat(),
        )
        _save_run(run)
        return run

    # Check provider availability
    if not provider.check_available():
        run = Run(
            id=str(uuid.uuid4()),
            agent=agent_name,
            task=task,
            state="failed",
            fail_reason=f"Provider '{runner_name}' binary not found",
            owner_pid=os.getpid(),
            finished=datetime.now(timezone.utc).isoformat(),
        )
        _save_run(run)
        return run

    # Load permissions from agent config
    permissions = AgentPermissions.from_dict(agent_cfg.get("permissions", {}))

    # Check if this is a remote (SSH) provider — it handles execution internally
    from hub.providers import SSHProvider
    is_remote = isinstance(provider, SSHProvider)

    # Create run
    if run_id is None:
        run_id = str(uuid.uuid4())
    run = Run(
        id=run_id,
        agent=agent_name,
        task=task,
        state="queued",
        owner_pid=os.getpid(),
        session_id=session_id,
    )
    _save_run(run)

    # Acquire file lock
    file_lock = _FileLock(agent_name)

    if no_wait:
        if not file_lock.try_acquire():
            run.state = "failed"
            run.fail_reason = "agent busy"
            run.finished = datetime.now(timezone.utc).isoformat()
            _save_run(run)
            return run
    else:
        file_lock.acquire()

    try:
        # Sync skills before running
        _sync_agent_before_run(agent_name)

        # Start working
        run.state = "working"
        run.started = datetime.now(timezone.utc).isoformat()
        _save_run(run)

        # Log file path
        log_path = _run_dir(agent_name) / f"{run_id}.log"
        run.log_file = str(log_path.relative_to(_PROJECT_ROOT))

        if is_remote:
            # Remote (SSH) provider — execute via provider.run() directly
            result = provider.run(task, project_dir, permissions, timeout=timeout)
            run.exit_code = result.exit_code
            run.raw_output = result.raw_output[-_RAW_OUTPUT_CAP:] if result.raw_output else ""
            run.answer = result.answer or _parse_json_output(result.raw_output)
            if result.error:
                run.state = "failed"
                run.fail_reason = result.error
            elif result.exit_code == 0:
                run.state = "done"
            else:
                run.state = "failed"
                run.fail_reason = f"exit code {result.exit_code}"
            run.finished = datetime.now(timezone.utc).isoformat()
            # Write output to log file
            with open(log_path, "w", encoding="utf-8") as log_f:
                log_f.write(result.raw_output)
            _save_run(run)
        else:
            # Local subprocess provider — build command and run via subprocess
            command_template = runner_cfg.get("command")
            cmd = provider.build_command(task, project_dir, permissions, command_template=command_template)

            # Retry logic
            retry_delays = [30, 60, 90]
            attempt = 0
            max_attempts = len(retry_delays) + 1

            while attempt < max_attempts:
                # Cap raw output
                output_lock = threading.Lock()
                output_parts: List[str] = []

                # Start subprocess in its own process group
                popen_kwargs: Dict[str, Any] = {
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "text": True,
                }
                if sys.platform != "win32":
                    popen_kwargs["start_new_session"] = True

                try:
                    process = subprocess.Popen(cmd, **popen_kwargs)
                except FileNotFoundError:
                    run.state = "failed"
                    run.fail_reason = f"Binary not found: {cmd[0]}"
                    run.finished = datetime.now(timezone.utc).isoformat()
                    _save_run(run)
                    return run
                run.pid = process.pid
                try:
                    run.pgid = os.getpgid(process.pid)
                except AttributeError:
                    run.pgid = process.pid  # Windows fallback
                _save_run(run)

                # Start output streaming thread
                stream_thread = threading.Thread(
                    target=_stream_output,
                    args=(process, log_path, output_parts, output_lock, output_callback),
                    daemon=True,
                )
                stream_thread.start()

                # Wait with timeout
                start_time = time.monotonic()
                timed_out = False
                while True:
                    ret = process.poll()
                    elapsed = time.monotonic() - start_time
                    if ret is not None:
                        break
                    if elapsed >= timeout:
                        timed_out = True
                        break
                    time.sleep(0.5)

                if timed_out:
                    # Kill the process directly first
                    try:
                        process.kill()
                    except (OSError, ProcessLookupError):
                        pass
                    _kill_process_group(run)

                # Wait for process to finish, then close streams, then join thread
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                # Close streams to unblock the reader thread
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()
                stream_thread.join(timeout=3)

                raw_output = "".join(output_parts)

                if timed_out:
                    run.state = "failed"
                    run.fail_reason = "timeout"
                    run.exit_code = -1
                    run.finished = datetime.now(timezone.utc).isoformat()
                    run.raw_output = raw_output[-_RAW_OUTPUT_CAP:]
                    _save_run(run)
                    # Retry on timeout? No, don't retry timeout
                    break

                run.exit_code = process.returncode

                if _check_429(raw_output) and attempt < len(retry_delays):
                    time.sleep(retry_delays[attempt])
                    attempt += 1
                    continue

                # Parse output
                run.answer = _parse_json_output(raw_output)
                run.raw_output = raw_output[-_RAW_OUTPUT_CAP:]

                if process.returncode == 0:
                    run.state = "done"
                else:
                    run.state = "failed"
                    run.fail_reason = f"exit code {process.returncode}"
                run.finished = datetime.now(timezone.utc).isoformat()
                _save_run(run)
                break

        # Persist session messages if session_id is set
        if session_id:
            _persist_run_to_session(run)

        return run

    finally:
        file_lock.release()


def _persist_run_to_session(run: Run) -> None:
    """Persist the result of a run as an assistant message in the session.
    
    If the run failed, persist a failure message instead.
    """
    try:
        from hub import memory
        if run.state == "done" and run.answer:
            memory.add_message(
                session_id=run.session_id,
                role="assistant",
                content=run.answer,
                run_id=run.id,
            )
        elif run.state in ("failed", "stopped"):
            reason = run.fail_reason or "unknown error"
            content = f"Run failed: {reason}"
            if run.answer:
                content += f"\n\nPartial output: {run.answer}"
            memory.add_message(
                session_id=run.session_id,
                role="assistant",
                content=content,
                run_id=run.id,
            )
    except Exception:
        # Don't let persistence failures break the run
        pass


def stop_run(run_id: str) -> Optional[Run]:
    """Stop a running agent by run ID."""
    run = _load_run(run_id)
    if run is None:
        return None

    if run.state != "working":
        return run

    if _kill_process_group(run):
        run.state = "stopped"
        run.finished = datetime.now(timezone.utc).isoformat()
        _save_run(run)

    return run


def get_run(run_id: str) -> Optional[Run]:
    """Get a run by ID."""
    return _load_run(run_id)


def list_runs(agent: Optional[str] = None, state: Optional[str] = None) -> List[Run]:
    """List runs, optionally filtered by agent and/or state."""
    return _list_runs(agent, state)


def agent_status(agent_name: str) -> Dict[str, Any]:
    """Get current status of an agent."""
    runs = _list_runs(agent_name)
    runs.sort(
        key=lambda r: r.started or "",
        reverse=True,
    )
    latest = runs[0] if runs else None

    status = "idle"
    current_task = None
    last_run = None

    if latest:
        if latest.state == "working":
            status = "working"
            current_task = latest.task
        elif latest.state == "failed":
            status = "failed"
            last_run = latest
        else:
            last_run = latest

    # Count queued runs
    queued = sum(1 for r in runs if r.state == "queued")

    return {
        "name": agent_name,
        "status": status,
        "current_task": current_task,
        "last_run": last_run.to_dict() if last_run else None,
        "queue_length": queued,
    }
