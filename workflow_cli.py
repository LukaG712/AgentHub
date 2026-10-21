#!/usr/bin/env python3
"""workflow — Command-line interface for the Unified Workflow platform.

A standalone CLI tool that connects to the Evershade Valley REST API to manage
agents, runs, pipelines, schedules, and the entire platform from any terminal.

Usage:
    workflow agents list
    workflow run my-agent "summarize the latest report"
    workflow pipeline create --name "research" --steps Spectra:SEARCH:query,Polter:TASK:code
    workflow schedules list
    workflow search "error handling"
    workflow health
    workflow services status

Configuration:
    Set WORKFLOW_API_URL environment variable or use --url flag.
    Default: http://localhost:8080
    Set WORKFLOW_API_KEY for authentication or use --key flag.
"""

import argparse
import json
import sys
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:
    print("Error: httpx is required. Install with: pip install httpx", file=sys.stderr)
    sys.exit(1)


# ─── Configuration ───────────────────────────────────────────────────────────

def get_api_url() -> str:
    """Get the API base URL from args, env, or default."""
    return os.environ.get("WORKFLOW_API_URL", "http://localhost:8080")


def get_api_key() -> Optional[str]:
    """Get the API key from env or default."""
    return os.environ.get("WORKFLOW_API_KEY")


def create_client(base_url: Optional[str] = None, api_key: Optional[str] = None) -> httpx.Client:
    """Create an HTTP client configured for the API."""
    url = (base_url or get_api_url()).rstrip("/")
    key = api_key or get_api_key()
    
    headers = {}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    
    return httpx.Client(base_url=url, headers=headers, timeout=30.0)


# ─── Output Helpers ──────────────────────────────────────────────────────────

def print_json(data, indent=2):
    """Print data as formatted JSON."""
    print(json.dumps(data, indent=indent, default=str))


def print_table(rows, headers):
    """Print a simple text table."""
    if not rows:
        print("No results.")
        return
    
    # Calculate column widths
    widths = [len(h) for h in headers]
    str_rows = []
    for row in rows:
        str_row = [str(v) if v is not None else "" for v in row]
        str_rows.append(str_row)
        for i, val in enumerate(str_row):
            widths[i] = max(widths[i], len(val))
    
    # Print header
    header_line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("  ".join("-" * w for w in widths))
    
    # Print rows
    for row in str_rows:
        line = "  ".join(row[i].ljust(widths[i]) for i in range(len(headers)))
        print(line)


def truncate(text, max_len=60):
    """Truncate text with ellipsis."""
    if text is None:
        return ""
    text = str(text)
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def api_call(client, method, path, **kwargs):
    """Make an API call and handle errors."""
    try:
        resp = client.request(method, path, **kwargs)
        if resp.status_code == 401:
            print("Error: Unauthorized. Check your API key.", file=sys.stderr)
            sys.exit(1)
        elif resp.status_code == 404:
            print(f"Error: Endpoint not found: {path}", file=sys.stderr)
            sys.exit(1)
        elif resp.status_code >= 400:
            try:
                error = resp.json()
                print(f"Error: {error.get('detail', resp.text)}", file=sys.stderr)
            except Exception:
                print(f"Error: {resp.text}", file=sys.stderr)
            sys.exit(1)
        try:
            return resp.json()
        except Exception:
            return resp.text
    except httpx.ConnectError:
        print(f"Error: Cannot connect to {client.base_url}. Is the server running?", file=sys.stderr)
        sys.exit(1)
    except httpx.TimeoutException:
        print(f"Error: Request timed out.", file=sys.stderr)
        sys.exit(1)


# ─── Agent Commands ──────────────────────────────────────────────────────────

def cmd_agents_list(args, client):
    """List all agents."""
    data = api_call(client, "GET", "/api/agents")
    
    if isinstance(data, dict) and "agents" in data:
        agents = data["agents"]
    elif isinstance(data, list):
        agents = data
    else:
        print_json(data)
        return
    
    if not agents:
        print("No agents configured.")
        return
    
    if args.json:
        print_json(agents)
        return
    
    rows = []
    if isinstance(agents, dict):
        for name, agent in sorted(agents.items()):
            runner = agent.get("runner", "junie")
            skills = agent.get("skills", [])
            skills_str = ", ".join(skills) if skills else "none"
            title = agent.get("title", "")
            rows.append([name, runner, skills_str, truncate(title, 40)])
    elif isinstance(agents, list):
        for agent in agents:
            name = agent.get("name", agent.get("id", ""))
            runner = agent.get("runner", "junie")
            skills = agent.get("skills", [])
            skills_str = ", ".join(skills) if skills else "none"
            title = agent.get("title", "")
            rows.append([name, runner, skills_str, truncate(title, 40)])
    
    print_table(rows, ["NAME", "RUNNER", "SKILLS", "TITLE"])


def cmd_agents_get(args, client):
    """Get agent details."""
    data = api_call(client, "GET", f"/api/agents/{args.name}")
    print_json(data)


def cmd_agents_create(args, client):
    """Create a new agent."""
    body = {
        "name": args.name,
        "runner": getattr(args, "runner", "junie") or "junie",
    }
    if getattr(args, "title", None):
        body["title"] = args.title
    if getattr(args, "skills", None):
        body["skills"] = [s.strip() for s in args.skills.split(",")]
    if getattr(args, "prompt", None):
        body["prompt"] = args.prompt
    
    data = api_call(client, "POST", "/api/agents", json=body)
    if args.json:
        print_json(data)
    else:
        print(f"Agent '{args.name}' created.")


def cmd_agents_update(args, client):
    """Update an agent."""
    body = {}
    if getattr(args, "runner", None):
        body["runner"] = args.runner
    if getattr(args, "title", None):
        body["title"] = args.title
    if getattr(args, "skills", None):
        body["skills"] = [s.strip() for s in args.skills.split(",")]
    if getattr(args, "prompt", None):
        body["prompt"] = args.prompt
    
    data = api_call(client, "PUT", f"/api/agents/{args.name}", json=body)
    if args.json:
        print_json(data)
    else:
        print(f"Agent '{args.name}' updated.")


def cmd_agents_delete(args, client):
    """Delete an agent."""
    api_call(client, "DELETE", f"/api/agents/{args.name}")
    print(f"Agent '{args.name}' deleted.")


# ─── Run Commands ────────────────────────────────────────────────────────────

def cmd_run(args, client):
    """Run an agent task."""
    body = {
        "agent": args.agent,
        "task": args.task,
    }
    if getattr(args, "no_wait", False):
        body["no_wait"] = True
    
    data = api_call(client, "POST", "/api/runs", json=body)
    
    if args.json:
        print_json(data)
        return
    
    run_id = data.get("id", "unknown")
    state = data.get("state", "unknown")
    answer = data.get("answer", "")
    
    if state == "done":
        print(f"Done: {answer}")
    elif state == "failed":
        reason = data.get("fail_reason", "unknown")
        print(f"Failed: {reason}", file=sys.stderr)
        if data.get("raw_output"):
            print(data["raw_output"], file=sys.stderr)
        sys.exit(1)
    elif state == "working":
        print(f"Run ID: {run_id}")
        print(f"State: {state}")
        if not getattr(args, "no_wait", False):
            # Poll for completion
            print("Waiting for completion...")
            poll_run(run_id, client)
    else:
        print(f"Run ID: {run_id}")
        print(f"State: {state}")


def poll_run(run_id, client, interval=2, timeout=600):
    """Poll a run until it completes."""
    start = time.time()
    while time.time() - start < timeout:
        data = api_call(client, "GET", f"/api/runs/{run_id}")
        state = data.get("state", "unknown")
        
        if state in ("done", "failed", "stopped"):
            if state == "done":
                print(f"\nDone: {data.get('answer', '')}")
            elif state == "failed":
                print(f"\nFailed: {data.get('fail_reason', 'unknown')}", file=sys.stderr)
                sys.exit(1)
            else:
                print(f"\nStopped.", file=sys.stderr)
                sys.exit(1)
            return
        
        print(f"  ... {state}", end="\r")
        time.sleep(interval)
    
    print("\nTimeout waiting for run to complete.")
    sys.exit(1)


def cmd_runs_list(args, client):
    """List runs."""
    params = {}
    if getattr(args, "agent", None):
        params["agent"] = args.agent
    if getattr(args, "state", None):
        params["state"] = args.state
    
    data = api_call(client, "GET", "/api/runs", params=params)
    
    if args.json:
        print_json(data)
        return
    
    runs = data if isinstance(data, list) else data.get("runs", [])
    if not runs:
        print("No runs found.")
        return
    
    rows = []
    for run in runs:
        ts = run.get("started", run.get("finished", "?"))
        state = run.get("state", "unknown")
        run_id = run.get("id", "")[:8]
        agent = run.get("agent", "")
        task = run.get("task", "")
        answer = run.get("answer", "")
        reason = run.get("fail_reason", "")
        
        answer_preview = truncate(answer, 40) if answer else ""
        reason_str = f" ({reason})" if reason else ""
        
        rows.append([state, str(ts)[:19], run_id, agent[:15], truncate(task, 35), answer_preview + reason_str])
    
    print_table(rows, ["STATE", "TIME", "ID", "AGENT", "TASK", "ANSWER/REASON"])


def cmd_run_get(args, client):
    """Get run details."""
    data = api_call(client, "GET", f"/api/runs/{args.run_id}")
    print_json(data)


def cmd_run_stop(args, client):
    """Stop a running agent."""
    data = api_call(client, "POST", f"/api/runs/{args.run_id}/stop")
    state = data.get("state", "unknown")
    if state == "stopped":
        print(f"Run '{args.run_id}' stopped.")
    else:
        print(f"Run '{args.run_id}' is not running (state: {state}).", file=sys.stderr)
        sys.exit(1)


# ─── Pipeline Commands ───────────────────────────────────────────────────────

def cmd_pipeline_run(args, client):
    """Run a cross-service pipeline."""
    steps = []
    for step_str in args.steps:
        if ":" in step_str:
            service, task = step_str.split(":", 1)
            steps.append({"service": service.strip(), "task": task.strip()})
        else:
            steps.append({"service": "junie", "task": step_str.strip()})
    
    body = {"steps": steps}
    if getattr(args, "context", None):
        body["context"] = args.context
    
    data = api_call(client, "POST", "/api/pipeline", json=body)
    
    if args.json:
        print_json(data)
        return
    
    results = data.get("results", [])
    for i, result in enumerate(results):
        step = result.get("step", {})
        status = result.get("status", "unknown")
        output = result.get("output", "")
        print(f"Step {i+1} ({step.get('service', '?')}): {status}")
        if output:
            print(f"  {truncate(output, 100)}")


# ─── Schedule Commands ───────────────────────────────────────────────────────

def cmd_schedules_list(args, client):
    """List all scheduled pipelines."""
    data = api_call(client, "GET", "/api/schedules")
    
    if args.json:
        print_json(data)
        return
    
    schedules = data if isinstance(data, list) else data.get("schedules", [])
    if not schedules:
        print("No scheduled pipelines.")
        return
    
    rows = []
    for sched in schedules:
        sid = sched.get("id", "")[:8]
        name = sched.get("name", "")
        cron = sched.get("cron", "")
        enabled = "on" if sched.get("enabled", True) else "off"
        last_run = sched.get("last_run", "never")
        if last_run and last_run != "never":
            last_run = str(last_run)[:19]
        run_count = sched.get("run_count", 0)
        rows.append([sid, name, cron, enabled, last_run, str(run_count)])
    
    print_table(rows, ["ID", "NAME", "CRON", "ENABLED", "LAST RUN", "RUNS"])


def cmd_schedules_create(args, client):
    """Create a scheduled pipeline."""
    steps = []
    for step_str in args.steps:
        if ":" in step_str:
            service, task = step_str.split(":", 1)
            steps.append({"service": service.strip(), "task": task.strip()})
        else:
            steps.append({"service": "junie", "task": step_str.strip()})
    
    body = {
        "name": args.name,
        "cron": args.cron,
        "steps": steps,
    }
    
    data = api_call(client, "POST", "/api/schedules", json=body)
    if args.json:
        print_json(data)
    else:
        sched_id = data.get("id", "unknown")
        print(f"Schedule '{args.name}' created (ID: {sched_id[:8]})")


def cmd_schedules_delete(args, client):
    """Delete a scheduled pipeline."""
    api_call(client, "DELETE", f"/api/schedules/{args.schedule_id}")
    print(f"Schedule '{args.schedule_id}' deleted.")


def cmd_schedules_toggle(args, client):
    """Enable or disable a schedule."""
    enabled = args.enable
    body = {"enabled": enabled}
    api_call(client, "PUT", f"/api/schedules/{args.schedule_id}", json=body)
    state = "enabled" if enabled else "disabled"
    print(f"Schedule '{args.schedule_id}' {state}.")


# ─── Search Command ──────────────────────────────────────────────────────────

def cmd_search(args, client):
    """Search across all services."""
    params = {"q": args.query}
    if getattr(args, "service", None):
        params["service"] = args.service
    
    data = api_call(client, "GET", "/api/search", params=params)
    
    if args.json:
        print_json(data)
        return
    
    # Print results by service
    for service in ["Spectra", "Polter", "Evershade Valley"]:
        results = data.get(service, [])
        if results:
            print(f"\n{service.upper()} ({len(results)} results):")
            for i, result in enumerate(results[:10], 1):
                if isinstance(result, dict):
                    title = result.get("title", result.get("name", result.get("task", "")))
                    desc = result.get("description", result.get("answer", ""))
                    print(f"  {i}. {truncate(title, 50)}")
                    if desc:
                        print(f"     {truncate(desc, 80)}")
                else:
                    print(f"  {i}. {truncate(str(result), 80)}")


# ─── Health & Service Commands ───────────────────────────────────────────────

def cmd_health(args, client):
    """Check platform health."""
    data = api_call(client, "GET", "/api/health")
    
    if args.json:
        print_json(data)
        return
    
    status = data.get("status", "unknown")
    db_status = data.get("database", {}).get("status", "unknown") if isinstance(data.get("database"), dict) else "N/A"
    db_size = data.get("database", {}).get("size", "N/A") if isinstance(data.get("database"), dict) else "N/A"
    
    print(f"Platform Status: {status}")
    print(f"Database: {db_status} ({db_size})")
    
    # Service health
    services = data.get("services", {})
    if services:
        print("\nServices:")
        for name, info in services.items():
            if isinstance(info, dict):
                svc_status = info.get("status", "unknown")
                response_time = info.get("response_time_ms", "?")
                print(f"  {name}: {svc_status} ({response_time}ms)")
            else:
                print(f"  {name}: {info}")


def cmd_services(args, client):
    """Check individual service health."""
    services = {
        "Evershade Valley": "/api/health",
        "Polter": "/api/Polter/health",
        "Spectra": "/api/crawl/health",
    }
    
    if args.json:
        result = {}
        for name, path in services.items():
            try:
                data = api_call(client, "GET", path)
                result[name] = data
            except SystemExit:
                result[name] = {"status": "unreachable"}
        print_json(result)
        return
    
    for name, path in services.items():
        try:
            data = api_call(client, "GET", path)
            status = data.get("status", data.get("healthy", "unknown"))
            if isinstance(status, bool):
                status = "healthy" if status else "unhealthy"
            print(f"  {name}: {status}")
        except SystemExit:
            print(f"  {name}: unreachable")


def cmd_dashboard(args, client):
    """Show unified dashboard."""
    data = api_call(client, "GET", "/api/dashboard")
    
    if args.json:
        print_json(data)
        return
    
    print("=== Unified Workflow Dashboard ===\n")
    
    # Evershade Valley section
    Evershade Valley = data.get("Evershade Valley", {})
    agents = Evershade Valley.get("agents", [])
    runs = Evershade Valley.get("runs", [])
    print(f"Evershade Valley: {len(agents)} agents, {len(runs)} runs")
    
    # Polter section
    Polter = data.get("Polter", {})
    workers = Polter.get("workers", [])
    queue = Polter.get("queue", {})
    print(f"Polter: {len(workers)} workers, queue: {queue}")
    
    # Spectra section
    Spectra = data.get("Spectra", {})
    oc_status = Spectra.get("status", "unknown")
    print(f"Spectra: {oc_status}")


# ─── Batch Command ───────────────────────────────────────────────────────────

def cmd_batch(args, client):
    """Run parallel batch tasks."""
    tasks = []
    for task_str in args.tasks:
        if ":" in task_str:
            service, task = task_str.split(":", 1)
            tasks.append({"service": service.strip(), "task": task.strip()})
        else:
            tasks.append({"service": "junie", "task": task_str.strip()})
    
    body = {"tasks": tasks}
    data = api_call(client, "POST", "/api/batch", json=body)
    
    if args.json:
        print_json(data)
        return
    
    results = data.get("results", [])
    for i, result in enumerate(results):
        status = result.get("status", "unknown")
        task = result.get("task", "")
        print(f"Task {i+1}: {status} - {truncate(task, 60)}")


# ─── Backup Commands ─────────────────────────────────────────────────────────

def cmd_backup_create(args, client):
    """Create a database backup."""
    data = api_call(client, "POST", "/api/backup")
    if args.json:
        print_json(data)
    else:
        filename = data.get("filename", "unknown")
        print(f"Backup created: {filename}")


def cmd_backup_list(args, client):
    """List available backups."""
    data = api_call(client, "GET", "/api/backups")
    
    if args.json:
        print_json(data)
        return
    
    backups = data if isinstance(data, list) else data.get("backups", [])
    if not backups:
        print("No backups found.")
        return
    
    rows = []
    for backup in backups:
        if isinstance(backup, dict):
            name = backup.get("filename", backup.get("name", ""))
            size = backup.get("size", "?")
            created = backup.get("created_at", "?")
            rows.append([name, str(size), str(created)[:19]])
        else:
            rows.append([str(backup), "", ""])
    
    print_table(rows, ["FILENAME", "SIZE", "CREATED"])


def cmd_backup_restore(args, client):
    """Restore from a backup."""
    data = api_call(client, "POST", f"/api/backup/restore/{args.filename}")
    if args.json:
        print_json(data)
    else:
        print(f"Restored from: {args.filename}")


# ─── Analytics Commands ──────────────────────────────────────────────────────

def cmd_analytics(args, client):
    """Show usage analytics."""
    data = api_call(client, "GET", "/api/analytics")
    
    if args.json:
        print_json(data)
        return
    
    total = data.get("total_api_calls", 0)
    print(f"Total API Calls: {total}")
    
    by_service = data.get("by_service", {})
    if by_service:
        print("\nBy Service:")
        for svc, count in by_service.items():
            print(f"  {svc}: {count}")
    
    task_durations = data.get("task_durations", {})
    if task_durations:
        print("\nTask Durations:")
        avg = task_durations.get("avg", "?")
        p95 = task_durations.get("p95", "?")
        print(f"  Avg: {avg}, P95: {p95}")


# ─── Main Parser ─────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="workflow",
        description="Unified Workflow CLI — Manage agents, runs, pipelines, and services",
    )
    parser.add_argument("--url", help="API base URL (default: $WORKFLOW_API_URL or http://localhost:8080)")
    parser.add_argument("--key", help="API key (default: $WORKFLOW_API_KEY)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # ── Agents ──
    p_agents = subparsers.add_parser("agents", help="Manage agents")
    agents_sub = p_agents.add_subparsers(dest="subcommand")
    
    p_agents_list = agents_sub.add_parser("list", help="List all agents")
    p_agents_list.set_defaults(func=cmd_agents_list)
    
    p_agents_get = agents_sub.add_parser("get", help="Get agent details")
    p_agents_get.add_argument("name", help="Agent name")
    p_agents_get.set_defaults(func=cmd_agents_get)
    
    p_agents_create = agents_sub.add_parser("create", help="Create a new agent")
    p_agents_create.add_argument("name", help="Agent name")
    p_agents_create.add_argument("--runner", default="junie", help="Runner type (junie, Polter, Spectra)")
    p_agents_create.add_argument("--title", help="Agent title")
    p_agents_create.add_argument("--skills", help="Comma-separated skills")
    p_agents_create.add_argument("--prompt", help="Agent prompt")
    p_agents_create.set_defaults(func=cmd_agents_create)
    
    p_agents_update = agents_sub.add_parser("update", help="Update an agent")
    p_agents_update.add_argument("name", help="Agent name")
    p_agents_update.add_argument("--runner", help="Runner type")
    p_agents_update.add_argument("--title", help="Agent title")
    p_agents_update.add_argument("--skills", help="Comma-separated skills")
    p_agents_update.add_argument("--prompt", help="Agent prompt")
    p_agents_update.set_defaults(func=cmd_agents_update)
    
    p_agents_delete = agents_sub.add_parser("delete", help="Delete an agent")
    p_agents_delete.add_argument("name", help="Agent name")
    p_agents_delete.set_defaults(func=cmd_agents_delete)
    
    # ── Runs ──
    p_runs = subparsers.add_parser("runs", help="Manage runs")
    runs_sub = p_runs.add_subparsers(dest="subcommand")
    
    p_runs_list = runs_sub.add_parser("list", help="List runs")
    p_runs_list.add_argument("--agent", help="Filter by agent")
    p_runs_list.add_argument("--state", help="Filter by state")
    p_runs_list.set_defaults(func=cmd_runs_list)
    
    p_runs_get = runs_sub.add_parser("get", help="Get run details")
    p_runs_get.add_argument("run_id", help="Run ID")
    p_runs_get.set_defaults(func=cmd_run_get)
    
    p_runs_stop = runs_sub.add_parser("stop", help="Stop a run")
    p_runs_stop.add_argument("run_id", help="Run ID")
    p_runs_stop.set_defaults(func=cmd_run_stop)
    
    # ── Run (shortcut) ──
    p_run = subparsers.add_parser("run", help="Run an agent task")
    p_run.add_argument("agent", help="Agent name")
    p_run.add_argument("task", help="Task description")
    p_run.add_argument("--no-wait", action="store_true", help="Don't wait for completion")
    p_run.set_defaults(func=cmd_run)
    
    # ── Pipeline ──
    p_pipeline = subparsers.add_parser("pipeline", help="Run a cross-service pipeline")
    p_pipeline.add_argument("steps", nargs="+", help="Pipeline steps (service:task)")
    p_pipeline.add_argument("--context", help="Initial context")
    p_pipeline.set_defaults(func=cmd_pipeline_run)
    
    # ── Schedules ──
    p_schedules = subparsers.add_parser("schedules", help="Manage scheduled pipelines")
    sched_sub = p_schedules.add_subparsers(dest="subcommand")
    
    p_sched_list = sched_sub.add_parser("list", help="List schedules")
    p_sched_list.set_defaults(func=cmd_schedules_list)
    
    p_sched_create = sched_sub.add_parser("create", help="Create a schedule")
    p_sched_create.add_argument("name", help="Schedule name")
    p_sched_create.add_argument("cron", help="Cron expression")
    p_sched_create.add_argument("steps", nargs="+", help="Pipeline steps (service:task)")
    p_sched_create.set_defaults(func=cmd_schedules_create)
    
    p_sched_delete = sched_sub.add_parser("delete", help="Delete a schedule")
    p_sched_delete.add_argument("schedule_id", help="Schedule ID")
    p_sched_delete.set_defaults(func=cmd_schedules_delete)
    
    p_sched_toggle = sched_sub.add_parser("toggle", help="Enable/disable a schedule")
    p_sched_toggle.add_argument("schedule_id", help="Schedule ID")
    p_sched_toggle.add_argument("--enable", action="store_true", help="Enable")
    p_sched_toggle.set_defaults(func=cmd_schedules_toggle)
    
    # ── Search ──
    p_search = subparsers.add_parser("search", help="Search across all services")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--service", help="Filter by service (Spectra, Polter, Evershade Valley)")
    p_search.set_defaults(func=cmd_search)
    
    # ── Health ──
    p_health = subparsers.add_parser("health", help="Check platform health")
    p_health.set_defaults(func=cmd_health)
    
    # ── Services ──
    p_services = subparsers.add_parser("services", help="Check individual service health")
    p_services.set_defaults(func=cmd_services)
    
    # ── Dashboard ──
    p_dashboard = subparsers.add_parser("dashboard", help="Show unified dashboard")
    p_dashboard.set_defaults(func=cmd_dashboard)
    
    # ── Batch ──
    p_batch = subparsers.add_parser("batch", help="Run parallel batch tasks")
    p_batch.add_argument("tasks", nargs="+", help="Tasks to run (service:task)")
    p_batch.set_defaults(func=cmd_batch)
    
    # ── Backup ──
    p_backup = subparsers.add_parser("backup", help="Database backup/restore")
    backup_sub = p_backup.add_subparsers(dest="subcommand")
    
    p_backup_create = backup_sub.add_parser("create", help="Create a backup")
    p_backup_create.set_defaults(func=cmd_backup_create)
    
    p_backup_list = backup_sub.add_parser("list", help="List backups")
    p_backup_list.set_defaults(func=cmd_backup_list)
    
    p_backup_restore = backup_sub.add_parser("restore", help="Restore from backup")
    p_backup_restore.add_argument("filename", help="Backup filename")
    p_backup_restore.set_defaults(func=cmd_backup_restore)
    
    # ── Analytics ──
    p_analytics = subparsers.add_parser("analytics", help="Show usage analytics")
    p_analytics.set_defaults(func=cmd_analytics)
    
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    
    # Create client
    client = create_client(base_url=args.url, api_key=args.key)
    
    # Dispatch to command handler
    try:
        args.func(args, client)
    except AttributeError as e:
        if "func" in str(e):
            # Subcommand required
            print(f"Error: 'workflow {args.command}' requires a subcommand.", file=sys.stderr)
            parser.parse_args([args.command, "--help"])
        else:
            raise
    finally:
        client.close()


if __name__ == "__main__":
    main()
