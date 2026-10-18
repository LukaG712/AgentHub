# Agent Hub

A self-hosted dashboard that lets you manage AI coding agents (JetBrains Junie CLI), share skills between them, and control everything from a web browser.  Runs entirely on your machine — no cloud, no paid APIs, no internet connection needed once it's set up.

## What it does

- **Manage agents** — define one or more AI agents, each with its own project folder and guidelines.
- **Shared skills** — create reusable skills (prompts and instructions) and enable them for any agent.
- **Web dashboard** — see agent status, send tasks, view output, and manage everything from a browser.
- **Run in the background** — install as a systemd service that starts automatically on boot.

## Works together with JunieOrchestrator

Agent Hub pairs well with [JunieOrchestrator](https://github.com/LukaG712/JunieOrchestrator).  In plain terms:

- **JunieOrchestrator** is the chat front door.  It sits behind Open WebUI, improves your prompts, and decides which agent to call.  It typically runs on port **8000**.
- **Agent Hub** is the workhorse.  It receives tasks from the orchestrator (or from the web dashboard) and runs the actual agents.  It runs on port **8080**.

Together they give you a full pipeline: chat → prompt improvement → agent execution → results.  You can use Agent Hub on its own too — the web dashboard lets you send tasks directly.

## Before you start

Make sure these are in place **before** running the setup:

1. **Linux machine** — Agent Hub runs on Linux (tested on Debian/Ubuntu).  A Raspberry Pi 4 or any small VPS works fine.
2. **Junie installed** — install the [Junie CLI](https://junie.jetbrains.com) and make sure `junie` is on your PATH.
3. **Junie logged in** — log in to Junie (`junie --auth=...`) as the **same Linux user** that will run the hub.  The agents reuse this login.
4. **Project directories ready** — if your agent works on an Obsidian vault, mount it at the path you'll put in `hub.yaml`.  For other agents, create the project folders first.
5. **Use a scratch copy first** — when testing, point agents at a copy of your data, not the real thing.

## Quick Start

```bash
git clone https://github.com/LukaG712/AgentHub.git
cd AgentHub
./setup.sh
./start.sh
```

Then open **http://localhost:8080** in your browser and enter the API key that `setup.sh` printed.

That's it.  The dashboard lets you edit agents, create skills, and send tasks.

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
```

- `{task}` and `{project}` are replaced automatically when a run starts.
- The web UI lets you edit agent properties (title, description, project_dir, skills, guidelines) without touching the file.  Runner commands can only be changed in `hub.yaml` directly — the UI and API never expose them.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HUB_CONFIG` | `./hub.yaml` | Path to config file |
| `HUB_API_KEY` | *(required)* | Bearer token for API auth (stored in `.env`) |
| `HUB_TIMEOUT` | `1800` | Max seconds per agent run |
| `JUNIE_BIN` | — | Override the `junie` binary path |

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

## How to Add Another Runner

1. Add a new entry under `runners:` in `hub.yaml`:
   ```yaml
   runners:
     myagent:
       command: ["myagent", "--do", "{task}", "--in", "{project}"]
       skills_dir: ".myagent/skills"
       guidelines_file: ".myagent/GUIDE.md"
   ```
2. Create agents that reference `runner: myagent`.

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
