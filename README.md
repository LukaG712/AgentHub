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
| 🤖 **Agents** | Multi-agent management | Define agents (Bots) with unique project folders, runners, and guidelines |
| 🧠 **Skills** | Shared skill library | Create reusable prompts and enable them for any agent |
| 💬 **Chat** | Real-time streaming | See agent output as it happens via Server-Sent Events (SSE) |
| 💾 **Memory** | Persistent knowledge | Store, search, and edit project notes that survive restarts |
| 📌 **Persistence** | Thread survival | Conversations, runs, and messages persist in SQLite — survive page reloads and restarts |
| 🔵 **Unread tracking** | Blue dot indicators | Unread assistant replies show a blue dot in the sidebar; clears when you open the thread |
| 👀 **Previews** | Last-message preview | Sidebar shows the last message preview and activity time per Bot |
| ⏸️ **Pause/Resume** | Per-Bot control | Pause a Bot to halt queued tasks; resume to continue processing |
| 🔄 **Queueing** | Sequential per-Bot | Each Bot runs one task at a time; extra messages queue and display as "queued" |
| ⚡ **Parallel Bots** | Concurrent execution | Different Bots run simultaneously — only one task per Bot at a time |
| ⏱️ **Routines** | Scheduled tasks | Create recurring tasks for Bots with interval or cron-like schedules; enable/disable/run-now from the right panel |
| 🎓 **Teach a task** | Save runs as routines | Click "Save as routine" on any completed run to create a reusable routine with one click |
| 📂 **Sidebar grouping** | Schedule-based groups | Bots are grouped by routine schedule (Daily, Weekly, etc.) in the sidebar; falls back to Working/Recent |
| 🧠 **Bot Memory** | Per-Bot notes | Edit each Bot's memory in the right panel; propose updates that appear in the chat with an Undo button |
| ↩️ **Memory Undo** | Revert changes | Click "Undo" on any memory update system message to restore the previous memory content |
| 🔀 **Group Threads** | Multi-Bot threads | A thread can contain multiple Bots; hand off work between Bots with "Send to another Bot" button |
| 🤝 **Handoffs** | Bot-to-Bot delegation | Hand off tasks between Bots within the same thread; system messages show colored dots for each Bot; loop prevention limits max hops |
| ⚠️ **Approvals** | Human-in-the-loop | When auto-review detects sensitive actions, an inline Approve/Deny card appears in the chat; amber badge on the Bot's avatar shows pending approvals |
| 🔍 **Auto Review** | Sensitive action detection | Configurable pattern matching (git push, rm -rf, etc.) automatically flags sensitive actions for approval; toggle in the right panel |
| 🔌 **Plugins** | Per-Bot plugins | Toggle plugins per Bot in the right panel; plugin definitions live in `hub.yaml` |
| 🏪 **Marketplace** | Local Bot templates | Browse pre-configured Bot templates (Research, Night Shift, etc.) with search and category filters; click "Add" to create a Bot from a template |
| ✨ **New Bot from Sentence** | AI-assisted creation | Describe what a Bot should do in a sentence and get an auto-generated name and config; choose from suggestion cards or create from scratch |
| ⭐ **Primary Bot** | Go-to Bot | Mark one Bot as your Primary Bot — pinned at the top of the sidebar with a star badge; automatically gets a daily check-in routine that summarizes other Bots' activity |
| 🔔 **Notifications** | Browser alerts | Browser notifications when a Bot finishes or fails; permission requested on first visit |
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
| 🖥️ **Desktop App** | Windows client | Tauri-based desktop app that connects to the VM-hosted backend |
| 📦 **Portable** | No-install build | Portable `.zip` distribution — no admin privileges required |
| 📀 **Installer** | NSIS installer | Proper Windows installer with Start Menu shortcuts and clean uninstall |
| 🏥 **Health API** | Monitoring | `GET /api/health` and `GET /api/ready` for systemd and load balancer checks |
| 🌐 **CORS** | LAN access | Configurable CORS middleware for browser access from LAN devices |

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

### Production Mode

For production deployments (no auto-reload), use the `--production` flag:

```bash
./start.sh --production
```

```powershell
.\start.ps1 --production
```

You can also customize the bind address:

```bash
./start.sh --host 0.0.0.0 --production    # LAN access, production mode
./start.sh --host 127.0.0.1              # Localhost only, development mode
```

## 🖥️ VM Deployment

AgentHub is designed to run as a persistent service on a Linux VM (Ubuntu/Debian), accessible from your local network.

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    VM (Ubuntu/Debian)                    │
│                                                          │
│  systemd: agent-hub.service                              │
│  ┌──────────────────────────────────────────────────┐  │
│  │  FastAPI (uvicorn) on 0.0.0.0:8080              │  │
│  │  ┌───────────┐  ┌───────────┐  ┌────────────┐ │  │
│  │  │ REST API  │  │ SSE Stream│  │ Static UI  │ │  │
│  │  └───────────┘  └───────────┘  └────────────┘ │  │
│  │  ┌───────────┐  ┌───────────┐  ┌────────────┐ │  │
│  │  │ SQLite DB │  │ Run Queue │  │ Scheduler  │ │  │
│  │  └───────────┘  └───────────┘  └────────────┘ │  │
│  └──────────────────────────────────────────────────┘  │
│                                                          │
│  Data: data/hub.db, data/runs/, data/queue_state.json    │
│  Config: hub.yaml, .env (HUB_API_KEY)                    │
└─────────────────────────────────────────────────────────┘
         ▲                    ▲                    ▲
         │ HTTP/SSE           │ HTTP/SSE           │ HTTP
┌────────┴──────┐   ┌────────┴───────┐   ┌────────┴────────┐
│ Browser (LAN) │   │ Tauri Desktop  │   │ Other LAN device │
│ vm-ip:8080    │   │ App (Windows)  │   │ Browser          │
└───────────────┘   └────────────────┘   └─────────────────┘
```

### Deploy to VM

1. **Clone and set up** on the VM:

```bash
git clone https://github.com/LukaG712/AgentHub.git && cd AgentHub
./start.sh
```

2. **Install as systemd service**:

```bash
sudo ./install_service.sh
```

3. **Configure LAN access** in `hub.yaml`:

```yaml
cors:
  enabled: true
  origins:
    - "http://localhost:*"
    - "http://127.0.0.1:*"
    - "http://192.168.1.100:*"    # Your VM's LAN IP
```

4. **Open firewall** (Ubuntu/Debian with UFW):

```bash
sudo ufw allow 8080/tcp
```

5. **Find your VM's IP**:

```bash
hostname -I | awk '{print $1}'
```

6. **Access from your network**: Open `http://<vm-ip>:8080` in any browser on your LAN.

### Service Management

```bash
systemctl status agent-hub       # Check status
journalctl -u agent-hub -f       # Live logs
sudo systemctl restart agent-hub # Restart
sudo systemctl stop agent-hub    # Stop
```

### Health Checks

The service includes health and readiness endpoints:

- `GET /api/health` — Returns `{"status": "ok", "version": "1.0.3"}` (unauthenticated)
- `GET /api/ready` — Checks SQLite and config validity (returns 503 if not ready)

### Backup & Restore

```bash
# Backup
tar czf agent-hub-backup.tar.gz data/ hub.yaml .env

# Restore
tar xzf agent-hub-backup.tar.gz
sudo systemctl restart agent-hub
```

### Update Procedure

```bash
cd /path/to/AgentHub
git pull
./start.sh --production    # Or: sudo systemctl restart agent-hub
```

The database and configuration are preserved across updates.

## 🖥️ Desktop App (Windows)

AgentHub Desktop is a lightweight Windows client built with Tauri that connects to the VM-hosted backend. It uses the system WebView2 to load the remote AgentHub UI directly — no iframe, no local backend.

### How It Works

The desktop app navigates the WebView directly to your VM's AgentHub URL. After connection validation via the Rust backend, it injects the API key as a cookie scoped to the server's origin. All API calls and SSE streaming work natively through the WebView.

### Features

- **First-run setup**: Enter your VM URL and API key
- **Direct WebView navigation**: No iframe — the remote UI loads natively
- **Secure authentication**: API key stored in Tauri's store, injected as cookie after navigation
- **Connection validation**: Rust backend checks `/api/health` before connecting
- **Graceful close**: Closing the app does not affect the VM backend or running tasks
- **Settings persistence**: Stored in `%APPDATA%\agent-hub-desktop\`
- **No local backend**: Pure client — all work runs on the VM

### Build from Source

**Prerequisites:**
- [Rust](https://rustup.rs/)
- [Node.js](https://nodejs.org/) (for Tauri CLI)
- WebView2 Runtime (pre-installed on Windows 10+)

```powershell
cd desktop
npm install
npm run build
```

**Build output:**
- **Installer**: `src-tauri/target/release/bundle/nsis/AgentHub Desktop Setup X.X.X.exe`
- **Portable**: Created by CI as `AgentHub-Portable-Windows-x64.zip`

### First-Run Flow

1. App launches → shows settings page
2. Enter VM URL (e.g., `http://192.168.1.100:8080`) and API key
3. App validates connection via `/api/health` (Rust backend, no CORS issues)
4. On success, WebView navigates to the remote AgentHub UI with cookie auth
5. On failure, shows error and allows retry

### Portable vs Installer

| Feature | Portable | Installer |
|---------|----------|-----------|
| Installation | None — just extract | NSIS installer |
| Admin required | No | No (per-user) |
| Start Menu shortcut | No | Yes |
| Settings location | `%APPDATA%` | `%APPDATA%` |
| Uninstaller | Delete folder | Clean uninstaller |

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
| 🏠 **Localhost by default** | Server binds to `127.0.0.1` by default — use `--host 0.0.0.0` only for intentional LAN exposure |
| 🔒 **Locked runner commands** | Only `hub.yaml` on disk controls how agents run — the API and UI can't change them |
| 🛡️ **List-based commands** | All agent commands use list arguments, never shell strings — prevents injection attacks |
| 📂 **Path validation** | Project directories are validated to prevent agents from accessing sensitive system paths |
| 🔑 **Bearer token auth** | All API calls require `HUB_API_KEY` — the dashboard view works without auth, but actions require it |
| 🚫 **Rate limiting** | Auth failures are rate-limited (10/min per IP) — prevents brute-force attacks on the API key |
| 🍪 **Cookie-based SSE auth** | SSE streaming uses cookies instead of query parameters — avoids logging API keys in server/proxy logs |
| 🔐 **SSH host key checking** | SSH connections verify host keys by default — set `strict_host_key_checking: false` in `hub.yaml` to disable |
| ✅ **Name validation** | Agent and skill names must match `^[a-z0-9][a-z0-9-]{0,40}$` — no special characters |
| 🛡️ **Path safety** | Skill paths are verified to stay within the skills directory — no escaping |
| 🌿 **Git safety** | AgentHub never discards your changes, resets branches, or merges automatically |
| ✅ **Coordinator approval** | Multi-agent tasks require explicit approval before changes are marked complete |
| 🔇 **Secret filtering** | API keys and tokens are never logged or returned to the frontend |
| 🧱 **Context isolation** | Conversation history from one session never leaks into another session or project |
| 🔒 **Config locking** | Concurrent config updates are serialized with a threading lock — prevents lost updates |
| 💾 **Queue persistence** | Queued tasks survive server restarts — state is persisted to `data/queue_state.json` |

**Permissions note:** Agent permissions (file read/write, command execution, etc.) are passed as CLI flags to the provider. Whether they are enforced depends on the provider implementation — Junie CLI respects these flags, but custom providers may not.

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
| `agent-hub serve` | 🌐 Start the web server on localhost:8080 |
| `agent-hub serve --port 9000` | 🌐 Start on a custom port |
| `agent-hub serve --host 0.0.0.0` | 🌐 Expose to local network (default is localhost only) |
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

Quality checklist for the messenger-style web UI:

### Layout & Navigation
- [ ] Three-column layout: sidebar (260px), chat thread (flex), right panel (300px, toggleable)
- [ ] Left sidebar shows Bot list with avatars (initials + color), name, description, and status dots
- [ ] Status dots: green = Working, gray = Idle, red = Failed, amber = Paused
- [ ] Blue unread dot appears on sidebar rows when assistant replies arrive while thread is closed
- [ ] Unread dot clears when you open the thread
- [ ] Last-message preview shown in sidebar (from session data, not agent description)
- [ ] Last-activity time shown right-aligned in sidebar ("8:20 AM", "Yesterday", "9/1")
- [ ] Bots grouped by "Working" and "Recent" in sidebar (fallback when no routines)
- [ ] Bots grouped by routine schedule (Daily, Weekly, etc.) when routines exist
- [ ] Bots without routines appear under "Unassigned" group
- [ ] "+ New Bot" button at top of sidebar opens the New Bot page
- [ ] "Marketplace" link in sidebar footer navigates to the Marketplace page
- [ ] Search/filter field appears when 5+ Bots are configured
- [ ] Skills link in sidebar navigates to Skills page (`#skills` hash route)
- [ ] Right panel toggle button in header shows/hides the panel
- [ ] Pause/Resume button in right panel toggles Bot pause state
- [ ] Queue length shown in thread header status ("Working (2 queued)")
- [ ] "Save as routine" button appears on completed run cards in the chat
- [ ] Clicking "Save as routine" prompts for a name and creates the routine
- [ ] Creating a routine appends a "Created routine ⏱ <name>" system message in the chat
- [ ] Memory section in right panel shows editable textarea with Save button
- [ ] "Propose update" button in Memory section creates a memory update system message in the chat
- [ ] Memory update appears as a card with "Updated memory for <Bot>" and an Undo button
- [ ] Clicking "Undo" restores the previous memory content and shows "Undid memory update" message
- [ ] "Send to another Bot" button appears on completed run cards
- [ ] Clicking "Send to another Bot" opens a dialog listing other Bots
- [ ] Selecting a Bot in the dialog hands off the task and shows a handoff system message
- [ ] Handoff system message displays colored dots for both Bots involved
- [ ] Handoff reply appears as a card showing the responding Bot's name and content
- [ ] Group thread header shows participant avatars when session has multiple Bots
- [ ] Handoff loop prevention rejects handoffs after max hops (default 5)
- [ ] Auto-review detects sensitive actions in run output and creates approval requests
- [ ] Approval requests appear as inline cards with Approve and Deny buttons in the chat
- [ ] Clicking Approve/Deny resolves the approval and shows a resolution system message
- [ ] Amber badge appears on the Bot's avatar in the sidebar when approvals are pending
- [ ] "Auto Review" section in the right panel has a toggle to enable/disable auto-review
- [ ] Pending approvals are listed in the right panel with Approve/Deny buttons
- [ ] Approval resolved messages show green (approved) or red (denied) styling
- [ ] Primary Bot shows a star badge (★) on its avatar in the sidebar
- [ ] Primary Bot is pinned at the top of the sidebar under a "Primary" group label
- [ ] Right panel shows "Set as Primary Bot" / "Clear as Primary" button for the selected Bot
- [ ] Clicking "Set as Primary Bot" pins the Bot and creates a "Daily Check-in" routine
- [ ] Clicking "Clear as Primary" removes the Primary Bot designation
- [ ] Browser notification permission is requested on first visit
- [ ] Browser notification appears when a Bot's task finishes
- [ ] Browser notification appears when a Bot's task fails

### Chat Thread
- [ ] Selecting a Bot loads its chat session (auto-creates session if none exists)
- [ ] User messages appear as right-aligned blue bubbles
- [ ] Bot messages appear as left-aligned gray bubbles
- [ ] Run messages show: status (Working/Done/Failed), elapsed time, task, collapsible output, and answer
- [ ] Stop button visible while a run is "Working"
- [ ] SSE streaming: output appears incrementally in the chat thread
- [ ] Composer at bottom: Enter sends, Shift+Enter for newline, auto-resize textarea
- [ ] Auto-scroll to bottom on new messages, respects manual scrolling

### Right Panel
- [ ] Bot section: displays name, title, and description
- [ ] Runner name shown (read-only, never editable)
- [ ] Project Directory: editable field with Save button
- [ ] Guidelines: editable textarea with Save button
- [ ] Skills: checkboxes for each skill, toggles enable/disable for current Bot
- [ ] Run History: clickable list of recent runs, opens run detail modal
- [ ] Memory section: editable textarea with Save and "Propose update" buttons
- [ ] Routines section: lists routines with enable/disable toggle, run-now, and delete buttons
- [ ] Routines section: "+ New Routine" button opens inline form for creating routines
- [ ] Plugins section: lists available plugins with enable/disable toggle per Bot

### New Bot Page
- [ ] "Describe the job in a sentence" field auto-generates a name
- [ ] Editable fields: name, title, runner (select), project directory, guidelines
- [ ] Name validation: `^[a-z0-9][a-z0-9-]{0,40}$` pattern with error message
- [ ] Runner command template is never shown or editable
- [ ] Submit creates the Bot and navigates to its chat
- [ ] Avatar customization: color swatches and shape buttons with live preview
- [ ] Suggestions grid shows pre-configured Bot templates to quickly start
- [ ] Clicking a suggestion fills the form with that template's info

### Marketplace Page
- [ ] Marketplace page lists Bot templates as cards with title, description, and "Add" button
- [ ] Search field filters templates by name and description
- [ ] Category chips (All, Development, Operations, Data) filter templates
- [ ] Clicking "Add" creates a Bot from the template and refreshes the sidebar
- [ ] Empty state shows "Templates will be available soon" when no templates exist

### Skills Page
- [ ] Skill cards with name, description, and "used by" info
- [ ] Create/Edit/Delete skill forms
- [ ] Enable/Disable matrix: skills as rows, Bots as columns with checkboxes

### Dark/Light Mode & Responsive
- [ ] Dark/light mode follows system preference (`prefers-color-scheme`)
- [ ] All components respect CSS custom properties in both modes
- [ ] At 768px: right panel hides, accessible as mobile sheet
- [ ] At 480px: sidebar becomes slide-over drawer with hamburger toggle
- [ ] Touch-friendly tap targets on mobile

### Accessibility
- [ ] Keyboard navigation: Tab through sidebar, Enter to select Bot, Escape to close dialogs
- [ ] ARIA labels on interactive elements
- [ ] Focus visible styles on all interactive elements
- [ ] Sufficient color contrast (WCAG AA)

### General
- [ ] First visit prompts for API key, stored in localStorage
- [ ] No external URLs, fonts, CDNs, or tracking (works offline)
- [ ] SSE auto-reconnects after 3s if connection drops during active run
- [ ] Run detail modal shows: state, task, error, answer, output, log file

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
