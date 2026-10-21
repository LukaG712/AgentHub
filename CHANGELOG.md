# Changelog

All notable changes to Agent Hub will be documented in this file.

## [1.0.3] - 2026-10-19

### Installation simplification
- **Merged setup into start scripts** — `start.sh` and `start.ps1` now contain all setup logic inline; standalone `setup.sh` and `setup.ps1` removed
- **Non-blocking Junie CLI check** — missing Junie CLI shows a warning but no longer blocks installation, so you can explore the dashboard first
- **Streamlined README** — Quick Start reduced to a single command with bullet-point summary of what happens automatically

## [1.0.2] - 2026-10-19

### Bug fixes
- **Windows compatibility** — replaced `os.kill(pid, 0)` with `psutil.pid_exists()` for reliable process checking on Windows
- **Windows .bat execution** — resolve `junie` binary to full path on Windows so `.bat` files execute correctly via subprocess

## [1.0.1] - 2026-10-19

### Installation improvements
- **One-command start** — `start.sh` and `start.ps1` now auto-run setup on first launch (venv, dependencies, API key, config file)
- **Windows setup script** — new `setup.ps1` mirrors Linux `setup.sh` for consistent cross-platform setup
- **Auto-open browser** — start scripts automatically open the dashboard in your default browser
- **Simplified README** — added Quick Start section with single-command install for both platforms

### Bug fixes
- **Configurable port** — start scripts respect `HUB_PORT` environment variable

## [1.0.0] - 2026-10-19

### Features
- **Agent management** — define and configure multiple AI agents, each with its own project folder, runner, and guidelines
- **Shared skills** — create reusable skills (prompts and instructions) and enable them for any agent
- **Real-time chat** — stream agent output in real time via Server-Sent Events; sessions persist across page refreshes
- **Persistent memory** — store, search, edit, and delete project knowledge, decisions, and notes across sessions
- **Context assembly** — agents receive relevant context from session history, project-scoped memories, and AGENTS.md with configurable budget
- **Provider abstraction** — Junie CLI as the default provider; extensible via the `AgentProvider` interface
- **Tool permissions** — per-agent control over file read/write, command execution, Git ops, and network access
- **Git safety** — inspect Git status, branch, changed files, and untracked files; manage isolated worktrees for concurrent work
- **Multi-agent coordinator** — run multiple tasks concurrently with dependency resolution and worktree isolation per worker
- **Startup validation** — `/api/status` reports provider availability, missing projects, and configuration issues
- **Ollama integration** — optional local LLM for prompt refinement, summarization, and task decomposition
- **Obsidian integration** — optional vault integration for reading notes and writing session summaries
- **Remote execution** — dispatch agent runs to a remote machine via SSH with automatic project sync
- **Web dashboard** — browser-based UI for agent status, task submission, output viewing, and configuration management
- **CLI interface** — manage agents, runs, and skills from the command line via `agent-hub` command
- **Systemd service** — install as a background service on Linux with `install_service.sh`
- **Windows support** — run via PowerShell with `start.ps1`

### Packaging
- Added `pyproject.toml` for standard Python packaging
- Installable via `pip install .` with optional dev dependencies (`pip install .[dev]`)
- Console script entry point: `agent-hub`
- **Windows .exe** — standalone executable built with PyInstaller; no Python installation required (`build_exe.bat`)

---

### Links
[1.0.3]: https://github.com/LukaG712/Greenie/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/LukaG712/Greenie/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/LukaG712/Greenie/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/LukaG712/Greenie/releases/tag/v1.0.0
