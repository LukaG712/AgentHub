# Agent Hub

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/Version-1.0.1-green.svg)](CHANGELOG.md)

A self-hosted dashboard that lets you manage AI coding agents (JetBrains Junie CLI), share skills between them, and control everything from a web browser.  Runs entirely on your machine — no cloud, no paid APIs, no internet connection needed once it's set up.

## What it does

- **Manage agents** — define one or more AI agents, each with its own project folder and guidelines.
- **Shared skills** — create reusable skills (prompts and instructions) and enable them for any agent.
- **Real-time chat** — start conversations with agents and see output stream in real time as it's produced, not just after completion. Sessions persist across page refreshes.
- **Persistent memory** — store, search, edit, and delete project knowledge, decisions, and notes across sessions.
- **Context assembly** — agents receive relevant context from session history, project-scoped memories, and project instructions (AGENTS.md), with configurable budget and no cross-session leakage.
- **Provider abstraction** — Junie CLI is one provider; add others via the `AgentProvider` interface.
- **Tool permissions** — control file read/write, command execution, Git ops, and network access per agent. Permissions are displayed in the UI and enforced at execution.
- **Git safety** — inspect Git status, branch, changed files, and untracked files. Manage isolated worktrees for concurrent work without risking user changes.
- **Multi-agent coordinator** — run multiple tasks concurrently with dependency resolution, worktree isolation per worker, and explicit approval before integrating changes.
- **Startup validation** — `/api/status` reports provider availability, missing projects, and configuration issues.
- **Ollama integration** — optional local LLM for prompt refinement, summarization, and task decomposition.
- **Obsidian integration** — optional vault integration for reading notes and writing session summaries.
- **Remote execution** — dispatch agent runs to a remote machine via SSH with automatic project sync.
- **Web dashboard** — see agent status, send tasks, view output, and manage everything from a browser.
- **Run in the background** — install as a systemd service (Linux) or run via PowerShell (Windows).

## Works together with JunieOrchestrator

Agent Hub pairs well with [JunieOrchestrator](https://github.com/LukaG712/JunieOrchestrator).  In plain terms:

- **JunieOrchestrator** is the chat front door.  It sits behind Open WebUI, improves your prompts, and decides which agent to call.  It typically runs on port **8000**.
- **Agent Hub** is the workhorse.  It receives tasks from the orchestrator (or from the web dashboard) and runs the actual agents.  It runs on port **8080**.

Together they give you a full pipeline: chat → prompt improvement → agent execution → results.  You can use Agent Hub on its own too — the web dashboard lets you send tasks directly.

## Before you start

Make sure these are in place **before** running the setup:

1. **Python 3.11+** — Agent Hub runs on Linux and Windows.
2. **Junie installed** — install the [Junie CLI](https://junie.jetbrains.com) and make sure `junie` is on your PATH.
3. **Junie logged in** — log in to Junie (`junie --auth=...`) as the **same user** that will run the hub.  The agents reuse this login.
4. **Project directories ready** — if your agent works on an Obsidian vault, mount it at the path you'll put in `hub.yaml`.  For other agents, create the project folders first.
5. **Use a scratch copy first** — when testing, point agents at a copy of your data, not the real thing.

## Quick Start

The fastest way to get started — **one command** clones, sets up, and launches the dashboard:

### Linux / macOS

```bash
git clone https://github.com/LukaG712/AgentHub.git && cd AgentHub && ./start.sh
```

### Windows (PowerShell)

```powershell
git clone https://github.com/LukaG712/AgentHub.git; cd AgentHub; .\start.ps1
```

The start script automatically handles first-time setup (virtual environment, dependencies, API key generation, config file). Your browser will open to **http://localhost:8080** — enter the displayed API key when prompted.

> **Note:** [Junie CLI](https://junie.jetbrains.com) must be installed and on your PATH before running the start script.

## Installation

### Option 1: Windows .exe (no Python required)

> **Note:** You still need [Junie CLI](https://junie.jetbrains.com) installed and on your PATH for agents to work.

Download `agent-hub.exe` from the [latest release](https://github.com/LukaG712/AgentHub/releases/latest), then:

1. Copy `hub.example.yaml` to `hub.yaml` next to the .exe and edit it to configure your agents.
2. Create a `.env` file next to the .exe with `HUB_API_KEY=your-random-key-here`.
3. Run `agent-hub.exe serve` to start the server.

Open **http://localhost:8080** in your browser and enter the API key.

### Option 2: Clone and run

#### Linux

```bash
git clone https://github.com/LukaG712/AgentHub.git
cd AgentHub
./start.sh
```

The `start.sh` script runs setup automatically on first launch, then starts the server and opens your browser.

#### Windows

```powershell
git clone https://github.com/LukaG712/AgentHub.git
cd AgentHub
.\start.ps1
```

The `start.ps1` script runs setup automatically on first launch, then starts the server and opens your browser.

That's it.  The dashboard lets you edit agents, create skills, send tasks, chat with agents, and manage memories.

## Running in the background

To keep Agent Hub running after you log out, install it as a systemd service:

```bash
sudo ./install_service.sh
```

This creates a service that starts on boot, runs as your user (not root), and reads the API key from `.env`.

```bash
systemctl status agent-hub       # check status
journalctl -u agent-hub -f       # live logs
sudo systemctl stop agent-hub    # stop
```

## Configuration

### hub.yaml

The main config file.  The start script creates it from `hub.example.yaml` on first launch.  Edit it to change agents:

```yaml
runners:
  junie:
    command:
      - "junie"
      - "--task"
      - "{task}"
      - "--project"
      - "{project}"
      - "--output-format"
      - "json"
    skills_dir: ".junie/skills"
    guidelines_file: ".junie/AGENTS.md"

agents:
  vault:
    title: "Vault librarian"
    description: "Reads and updates the Obsidian vault notes."
    runner: junie
    project_dir: /mnt/vault
    skills:
      - vault-conventions
    guidelines: "Never delete files. New notes go in _ai/."
    permissions:
      file_read: true
      file_write: true
      command_exec: true
      git_ops: true
      network: true
```

- `{task}` and `{project}` are replaced automatically when a run starts.
- `permissions` is optional — all default to `true` when omitted. Set individual permissions to `false` to restrict what the agent can do.
- The web UI lets you edit agent properties (title, description, project_dir, skills, guidelines) without touching the file.  Runner commands can only be changed in `hub.yaml` directly — the UI and API never expose them.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HUB_CONFIG` | `./hub.yaml` | Path to config file |
| `HUB_API_KEY` | *(required)* | Bearer token for API auth (stored in `.env`) |
| `HUB_TIMEOUT` | `1800` | Max seconds per agent run |
| `HUB_PORT` | `8080` | Server port (used by start scripts) |
| `JUNIE_BIN` | — | Override the `junie` binary path |

### Ollama Integration (Optional)

Ollama provides optional prompt refinement, summarization, and task decomposition using a local LLM. It is **not required** — Agent Hub works perfectly without it.

1. Install [Ollama](https://ollama.ai) and pull a model:
   ```bash
   ollama pull llama3
   ```
2. Add the `ollama` section to `hub.yaml`:
   ```yaml
   ollama:
     enabled: true
     base_url: "http://localhost:11434"
     model: "llama3"
     timeout: 60
   ```
3. When sending a message via the API, include `refine_prompt: true` to have Ollama refine the prompt before agent execution:
   ```json
   {"content": "Fix the bug", "refine_prompt": true}
   ```

Ollama features:
- **Prompt refinement** — improves clarity and completeness before agent execution
- **Summarization** — condense long agent outputs or conversations
- **Task decomposition** — break complex tasks into ordered subtasks
- **Key point extraction** — extract important findings from agent output

If Ollama is unavailable, all operations gracefully fall back to the original input.

### Obsidian Integration (Optional)

Obsidian vault integration allows reading notes and writing session summaries. It is **not required**.

1. Add the `obsidian` section to `hub.yaml`:
   ```yaml
   obsidian:
     enabled: true
     vault_path: "/path/to/your/vault"
   ```
2. Use the API to list notes, read note content, and sync session summaries to your vault.

### Skills

Skills live in the `skills/` directory.  Each skill is a folder with a `SKILL.md` file:

```markdown
---
name: my-skill
description: Does something useful
---

Skill content here...
```

Enable a skill for an agent from the web dashboard or CLI.  The hub creates a symlink inside the agent's project folder so the agent sees the skill.  Disabling removes only hub-managed symlinks — your other files are never touched.

## Troubleshooting

### Junie not logged in or wrong user

Agents fail with an authentication error.  Make sure you ran `junie --auth=...` as the **same user** that runs the hub (check with `systemctl status agent-hub` → `User=` line).

### project_dir missing

The agent can't find its working folder.  Create the directory and make sure the hub user can read/write it:

```bash
mkdir -p /path/to/project
chown $USER:$USER /path/to/project
```

### Agent stuck "busy"

If an agent shows as Working but isn't doing anything, stop its current run from the dashboard or via:

```bash
agent-hub stop <run-id>
```

If the hub was killed while an agent was running, restart the service — it will clean up stale runs automatically.

## Safety Model

- **LAN only** — the server listens on `0.0.0.0`.  Don't expose it to the internet without a reverse proxy and proper auth.
- **Runner commands are locked** — only `hub.yaml` on disk controls how agents run.  The API and web UI cannot change command templates.
- **List-based commands** — all agent commands use list-based arguments, never shell-string interpolation, preventing injection attacks.
- **Project path validation** — project directories are validated to prevent agents from operating on sensitive system paths.
- **Bearer token** — all API calls require `HUB_API_KEY`.  The dashboard at `/` works without auth, but any action needs the key.
- **Name validation** — agent and skill names must match `^[a-z0-9][a-z0-9-]{0,40}$`.
- **Path safety** — skill paths are verified to stay within the skills directory.
- **Git safety** — AgentHub never discards user changes, resets branches, or merges automatically. Worktrees are isolated and cleaned up after rejected tasks.
- **Coordinator approval** — multi-agent tasks require explicit approval before marking worktree-based changes as complete. No automatic integration.
- **Secret filtering** — API keys and tokens are never logged or returned to the frontend.
- **Context isolation** — conversation history from one session never leaks into another session or project.

## CLI Commands

```bash
agent-hub agents                    # List agents
agent-hub run vault "..."           # Run a task (waits for result)
agent-hub run vault "..." --no-wait # Fail immediately if busy
agent-hub runs [agent]              # List runs
agent-hub stop <run-id>             # Stop a running agent
agent-hub skills                    # List skills
agent-hub skill-enable vault skill  # Enable a skill
agent-hub skill-disable vault skill # Disable a skill
agent-hub sync [agent]              # Sync skills and guidelines
agent-hub serve                     # Start the web server
agent-hub serve --port 9000         # Start on a custom port
agent-hub serve --reload            # Start with auto-reload
```

## How to Add Another Provider

The provider abstraction layer (`hub/providers.py`) lets you add new agent backends beyond Junie CLI.

1. Create a new provider class in `hub/providers.py`:
   ```python
   from hub.providers import AgentProvider, AgentPermissions, ProviderRunResult

   class MyAgentProvider(AgentProvider):
       @property
       def name(self):
           return "myagent"

       def check_available(self):
           import shutil
           return shutil.which("myagent") is not None

       def build_command(self, task, project_dir, permissions, extra_args=None):
           return ["myagent", "--task", task, "--project", project_dir]

       def run(self, task, project_dir, permissions, timeout=1800, extra_args=None):
           # Execute the agent and return a ProviderRunResult
           ...
   ```
2. Register it:
   ```python
   from hub.providers import register_provider
   register_provider(MyAgentProvider())
   ```
3. Create agents that reference `runner: myagent` in `hub.yaml` or via the API.

## Remote Execution

AgentHub can dispatch agent runs to a remote machine (e.g., a Proxmox VM) via SSH. The project is synced automatically before each run.

1. Configure an agent with `runner: ssh` and a `remote` section in `hub.yaml`:
   ```yaml
   agents:
     remote-builder:
       runner: ssh
       project_dir: "~/workspace/project"
       remote:
         host: "192.168.1.100"
         user: "deploy"
         key_path: "~/.ssh/id_ed25519"
         remote_project_dir: "/home/deploy/project"
   ```
2. The hub syncs the project directory to the remote host, then runs the agent command via SSH.
3. Check connectivity with `GET /api/remote/status`.

Requires an SSH client on the host machine and key-based authentication to the remote target.

## Git Integration

AgentHub provides Git status inspection and safe worktree management without modifying your working tree.

### Git Status

The `/api/git/status` endpoint reports the current branch, dirty state, changed files, staged changes, and untracked files for the selected project. The web dashboard displays this in a Git status panel.

### Worktree Management

The `/api/git/worktrees` endpoint lets you create and remove isolated Git worktrees. Each worktree gets its own branch and working directory, so concurrent agents never conflict.

**Safety guarantees:**
- AgentHub never discards your changes, resets branches, or merges automatically.
- Worktrees are cleaned up after rejected tasks; approved worktrees remain for manual review.
- Explicit approval is required before a worker's changes are marked complete.

## Multi-Agent Coordinator

The coordinator lets you run multiple agent tasks concurrently with dependency resolution and worktree isolation.

### How it works

1. **Create a coordinator** via the API or web UI, specifying a project and max concurrency.
2. **Add tasks** with names, descriptions, agent assignments, and optional dependencies.
3. **Execute** — tasks run concurrently when their dependencies are satisfied, each in its own isolated worktree.
4. **Review & approve** — when a task finishes, it enters `needs_approval` state. Approve to mark it complete, or reject to clean up its worktree.

### Task lifecycle

`PENDING` → `WAITING` (on dependencies) → `RUNNING` → `NEEDS_APPROVAL` → `COMPLETED` or `FAILED`

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/coordinator` | Create a new coordinator |
| GET | `/api/coordinator` | List all active coordinators |
| GET | `/api/coordinator/{id}` | Get coordinator details |
| DELETE | `/api/coordinator/{id}` | Delete a coordinator |
| POST | `/api/coordinator/{id}/tasks` | Add a task |
| DELETE | `/api/coordinator/{id}/tasks/{task_id}` | Remove a pending task |
| POST | `/api/coordinator/{id}/execute` | Start execution |
| POST | `/api/coordinator/{id}/cancel` | Cancel all tasks |
| POST | `/api/coordinator/{id}/tasks/{task_id}/approve` | Approve a task |
| POST | `/api/coordinator/{id}/tasks/{task_id}/reject` | Reject a task |

## Real-Time Streaming

AgentHub streams agent output in real time using Server-Sent Events (SSE). As the agent produces output, each line is sent to the browser immediately — no waiting for the run to complete.

- **Reconnect support** — if the browser disconnects, reconnecting clients receive buffered events.
- **Bounded retention** — max 1000 events per run, cleaned up 30 seconds after completion.
- **Event isolation** — events from one run never leak into another session.

## Running Tests

```bash
python -m pytest tests/ -v
```

Tests use a fake agent script — no real `junie` binary needed.  POSIX-only tests (file locking, process groups) are skipped on Windows.

### Test coverage (348 tests)

| Area | Tests | What's covered |
|------|-------|----------------|
| Runner & streaming | ~80 | Subprocess output, incremental SSE events, timeouts, process cleanup, missing binaries, failed runs |
| API & SSE | ~70 | All API endpoints, SSE buffering, event isolation, coordinator endpoints |
| Memory & context | ~50 | Session CRUD, memory CRUD, context assembly, ordering, deduplication, truncation, project isolation |
| Providers & permissions | ~30 | Command safety, permission flags, list-based arguments |
| Git service | ~15 | Dirty detection, untracked files, worktree create/remove |
| Coordinator | ~38 | Task management, dependencies, approval workflow, worktree isolation, API endpoints |
| Config & skills | ~65 | Configuration loading, skill management, name validation, path safety |

## Web UI Manual Checks

- [ ] Dashboard shows agent cards grouped by state (Working, Idle, Failed)
- [ ] Clicking an agent opens the detail panel with run history
- [ ] Sending a task from the bottom bar dispatches a run
- [ ] Skills page lists skills with enable/disable matrix
- [ ] Dark/light mode follows system preference
- [ ] First visit prompts for API key
- [ ] No external URLs loaded (works offline)
- [ ] Chat shows incremental output in real time as the agent runs
- [ ] Session renaming works via double-click on session title
- [ ] Sessions persist after page refresh (localStorage)
- [ ] Memory page allows inline editing of memories
- [ ] Git status panel shows branch, changed files, and untracked files
- [ ] Coordinator view shows task plans, dependencies, and worker status
- [ ] Permission indicators (✓/✗) display for selected agent
- [ ] Auto-scroll respects manual scrolling in chat

## Manual Setup (Advanced)

If you prefer not to use the setup scripts, do these steps manually:

### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp hub.example.yaml hub.yaml
# Edit hub.yaml
export HUB_API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uvicorn hub.api:app --host 0.0.0.0 --port 8080
```

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy hub.example.yaml hub.yaml
# Edit hub.yaml
$env:HUB_API_KEY = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 43 | ForEach-Object {[char]$_})
python -m uvicorn hub.api:app --host 0.0.0.0 --port 8080
```
