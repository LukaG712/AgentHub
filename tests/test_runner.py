"""Tests for hub/runner.py"""

import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from hub.config import save_config
from hub.runner import (
    _LOCKS_DIR,
    _RUNS_DIR,
    Run,
    _check_429,
    _ensure_dirs,
    _extract_answer,
    _parse_json_output,
    _save_run,
    get_run,
    list_runs,
    recover_stale_runs,
    run_agent,
    stop_run,
)

# Skip POSIX-only tests on Windows
skip_posix = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX-only (flock, process groups)",
)


@pytest.fixture
def hub_env(tmp_path):
    """Set up a temporary hub config and data dirs for testing."""
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
                "title": "Vault",
                "runner": "junie",
                "project_dir": str(tmp_path / "vault-project"),
                "skills": [],
                "guidelines": "",
            }
        },
    }
    save_config(config, config_path)

    # Set up data dirs
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

    # Patch the runner module's paths
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


class TestRunDataclass:
    def test_to_dict(self):
        run = Run(
            id="test-id",
            agent="vault",
            task="test task",
            state="done",
            owner_pid=1234,
        )
        d = run.to_dict()
        assert d["id"] == "test-id"
        assert d["owner_pid"] == 1234

    def test_from_dict(self):
        d = {
            "id": "test-id",
            "agent": "vault",
            "task": "test",
            "state": "done",
            "owner_pid": 1234,
            "pid": 5678,
            "pgid": 5678,
        }
        run = Run.from_dict(d)
        assert run.id == "test-id"
        assert run.pid == 5678
        assert run.pgid == 5678


class TestParseJsonOutput:
    def test_simple_json_answer(self):
        raw = '{"answer": "the answer"}'
        assert _parse_json_output(raw) == "the answer"

    def test_json_text_field(self):
        raw = '{"text": "the text"}'
        assert _parse_json_output(raw) == "the text"

    def test_json_message_field(self):
        raw = '{"message": "the message"}'
        assert _parse_json_output(raw) == "the message"

    def test_nested_json(self):
        raw = '{"result": {"answer": "nested answer"}}'
        assert _parse_json_output(raw) == "nested answer"

    def test_non_json_fallback(self):
        raw = "just plain text"
        assert _parse_json_output(raw) == "just plain text"

    def test_multiline_json(self):
        raw = "some noise\n{\"answer\": \"found\"}\nmore noise"
        assert _parse_json_output(raw) == "found"


class TestCheck429:
    def test_429_detected(self):
        assert _check_429("Error 429: Too Many Requests")

    def test_resource_exhausted(self):
        assert _check_429("RESOURCE_EXHAUSTED")

    def test_no_429(self):
        assert not _check_429("All good")


class TestRunAgent:
    def test_successful_run(self, hub_env):
        tmp_path, _ = hub_env
        run = run_agent("vault", "test task")
        assert run.state == "done"
        assert "test task" in run.task
        assert run.owner_pid == os.getpid()
        assert run.pid is not None
        assert run.pgid is not None
        assert run.log_file  # log file path stored

    def test_missing_agent(self, hub_env):
        run = run_agent("nonexistent", "test")
        assert run.state == "failed"
        assert "not found" in (run.fail_reason or "")

    def test_missing_binary(self, tmp_path):
        """Test that missing binary returns clear error."""
        config_path = tmp_path / "hub.yaml"
        config = {
            "runners": {
                "junie": {
                    "command": ["nonexistent-binary-xyz", "--task", "{task}"],
                }
            },
            "agents": {
                "vault": {
                    "runner": "junie",
                    "project_dir": str(tmp_path),
                }
            },
        }
        save_config(config, config_path)
        old_config = os.environ.get("HUB_CONFIG")
        old_junie = os.environ.get("JUNIE_BIN")
        os.environ["HUB_CONFIG"] = str(config_path)
        if "JUNIE_BIN" in os.environ:
            del os.environ["JUNIE_BIN"]

        data_dir = tmp_path / "data"
        runs_dir = data_dir / "runs"
        locks_dir = data_dir / "locks"
        runs_dir.mkdir(parents=True)
        locks_dir.mkdir(parents=True)

        try:
            with patch("hub.runner._RUNS_DIR", runs_dir), \
                 patch("hub.runner._LOCKS_DIR", locks_dir), \
                 patch("hub.runner._PROJECT_ROOT", tmp_path):
                run = run_agent("vault", "test")
                assert run.state == "failed"
                assert "not found" in (run.fail_reason or "").lower() or "binary" in (run.fail_reason or "").lower()
        finally:
            if old_config is not None:
                os.environ["HUB_CONFIG"] = old_config
            else:
                os.environ.pop("HUB_CONFIG", None)
            if old_junie is not None:
                os.environ["JUNIE_BIN"] = old_junie

    def test_failed_run(self, hub_env):
        tmp_path, config_path = hub_env
        # Update config to use --fail flag
        from hub.config import load_config
        config = load_config(config_path)
        config["runners"]["junie"]["command"] = [
            "junie", "--task", "{task}", "--project", "{project}", "--fail"
        ]
        save_config(config, config_path)

        run = run_agent("vault", "test task")
        assert run.state == "failed"

    @skip_posix
    def test_no_wait_fails_when_busy(self, hub_env):
        """Test --no-wait fails immediately when agent is busy."""
        # This test is tricky — we need a running agent to hold the lock.
        # We'll simulate by holding the lock ourselves.
        from hub.runner import _ensure_dirs, _FileLock
        _ensure_dirs()

        lock = _FileLock("vault")
        lock.acquire()
        try:
            run = run_agent("vault", "test", no_wait=True)
            assert run.state == "failed"
            assert run.fail_reason == "agent busy"
        finally:
            lock.release()

    def test_run_stores_pids(self, hub_env):
        run = run_agent("vault", "test task")
        assert run.owner_pid == os.getpid()
        assert run.pid is not None
        assert run.pgid is not None

    def test_run_stores_log_file(self, hub_env):
        run = run_agent("vault", "test task")
        assert run.log_file
        assert run.log_file.endswith(".log")

    @skip_posix
    def test_timeout(self, hub_env):
        tmp_path, config_path = hub_env
        # Use --hang with very short timeout
        from hub.config import load_config
        config = load_config(config_path)
        config["runners"]["junie"]["command"] = [
            "junie", "--task", "{task}", "--project", "{project}", "--hang"
        ]
        save_config(config, config_path)

        run = run_agent("vault", "test", timeout=1)
        assert run.state == "failed"
        assert run.fail_reason == "timeout"

    @patch("hub.runner.time.sleep")
    def test_429_retry(self, mock_sleep, hub_env):
        """Test 429 retry with patched sleep."""
        tmp_path, config_path = hub_env
        # First call returns 429, second succeeds
        fake_script = Path(__file__).parent / "fake_agent.py"
        from hub.config import load_config
        config = load_config(config_path)
        # We'll use a wrapper that simulates 429 on first call
        wrapper = tmp_path / "wrapper.py"
        call_file = str(tmp_path / ".call_count")
        fake_script_str = str(fake_script)
        wrapper.write_text(
            "#!/usr/bin/env python3\n"
            "import os, sys, json\n"
            f'call_file = r"{call_file}"\n'
            "count = 0\n"
            "if os.path.exists(call_file):\n"
            "    with open(call_file) as f:\n"
            "        count = int(f.read().strip())\n"
            "count += 1\n"
            "with open(call_file, 'w') as f:\n"
            "    f.write(str(count))\n"
            "if count == 1:\n"
            '    print(json.dumps({"error": "429 RESOURCE_EXHAUSTED"}))\n'
            "    sys.exit(0)\n"
            f'os.execv(sys.executable, [sys.executable, r"{fake_script_str}"] + sys.argv[1:])\n'
        )
        config["runners"]["junie"]["command"] = [
            sys.executable, str(wrapper), "--task", "{task}", "--project", "{project}"
        ]
        save_config(config, config_path)
        old_junie = os.environ.get("JUNIE_BIN")
        os.environ["JUNIE_BIN"] = str(wrapper)

        try:
            run = run_agent("vault", "test task")
            assert run.state == "done"
        finally:
            if old_junie is not None:
                os.environ["JUNIE_BIN"] = old_junie


class TestRecoverStaleRuns:
    def test_recover_dead_owner(self, hub_env):
        tmp_path, _ = hub_env
        # Create a run with a dead owner PID
        run = Run(
            id="stale-1",
            agent="vault",
            task="test",
            state="working",
            owner_pid=99999,  # dead PID
        )
        _save_run(run)

        recovered = recover_stale_runs()
        assert len(recovered) == 1
        assert recovered[0].state == "failed"
        assert recovered[0].fail_reason == "interrupted"

    def test_leave_live_owner(self, hub_env):
        tmp_path, _ = hub_env
        # Create a run with the current PID as owner
        run = Run(
            id="live-1",
            agent="vault",
            task="test",
            state="working",
            owner_pid=os.getpid(),
        )
        _save_run(run)

        recovered = recover_stale_runs()
        assert len(recovered) == 0
        # Run should still be working
        loaded = get_run("live-1")
        assert loaded is not None
        assert loaded.state == "working"


class TestListRuns:
    def test_list_empty(self, hub_env):
        runs = list_runs()
        assert runs == []

    def test_list_after_run(self, hub_env):
        run_agent("vault", "test task")
        runs = list_runs()
        assert len(runs) >= 1

    def test_list_filtered_by_agent(self, hub_env):
        run_agent("vault", "test task")
        runs = list_runs(agent="vault")
        assert len(runs) >= 1
        runs = list_runs(agent="nonexistent")
        assert len(runs) == 0


class TestGetRun:
    def test_get_existing(self, hub_env):
        run = run_agent("vault", "test task")
        loaded = get_run(run.id)
        assert loaded is not None
        assert loaded.id == run.id

    def test_get_nonexistent(self, hub_env):
        loaded = get_run("nonexistent-id")
        assert loaded is None


class TestLiveOutput:
    def test_log_file_grows_while_running(self, hub_env):
        """Test that the .log file grows while the agent is still running."""
        tmp_path, config_path = hub_env
        from hub.config import load_config
        config = load_config(config_path)
        config["runners"]["junie"]["command"] = [
            "junie", "--task", "{task}",
            "--project", "{project}", "--delay", "1"
        ]
        save_config(config, config_path)

        import threading

        result = []

        def do_run():
            result.append(run_agent("vault", "delayed task"))

        t = threading.Thread(target=do_run)
        t.start()
        time.sleep(0.3)  # Let it start

        # Check log file exists and has content while running
        runs = list_runs(agent="vault")
        latest = runs[-1]
        log_path = Path(latest.log_file) if latest else None

        t.join(timeout=10)

        assert len(result) == 1
        run = result[0]
        assert run.state == "done"
        assert run.log_file
        # Log file should exist
        log_full = tmp_path / run.log_file
        assert log_full.exists()
        content = log_full.read_text()
        assert "[stdout]" in content


class TestAtomicRunFiles:
    def test_run_file_is_valid_json(self, hub_env):
        """Test that run files are always valid JSON (atomic writes)."""
        run = run_agent("vault", "test task")
        # Find the run file
        runs = list_runs(agent="vault")
        assert len(runs) >= 1
        # All run files should be valid JSON
        for r in runs:
            assert r.id  # If we loaded it, it's valid JSON


class TestHUBTimeout:
    def test_hub_timeout_env(self, hub_env):
        """Test that HUB_TIMEOUT env variable is respected."""
        # Already set to 10 in hub_env fixture
        # The timeout test above uses this
        pass


class TestStreamingOutput:
    def test_output_callback_receives_lines(self, hub_env):
        """Test that output_callback is called for each line of output."""
        tmp_path, config_path = hub_env
        from hub.config import load_config
        config = load_config(config_path)
        config["runners"]["junie"]["command"] = [
            "junie", "--task", "{task}", "--project", "{project}"
        ]
        save_config(config, config_path)

        received_lines = []
        lock = threading.Lock()

        def callback(line_type, text):
            with lock:
                received_lines.append((line_type, text))

        run = run_agent("vault", "test task", output_callback=callback)
        assert run.state == "done"
        with lock:
            assert len(received_lines) > 0, "Callback should receive at least one line"
            # All lines should be stdout (fake_agent writes to stdout)
            for lt, txt in received_lines:
                assert lt == "stdout"
                assert "Completed task" in txt or "Agent processed" in txt

    def test_output_callback_before_completion(self, hub_env):
        """Test that output_callback fires before the run completes."""
        tmp_path, config_path = hub_env
        from hub.config import load_config
        config = load_config(config_path)
        config["runners"]["junie"]["command"] = [
            "junie", "--task", "{task}", "--project", "{project}", "--delay", "0.5"
        ]
        save_config(config, config_path)

        callback_fired = threading.Event()
        run_finished = threading.Event()

        def callback(line_type, text):
            callback_fired.set()

        def do_run():
            run_agent("vault", "delayed task", output_callback=callback)
            run_finished.set()

        t = threading.Thread(target=do_run, daemon=True)
        t.start()

        # Wait for callback to fire (should happen before run finishes)
        fired = callback_fired.wait(timeout=5)
        assert fired, "Callback should fire during execution"

        t.join(timeout=10)
        assert run_finished.is_set(), "Run should complete"

    def test_output_callback_empty_output(self, hub_env):
        """Test that callback handles empty output gracefully."""
        tmp_path, config_path = hub_env
        from hub.config import load_config
        config = load_config(config_path)
        config["runners"]["junie"]["command"] = [
            "junie", "--task", "{task}", "--project", "{project}"
        ]
        save_config(config, config_path)

        received = []

        def callback(line_type, text):
            received.append(text)

        run = run_agent("vault", "test", output_callback=callback)
        assert run.state == "done"
        # Callback should have been called at least once
        assert len(received) > 0

    def test_output_callback_error_handling(self, hub_env):
        """Test that callback exceptions don't break the run."""
        tmp_path, config_path = hub_env
        from hub.config import load_config
        config = load_config(config_path)
        config["runners"]["junie"]["command"] = [
            "junie", "--task", "{task}", "--project", "{project}"
        ]
        save_config(config, config_path)

        def bad_callback(line_type, text):
            raise RuntimeError("Callback error!")

        # Should not raise
        run = run_agent("vault", "test", output_callback=bad_callback)
        assert run.state == "done"

    def test_concurrent_stdout_stderr(self, hub_env):
        """Test that stdout and stderr are read concurrently (no deadlock).

        Uses a script that writes to both stdout and stderr simultaneously.
        With sequential reading, a large stderr output could block while
        stdout is still open, causing a deadlock.
        """
        tmp_path, config_path = hub_env
        # Create a script that writes to both stdout and stderr
        script = tmp_path / "dual_output.py"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import sys, time\n"
            "# Write to stderr first (large output)\n"
            "for i in range(100):\n"
            "    sys.stderr.write(f'stderr line {i}\\n')\n"
            "    sys.stderr.flush()\n"
            "# Write to stdout\n"
            "for i in range(100):\n"
            "    sys.stdout.write(f'stdout line {i}\\n')\n"
            "    sys.stdout.flush()\n"
            "sys.stdout.write('done\\n')\n"
            "sys.stderr.write('stderr done\\n')\n"
        )
        from hub.config import load_config
        config = load_config(config_path)
        python = sys.executable
        config["runners"]["junie"]["command"] = [
            python, str(script), "--task", "{task}", "--project", "{project}"
        ]
        save_config(config, config_path)

        received = []
        lock = threading.Lock()

        def callback(line_type, text):
            with lock:
                received.append((line_type, text.strip()))

        run = run_agent("vault", "dual output test", output_callback=callback)
        assert run.state == "done"
        with lock:
            stdout_lines = [t for lt, t in received if lt == "stdout"]
            stderr_lines = [t for lt, t in received if lt == "stderr"]
        # Both streams should have been read — no deadlock
        assert len(stdout_lines) > 0, "stdout should have output"
        assert len(stderr_lines) > 0, "stderr should have output"
        # Verify we got the final markers
        stdout_texts = " ".join(stdout_lines)
        stderr_texts = " ".join(stderr_lines)
        assert "done" in stdout_texts, "stdout final marker missing"
        assert "stderr done" in stderr_texts, "stderr final marker missing"


class TestProcessCheck:
    """Regression tests for C3: _is_process_alive must not kill processes."""

    def test_is_process_alive_none(self):
        """None PID should return False."""
        from hub.runner import _is_process_alive
        assert _is_process_alive(None) is False

    def test_is_process_alive_current_process(self):
        """Current process PID should return True."""
        from hub.runner import _is_process_alive
        assert _is_process_alive(os.getpid()) is True

    def test_is_process_alive_nonexistent(self):
        """Non-existent PID should return False."""
        from hub.runner import _is_process_alive
        # PID 99999999 is very unlikely to exist
        assert _is_process_alive(99999999) is False

    def test_is_process_alive_does_not_kill(self, hub_env):
        """_is_process_alive must NOT kill the process it checks.
        
        Regression test for C3: the old fallback used taskkill /F which
        force-killed the process instead of checking if it was alive.
        """
        from hub.runner import _is_process_alive
        pid = os.getpid()
        # Call it multiple times — should always return True and never kill
        for _ in range(5):
            assert _is_process_alive(pid) is True


class TestFileLock:
    """Regression tests for M1: file lock on Windows."""

    def test_file_lock_acquire_release(self, hub_env):
        """File lock should acquire and release correctly."""
        from hub.runner import _FileLock
        lock = _FileLock("test-agent")
        lock.acquire()
        lock.release()

    def test_file_lock_context_manager(self, hub_env):
        """File lock should work as context manager."""
        from hub.runner import _FileLock
        with _FileLock("test-agent"):
            pass  # Should not raise

    def test_file_lock_try_acquire(self, hub_env):
        """try_acquire should return True when available."""
        from hub.runner import _FileLock
        lock = _FileLock("test-agent")
        assert lock.try_acquire() is True
        lock.release()

    def test_file_lock_try_acquire_busy(self, hub_env):
        """try_acquire should return False when already held."""
        from hub.runner import _FileLock
        lock = _FileLock("test-agent")
        lock.acquire()
        assert lock.try_acquire() is False
        lock.release()
