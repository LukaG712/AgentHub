# Agent Hub

A self-hosted dashboard that lets you manage AI coding agents (JetBrains Junie CLI), share skills between them, and control everything from a web browser.  Runs entirely on your machine — no cloud, no paid APIs, no internet connection needed once it's set up.

## What it does

- **Manage agents** — define one or more AI agents, each with its own project folder and guidelines.
- **Shared skills** — create reusable skills (prompts and instructions) and enable them for any agent.
- **Chat interface** — start conversations with agents, see live progress, and resume sessions later.
- **Persistent memory** — store and search project knowledge, decisions, and notes across sessions.
- **Provider abstraction** — Junie CLI is one provider; add others via the `AgentProvider` interface.
- **Tool permissions** — control file read/write, command execution, Git ops, and network access per agent.
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

1. **Python 3.10+** — Agent Hub runs on Linux and Windows.
2. **Junie installed** — install the [Junie CLI](https://junie.jetbrains.com) and make sure `junie` is on your PATH.
3. **Junie logged in** — log in to Junie (`junie --auth=...`) as the **same user** that will run the hub.  The agents reuse this login.
4. **Project directories ready** — if your agent works on an Obsidian vault, mount it at the path you'll put in `hub.yaml`.  For other agents, create the project folders first.
5. **Use a scratch copy first** — when testing, point agents at a copy of your data, not the real thing.

## Quick Start

### Linux

```bash
git clone https://github.com/LukaG712/AgentHub.git
cd AgentHub
./setup.sh
./start.sh
```

Then open **http://localhost:8080** in your browser and enter the API key that `setup.sh` printed.

### Windows

```powershell
git clone https://github.com/LukaG712/AgentHub.git
cd AgentHub
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file with your API key:

```
HUB_API_KEY=your-generated-key-here
```

Generate a key with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`

Copy the example config: `copy hub.example.yaml hub.yaml`, then edit `hub.yaml` to configure your agents.

Start the server:

```powershell
.\start.ps1
```

Then open **http://localhost:8080** in your browser and enter the API key.

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

The main config file.  `setup.sh` creates it from `hub.example.yaml`.  Edit it to change agents:

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
python -m hub.cli stop <run-id>
```

If the hub was killed while an agent was running, restart the service — it will clean up stale runs automatically.

## Safety Model

- **LAN only** — the server listens on `0.0.0.0`.  Don't expose it to the internet without a reverse proxy and proper auth.
- **Runner commands are locked** — only `hub.yaml` on disk controls how agents run.  The API and web UI cannot change command templates.
- **Bearer token** — all API calls require `HUB_API_KEY`.  The dashboard at `/` works without auth, but any action needs the key.
- **Name validation** — agent and skill names must match `^[a-z0-9][a-z0-9-]{0,40}$`.
- **Path safety** — skill paths are verified to stay within the skills directory.

## CLI Commands

```bash
python -m hub.cli agents                    # List agents
python -m hub.cli run vault "..."           # Run a task (waits for result)
python -m hub.cli run vault "..." --no-wait # Fail immediately if busy
python -m hub.cli runs [agent]              # List runs
python -m hub.cli stop <run-id>             # Stop a running agent
python -m hub.cli skills                    # List skills
python -m hub.cli skill-enable vault skill  # Enable a skill
python -m hub.cli skill-disable vault skill # Disable a skill
python -m hub.cli sync [agent]              # Sync skills and guidelines
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

## Running Tests

```bash
python -m pytest tests/ -v
```

Tests use a fake agent script — no real `junie` binary needed.  POSIX-only tests (file locking, process groups) are skipped on Windows.

## Web UI Manual Checks

- [ ] Dashboard shows agent cards grouped by state (Working, Idle, Failed)
- [ ] Clicking an agent opens the detail panel with run history
- [ ] Sending a task from the bottom bar dispatches a run
- [ ] Skills page lists skills with enable/disable matrix
- [ ] Dark/light mode follows system preference
- [ ] First visit prompts for API key
- [ ] No external URLs loaded (works offline)

## Manual Setup (Advanced)

If you prefer not to use `setup.sh`, do these steps manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp hub.example.yaml hub.yaml
# Edit hub.yaml
export HUB_API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uvicorn hub.api:app --host 0.0.0.0 --port 8080
```
