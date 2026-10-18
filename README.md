# Agent Hub

A self-hosted dashboard for managing CLI coding agents (JetBrains Junie CLI), a shared skill library, and a web UI — all free, local, and offline-capable.

## Install

```bash
pip install -r requirements.txt
```

## Quick Start

1. Copy the example config:
   ```bash
   cp hub.example.yaml hub.yaml
   ```
2. Edit `hub.yaml` to set your agents' `project_dir` and other settings.
3. Set an API key and start the server:
   ```bash
   export HUB_API_KEY="your-secret-key"
   uvicorn hub.api:app --host 0.0.0.0 --port 8080
   ```
4. Open `http://localhost:8080` in your browser and enter the API key.

## systemd Service (Linux)

```ini
[Unit]
Description=Agent Hub
After=network.target

[Service]
Type=simple
User=%i
Environment=HOME=%h
Environment=HUB_API_KEY=your-secret-key
WorkingDirectory=/path/to/agent-hub
ExecStart=/path/to/venv/bin/uvicorn hub.api:app --host 0.0.0.0 --port 8080
Restart=on-failure

[Install]
WantedBy=default.target
```

## Configuration

### hub.yaml

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

- `{task}` and `{project}` are replaced at runtime.
- If `JUNIE_BIN` env var is set, it replaces `junie` in the command.
- `HUB_TIMEOUT` (default 1800s) controls the max running time per agent task.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HUB_CONFIG` | `./hub.yaml` | Path to config file |
| `HUB_API_KEY` | *(required)* | Bearer token for API auth |
| `HUB_TIMEOUT` | `1800` | Max seconds per agent run |
| `JUNIE_BIN` | — | Override the `junie` binary path |

## Safety Model

- **LAN only**: The server binds to `0.0.0.0` — expose only on your local network.
- **Runner commands are immutable via API/UI**: Commands live only in `hub.yaml` on disk. The API and web UI can edit agent properties (title, description, project_dir, skills, guidelines, runner choice) but never the command template.
- **Bearer token auth**: All `/api/*` endpoints require `HUB_API_KEY`. The static UI at `/` is served without auth.
- **Name validation**: Agent and skill names must match `^[a-z0-9][a-z0-9-]{0,40}$`.
- **Path safety**: Skill paths are resolved and verified to stay within the skills directory.

## CLI Commands

```bash
python -m hub.cli agents          # List agents
python -m hub.cli run vault "..." # Run a task
python -m hub.cli run vault "..." --no-wait  # Fail immediately if busy
python -m hub.cli runs [agent]    # List runs
python -m hub.cli stop <run-id>   # Stop a running agent
python -m hub.cli skills          # List skills
python -m hub.cli skill-enable vault skill-name
python -m hub.cli skill-disable vault skill-name
python -m hub.cli sync [agent]    # Sync skills and guidelines
```

## Skills

Skills live in the `skills/` directory. Each skill is a folder with a `SKILL.md` file containing YAML frontmatter:

```markdown
---
name: my-skill
description: Does something useful
---

Skill content here...
```

When a skill is enabled for an agent, the hub creates a symlink (or copy on Windows) in `<project_dir>/<skills_dir>` pointing to the hub's skill. Disabling removes only hub-managed symlinks — foreign files are never touched.

Agent guidelines are written inside `<!-- hub:begin -->` / `<!-- hub:end -->` markers in `<project_dir>/<guidelines_file>`, preserving surrounding content.

## Manual Setup Steps

1. **Mount your vault** (or other project directory) at the path specified in `hub.yaml`.
2. **Log in to Junie** from the same user account that runs the hub, so the agent has access to credentials.
3. **Use a scratch copy** of your vault first to test the setup.
4. **Create skills** in the `skills/` directory or via the web UI.

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

Tests use a fake agent script (`tests/fake_agent.py`) — no real `junie` binary needed. POSIX-only tests (file locking, process groups) are skipped on Windows.

## Web UI Manual Checks

- [ ] Dashboard shows agent cards grouped by state (Working, Idle, Failed)
- [ ] Clicking an agent opens the detail panel with run history
- [ ] Sending a task from the bottom bar dispatches a run
- [ ] Skills page lists skills with enable/disable matrix
- [ ] Dark/light mode follows system preference
- [ ] First visit prompts for API key
- [ ] No external URLs loaded (works offline)
