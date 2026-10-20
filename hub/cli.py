"""CLI interface for the agent hub."""

import argparse
import json
import sys
from pathlib import Path

from hub import skills
from hub.agents import create_agent, delete_agent_by_name, get_agent, list_agents, update_agent_data
from hub.config import load_config, save_config, validate_name
from hub.runner import (
    Run,
    get_run,
    list_runs,
    recover_stale_runs,
    run_agent,
    stop_run,
)


def cmd_agents(args):
    """List all agents."""
    agents = list_agents()
    if not agents:
        print("No agents configured.")
        return
    config = load_config()
    for name in sorted(agents):
        agent = config["agents"][name]
        title = agent.get("title", name)
        runner = agent.get("runner", "junie")
        skills = agent.get("skills", [])
        skills_str = ", ".join(skills) if skills else "none"
        print(f"  {name:20s} runner={runner:10s} skills=[{skills_str}]  {title}")


def cmd_run(args):
    """Run an agent task."""
    agent_name = args.agent
    task = args.task
    no_wait = args.no_wait

    # Recover stale runs first
    recover_stale_runs()

    run = run_agent(agent_name, task, no_wait=no_wait)

    if run.state == "done":
        print(f"Done: {run.answer}")
    elif run.state == "failed":
        reason = run.fail_reason or "unknown"
        print(f"Failed: {reason}", file=sys.stderr)
        if run.raw_output:
            print(run.raw_output, file=sys.stderr)
        sys.exit(1)
    elif run.state == "stopped":
        print("Stopped.", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"Run ID: {run.id}")
        print(f"State: {run.state}")


def cmd_runs(args):
    """List runs."""
    agent = getattr(args, "agent", None)
    state = getattr(args, "state", None)

    runs = list_runs(agent=agent, state=state)
    if not runs:
        print("No runs found.")
        return

    for run in runs:
        ts = run.started or run.finished or "?"
        answer_preview = (run.answer[:50] + "...") if len(run.answer) > 50 else run.answer
        reason = f" ({run.fail_reason})" if run.fail_reason else ""
        print(f"  [{run.state:8s}] {ts}  {run.id[:8]}  {run.agent:15s}  {run.task[:40]:40s}  {answer_preview}{reason}")


def cmd_stop(args):
    """Stop a running agent."""
    run_id = args.run_id
    run = stop_run(run_id)
    if run is None:
        print(f"Run '{run_id}' not found.", file=sys.stderr)
        sys.exit(1)
    elif run.state == "stopped":
        print(f"Run '{run_id}' stopped.")
    elif run.state == "failed" and run.fail_reason == "stale":
        print(f"Run '{run_id}' was stale (PID reused).", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"Run '{run_id}' is not running (state: {run.state}).", file=sys.stderr)
        sys.exit(1)


def cmd_skills(args):
    """List all skills."""
    skill_list = skills.list_skills()
    if not skill_list:
        print("No skills found.")
        return
    for s in skill_list:
        usage = skills.skill_usage(s["name"])
        usage_str = ", ".join(usage) if usage else "none"
        print(f"  {s['name']:20s} used_by=[{usage_str}]  {s['description']}")


def cmd_skill_enable(args):
    """Enable a skill for an agent."""
    agent_name = args.agent
    skill_name = args.skill
    try:
        skills.enable_skill(agent_name, skill_name)
        print(f"Skill '{skill_name}' enabled for agent '{agent_name}'.")
        skills.sync_agent(agent_name)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def cmd_skill_disable(args):
    """Disable a skill for an agent."""
    agent_name = args.agent
    skill_name = args.skill
    try:
        skills.disable_skill(agent_name, skill_name)
        print(f"Skill '{skill_name}' disabled for agent '{agent_name}'.")
        skills.sync_agent(agent_name)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def cmd_sync(args):
    """Sync all agents."""
    agent_name = getattr(args, "agent", None)
    if agent_name:
        try:
            skills.sync_agent(agent_name)
            print(f"Agent '{agent_name}' synced.")
        except KeyError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
    else:
        skills.sync_all_agents()
        print("All agents synced.")


def cmd_serve(args):
    """Start the web server."""
    import uvicorn
    port = args.port
    host = args.host
    print(f"Starting Agent Hub on {host}:{port} ...")
    uvicorn.run("hub.api:app", host=host, port=port, reload=args.reload)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="hub",
        description="Agent Hub CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # hub agents
    p_agents = subparsers.add_parser("agents", help="List agents")
    p_agents.set_defaults(func=cmd_agents)

    # hub run
    p_run = subparsers.add_parser("run", help="Run an agent task")
    p_run.add_argument("agent", help="Agent name")
    p_run.add_argument("task", help="Task description")
    p_run.add_argument("--no-wait", action="store_true", help="Fail immediately if agent is busy")
    p_run.set_defaults(func=cmd_run)

    # hub runs
    p_runs = subparsers.add_parser("runs", help="List runs")
    p_runs.add_argument("agent", nargs="?", help="Filter by agent name")
    p_runs.add_argument("--state", choices=["queued", "working", "done", "failed", "stopped"],
                        help="Filter by state")
    p_runs.set_defaults(func=cmd_runs)

    # hub stop
    p_stop = subparsers.add_parser("stop", help="Stop a running agent")
    p_stop.add_argument("run_id", help="Run ID to stop")
    p_stop.set_defaults(func=cmd_stop)

    # hub skills
    p_skills = subparsers.add_parser("skills", help="List skills")
    p_skills.set_defaults(func=cmd_skills)

    # hub skill-enable
    p_enable = subparsers.add_parser("skill-enable", help="Enable a skill for an agent")
    p_enable.add_argument("agent", help="Agent name")
    p_enable.add_argument("skill", help="Skill name")
    p_enable.set_defaults(func=cmd_skill_enable)

    # hub skill-disable
    p_disable = subparsers.add_parser("skill-disable", help="Disable a skill for an agent")
    p_disable.add_argument("agent", help="Agent name")
    p_disable.add_argument("skill", help="Skill name")
    p_disable.set_defaults(func=cmd_skill_disable)

    # hub sync
    p_sync = subparsers.add_parser("sync", help="Sync agent skills and guidelines")
    p_sync.add_argument("agent", nargs="?", help="Agent name (sync all if omitted)")
    p_sync.set_defaults(func=cmd_sync)

    # hub serve
    p_serve = subparsers.add_parser("serve", help="Start the web server")
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1; use 0.0.0.0 for LAN exposure)")
    p_serve.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    p_serve.add_argument("--reload", action="store_true", help="Enable auto-reload on code changes")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
