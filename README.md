```
    e Y8b                                d8   888 888           888      
   d8b Y8b     e88 888  ,e e,  888 8e   d88   888 888 8888 8888 888 88e  
  d888b Y8b   d888 888 d88 88b 888 88b d88888 8888888 8888 8888 888 888b 
 d888888888b  Y888 888 888   , 888 888  888   888 888 Y888 888P 888 888P 
d8888888b Y8b  "88 888  "YeeP" 888 888  888   888 888  "88 88"  888 88"  
                ,  88P                                                   
               "8",P"                                                    
```

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/Version-dev-yellow.svg)](CHANGELOG.md)

> 🏠 **Self-hosted AI agent dashboard** — Manage AI coding agents (JetBrains Junie CLI), share reusable skills between them, and control everything from a web browser. Runs entirely on your machine with no cloud, no paid APIs, and no internet connection needed once it's set up.

## ✨ Features

Everything you need to manage AI coding agents from one place:

| Category | Feature | Description |
|----------|---------|-------------|
| 🤖 **Agents** | Multi-agent management | Define agents with unique project folders, runners, and guidelines |
| 🧠 **Skills** | Shared skill library | Create reusable prompts and enable them for any agent |
| 💬 **Chat** | Real-time streaming | See agent output as it happens via Server-Sent Events (SSE) |
| 💾 **Memory** | Persistent knowledge | Store, search, and edit project notes that survive restarts |
| 📦 **Context** | Smart context assembly | Agents get relevant history, memories, and instructions automatically |
| 🔌 **Providers** | Extensible backends | Junie CLI is the default; add more via the `AgentProvider` interface |
| 🔒 **Permissions** | Per-agent controls | Toggle file read/write, command execution, Git ops, and network access |
| 🌿 **Git** | Safe Git integration | Inspect status and manage isolated worktrees without risking your work |
| 🎯 **Coordinator** | Multi-agent tasks | Run concurrent tasks with dependency resolution and approval workflow |
| 🏥 **Health** | Startup validation | `/api/status` checks providers, projects, and config on boot |
| 🦙 **Ollama** | Local LLM support | Optional prompt refinement and summarization with local models |
| 📓 **Obsidian** | Vault integration | Read notes and write session summaries to your Obsidian vault |
| 🌐 **Remote** | SSH execution | Dispatch agent runs to remote machines with automatic project sync |
| 🖥️ **Dashboard** | Web UI | Browser-based interface for all agent management tasks |
| ⚙️ **Background** | Service mode | Run as a systemd service (Linux) or via PowerShell (Windows) |

## �- How it Works with JunieOrchestrator

Agent Hub pairs perfectly with [JunieOrchestrator](https://github.com/LukaG712/JunieOrchestrator) for a complete AI pipeline. Think of it this way:

| Component | Role | Port |
|-----------|------|------|
| **JunieOrchestrator** | 🚪 The chat front door — improves your prompts and routes them to the right agent | `8000` |
| **Agent Hub** | 🏭 The workhorse — receives tasks and runs the actual agents | `8080` |

**The full pipeline:** Chat → Prompt improvement → Agent execution → Results

> 💡 **You can use Agent Hub on its own** — the web dashboard lets you send tasks directly without the orchestrator.

## 🚀 Quick Start

Getting started takes **one command** — it clones the repo, sets up everything, and launches the dashboard automatically:

### 🐧 Linux / macOS

```bash
git clone https://github.com/LukaG712/AgentHub.git && cd AgentHub && ./start.sh
```

### 🪟 Windows (PowerShell)

```powershell
git clone https://github.com/LukaG712/AgentHub.git; cd AgentHub; .\start.ps1
```

### What happens next?

The script handles everything automatically on first run:

1. ✅ **Checks** that Python 3.11+ is installed
2. 📦 **Creates** a virtual environment and installs all dependencies
3. ⚙️ **Generates** a config file (`hub.yaml`) and a random API key
4. 🌐 **Starts** the server and opens your browser to **http://localhost:8080**

Enter the displayed API key when prompted in the browser, then edit `hub.yaml` to configure your agents.

> 💡 **Tip:** [Junie CLI](https://junie.jetbrains.com) is needed for agents to actually run, but you can explore the dashboard first and install it later.

---

### 🪟 Windows .exe (no Python required)

Don't want to install Python? Download `agent-hub.exe` from the [latest release](https://github.com/LukaG712/AgentHub/releases/latest):

1. Download `agent-hub.exe` and `hub.example.yaml`
2. Copy `hub.example.yaml` → `hub.yaml` and configure your agents
3. Create a `.env` file with `HUB_API_KEY=your-random-key-here`
4. Run `agent-hub.exe serve`

> ⚠️ **Note:** You still need [Junie CLI](https://junie.jetbrains.com) on your system PATH for agents to work.

---

### ✅ Before You Run Your First Agent

Make sure these three things are set up:

| Step | What to do | Why |
|------|------------|-----|
| 1️⃣ **Install Junie CLI** | Download from [junie.jetbrains.com](https://junie.jetbrains.com) and log in with `junie --auth=...` | Agents need Junie to run tasks |
| 2️⃣ **Configure agents** | Edit `hub.yaml` and set `project_dir` for each agent | Tells agents where to work |
| 3️⃣ **Use a scratch copy** | Point agents at a copy of your code, not your real project | Safety first — test before trusting |

## ⚙️ Running in the Background

Want Agent Hub to keep running after you close your terminal?

### 🐧 Linux (Systemd Service)

Install as a background service that starts automatically on boot:

```bash
sudo ./install_service.sh
```

**Manage the service:**

```bash
systemctl status agent-hub       # 👀 Check if it's running
journalctl -u agent-hub -f       # 📋 View live logs
sudo systemctl stop agent-hub    # 🛑 Stop the service
```

The service runs as your user (not root) and reads the API key from `.env`.

### 🪟 Windows

On Windows, run `.\start.ps1` in a console window or configure [Task Scheduler](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-start-page) to keep it running.

## ⚙️ Configuration

### 📄 hub.yaml

The main config file — the start script creates it from `hub.example.yaml` on first launch. Edit it to configure your agents:

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

**Key concepts:**

| Setting | What it does |
|---------|--------------|
| `{task}` / `{project}` | Automatically replaced with the actual task and project path when a run starts |
| `permissions` | Optional — all default to `true`. Set to `false` to restrict what an agent can do |
| **Web UI edits** | You can change title, description, project_dir, skills, and guidelines from the dashboard — no file editing needed |
| **Runner commands** | Can only be changed in `hub.yaml` directly for security — the UI and API never expose them |

---

### 🔑 Environment Variables

Settings that control how Agent Hub runs. Store sensitive values like your API key in the `.env` file.

| Variable | Default | Description |
|----------|---------|-------------|
| `HUB_CONFIG` | `./hub.yaml` | Path to your config file |
| `HUB_API_KEY` | *(required)* | 🔐 Bearer token for API authentication — stored in `.env` |
| `HUB_TIMEOUT` | `1800` | ⏱️ Maximum seconds per agent run (30 minutes) |
| `HUB_PORT` | `8080` | 🌐 Server port number |
| `JUNIE_BIN` | — | 🔧 Override the default `junie` binary path |

### 🦙 Ollama Integration (Optional)

Ollama adds AI-powered prompt refinement, summarization, and task decomposition using a **local** LLM. It is **completely optional** — Agent Hub works perfectly without it.

**Setup in 3 steps:**

1. **Install Ollama** and download a model:
   ```bash
   ollama pull llama3
   ```
2. **Add the config** to `hub.yaml`:
   ```yaml
   ollama:
     enabled: true
     base_url: "http://localhost:11434"
     model: "llama3"
     timeout: 60
   ```
3. **Use it** — when sending a message via the API, include `refine_prompt: true`:
   ```json
   {"content": "Fix the bug", "refine_prompt": true}
   ```

**What Ollama can do:**

| Feature | Description |
|---------|-------------|
| ✍️ **Prompt refinement** | Improves clarity and completeness before agent execution |
| 📝 **Summarization** | Condenses long agent outputs or conversations |
| 🧩 **Task decomposition** | Breaks complex tasks into ordered subtasks |
| 🔑 **Key point extraction** | Pulls important findings from agent output |

> 💡 If Ollama is unavailable, all operations gracefully fall back to the original input — no errors.

---

### 📓 Obsidian Integration (Optional)

Connect your Obsidian vault to read notes and write session summaries. **Not required** for core functionality.

**Setup:**

1. Add the `obsidian` section to `hub.yaml`:
   ```yaml
   obsidian:
     enabled: true
     vault_path: "/path/to/your/vault"
   ```
2. Use the API to list notes, read note content, and sync session summaries to your vault.

---

### 🧠 Skills

Skills are reusable prompts and instructions that you can share across agents. They live in the `skills/` directory, with each skill being a folder containing a `SKILL.md` file:

```markdown
---
name: my-skill
description: Does something useful
---

Skill content here...
```

**How skills work:**

| Action | What happens |
|--------|--------------|
| **Enable** | The hub creates a symlink inside the agent's project folder so the agent sees the skill |
| **Disable** | Removes only the hub-managed symlink — your other files are never touched |

Enable or disable skills for any agent from the **web dashboard** or **CLI**. Skills are the best way to give agents consistent behavior across projects.

## 🐛 Troubleshooting

Common issues and how to fix them:

### 🔐 Junie not logged in or wrong user

**Symptom:** Agents fail with an authentication error.

**Fix:** Make sure you ran `junie --auth=...` as the **same user** that runs the hub. Check which user the hub runs as:
```bash
systemctl status agent-hub  # Look for the `User=` line
```

### 📁 `project_dir` missing

**Symptom:** The agent can't find its working folder.

**Fix:** Create the directory and ensure the hub user has read/write access:
```bash
mkdir -p /path/to/project
chown $USER:$USER /path/to/project
```

### ⏸️ Agent stuck "busy"

**Symptom:** An agent shows as "Working" but isn't doing anything.

**Fix:** Stop its current run from the dashboard or via CLI:
```bash
agent-hub stop <run-id>
```

If the hub was killed while an agent was running, simply restart the service — it will clean up stale runs automatically.

## 🔒 Safety & Security

Agent Hub is designed to be safe to run on your local machine. Here's how it protects you:

| Protection | How it works |
|------------|--------------|
| 🏠 **LAN only** | Server listens on `0.0.0.0` — don't expose it to the internet without a reverse proxy |
| 🔒 **Locked runner commands** | Only `hub.yaml` on disk controls how agents run — the API and UI can't change them |
| 🛡️ **List-based commands** | All agent commands use list arguments, never shell strings — prevents injection attacks |
| 📂 **Path validation** | Project directories are validated to prevent agents from accessing sensitive system paths |
| 🔑 **Bearer token auth** | All API calls require `HUB_API_KEY` — the dashboard view works without auth, but actions require it |
| ✅ **Name validation** | Agent and skill names must match `^[a-z0-9][a-z0-9-]{0,40}$` — no special characters |
| 🛡️ **Path safety** | Skill paths are verified to stay within the skills directory — no escaping |
| 🌿 **Git safety** | AgentHub never discards your changes, resets branches, or merges automatically |
| ✅ **Coordinator approval** | Multi-agent tasks require explicit approval before changes are marked complete |
| 🔇 **Secret filtering** | API keys and tokens are never logged or returned to the frontend |
| 🧱 **Context isolation** | Conversation history from one session never leaks into another session or project |

## 💻 CLI Commands

All commands are available via the `agent-hub` command line tool:

| Command | Description |
|---------|-------------|
| **Agent management** | |
| `agent-hub agents` | 📋 List all configured agents |
| `agent-hub run <agent> "..."` | 🚀 Run a task (waits for the result) |
| `agent-hub run <agent> "..." --no-wait` | ⚡ Run a task, fail immediately if agent is busy |
| `agent-hub runs [agent]` | 📜 List run history (optionally filter by agent) |
| `agent-hub stop <run-id>` | 🛑 Stop a running agent |
| **Skills** | |
| `agent-hub skills` | 📋 List all available skills |
| `agent-hub skill-enable <agent> <skill>` | ✅ Enable a skill for an agent |
| `agent-hub skill-disable <agent> <skill>` | ❌ Disable a skill for an agent |
| `agent-hub sync [agent]` | 🔄 Sync skills and guidelines to agent projects |
| **Server** | |
| `agent-hub serve` | 🌐 Start the web server on default port (8080) |
| `agent-hub serve --port 9000` | 🌐 Start on a custom port |
| `agent-hub serve --reload` | 🔄 Start with auto-reload for development |

## 🔌 How to Add Another Provider

The provider abstraction layer (`hub/providers.py`) lets you add new agent backends beyond Junie CLI. Follow these 3 steps:

**1. Create a provider class** in `hub/providers.py`:
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
**2. Register it:**
   ```python
   from hub.providers import register_provider
   register_provider(MyAgentProvider())
   ```
**3. Use it** — create agents that reference `runner: myagent` in `hub.yaml` or via the API.

---

## 🌐 Remote Execution

Run agents on a remote machine (e.g., a Proxmox VM) via SSH. The project is synced automatically before each run.

**Setup:**

1. **Configure** an agent with `runner: ssh` and a `remote` section in `hub.yaml`:
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
2. **Run** — the hub syncs the project directory to the remote host, then runs the agent command via SSH.
3. **Verify** — check connectivity with `GET /api/remote/status`.

> ⚠️ **Requirements:** SSH client on the host machine and key-based authentication to the remote target.

## 🌿 Git Integration

AgentHub provides Git status inspection and safe worktree management — **your working tree is never modified**.

### 📊 Git Status

The `/api/git/status` endpoint reports everything about your current Git state:

- Current branch name
- Dirty state (modified files)
- Changed and staged files
- Untracked files

The web dashboard displays all this information in a dedicated Git status panel.

### 🌳 Worktree Management

The `/api/git/worktrees` endpoint lets you create and remove isolated Git worktrees. Each worktree gets its own branch and working directory, so concurrent agents never conflict.

**Safety guarantees:**

| Guarantee | What it means |
|-----------|---------------|
| 🛡️ **No data loss** | AgentHub never discards your changes, resets branches, or merges automatically |
| 🧹 **Clean cleanup** | Worktrees are automatically cleaned up after rejected tasks |
| ✅ **Explicit approval** | A worker's changes must be approved before being marked complete |

---

## 🎯 Multi-Agent Coordinator

Run multiple agent tasks at the same time with dependency resolution and isolated worktrees. Perfect for complex projects where tasks depend on each other.

### How it works

| Step | Action | Description |
|------|--------|-------------|
| 1️⃣ | **Create** | Create a coordinator via the API or web UI, specifying a project and max concurrency |
| 2️⃣ | **Add tasks** | Define tasks with names, descriptions, agent assignments, and optional dependencies |
| 3️⃣ | **Execute** | Tasks run concurrently when dependencies are met, each in its own isolated worktree |
| 4️⃣ | **Review & approve** | Finished tasks enter `needs_approval` — approve to complete, or reject to clean up |

### Task lifecycle

```
PENDING → WAITING (on dependencies) → RUNNING → NEEDS_APPROVAL → COMPLETED or FAILED
```

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/coordinator` | 🆕 Create a new coordinator |
| GET | `/api/coordinator` | 📋 List all active coordinators |
| GET | `/api/coordinator/{id}` | 🔍 Get coordinator details |
| DELETE | `/api/coordinator/{id}` | �-�️ Delete a coordinator |
| POST | `/api/coordinator/{id}/tasks` | ➕ Add a task |
| DELETE | `/api/coordinator/{id}/tasks/{task_id}` | ➖ Remove a pending task |
| POST | `/api/coordinator/{id}/execute` | 🚀 Start execution |
| POST | `/api/coordinator/{id}/cancel` | 🛑 Cancel all tasks |
| POST | `/api/coordinator/{id}/tasks/{task_id}/approve` | ✅ Approve a task |
| POST | `/api/coordinator/{id}/tasks/{task_id}/reject` | ❌ Reject a task |

## ⚡ Real-Time Streaming

AgentHub streams agent output to your browser in real time using **Server-Sent Events (SSE)**. As the agent produces output, each line appears immediately — no waiting for the run to complete.

**Key features:**

| Feature | Description |
|---------|-------------|
| 🔁 **Reconnect support** | If the browser disconnects, reconnecting clients receive buffered events |
| 📦 **Bounded retention** | Max 1000 events per run, cleaned up 30 seconds after completion |
| 🧱 **Event isolation** | Events from one run never leak into another session |

---

## 🧪 Running Tests

Run the full test suite with:

```bash
python -m pytest tests/ -v
```

Tests use a fake agent script — **no real `junie` binary needed**. POSIX-only tests (file locking, process groups) are automatically skipped on Windows.

### Test coverage (348 tests)

| Area | Tests | What's covered |
|------|-------|----------------|
| 🏃 Runner & streaming | ~80 | Subprocess output, incremental SSE events, timeouts, process cleanup, missing binaries, failed runs |
| 🔌 API & SSE | ~70 | All API endpoints, SSE buffering, event isolation, coordinator endpoints |
| 🧠 Memory & context | ~50 | Session CRUD, memory CRUD, context assembly, ordering, deduplication, truncation, project isolation |
| 🔒 Providers & permissions | ~30 | Command safety, permission flags, list-based arguments |
| 🌿 Git service | ~15 | Dirty detection, untracked files, worktree create/remove |
| 🎯 Coordinator | ~38 | Task management, dependencies, approval workflow, worktree isolation, API endpoints |
| ⚙️ Config & skills | ~65 | Configuration loading, skill management, name validation, path safety |

---

## 🖥️ Web UI Manual Checks

Quality checklist for the web dashboard:

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
- [ ] Permission indicators (✓/�-) display for selected agent
- [ ] Auto-scroll respects manual scrolling in chat

---

## 🛠️ Manual Setup (Advanced)

Prefer not to use the start scripts? Follow these steps manually:

### 🐧 Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp hub.example.yaml hub.yaml
# Edit hub.yaml to configure your agents
echo "HUB_API_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" > .env
uvicorn hub.api:app --host 0.0.0.0 --port 8080
```

### 🪟 Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy hub.example.yaml hub.yaml
# Edit hub.yaml to configure your agents
$env:HUB_API_KEY = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 43 | ForEach-Object {[char]$_})
python -m uvicorn hub.api:app --host 0.0.0.0 --port 8080
```
