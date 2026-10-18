import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "hub.yaml"


def get_config_path() -> Path:
    return Path(os.environ.get("HUB_CONFIG", str(DEFAULT_CONFIG_PATH))).resolve()


def get_hub_timeout() -> int:
    try:
        return int(os.environ.get("HUB_TIMEOUT", "1800"))
    except ValueError:
        return 1800


def validate_name(name: str) -> bool:
    return bool(NAME_RE.match(name))


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    p = (path or get_config_path()).resolve()
    if not p.exists():
        return {"runners": {}, "agents": {}}
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "runners" not in data:
        data["runners"] = {}
    if "agents" not in data:
        data["agents"] = {}
    return data


def save_config(config: Dict[str, Any], path: Optional[Path] = None) -> Path:
    p = (path or get_config_path()).resolve()
    if p.exists():
        backup = p.with_suffix(".yaml.bak")
        shutil.copy2(str(p), str(backup))
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    os.replace(str(tmp), str(p))
    return p


def resolve_command(
    command: List[str], task: str, project: str
) -> List[str]:
    """Resolve {task} and {project} placeholders, apply JUNIE_BIN override."""
    junie_bin = os.environ.get("JUNIE_BIN")
    result = []
    for i, part in enumerate(command):
        if i == 0 and part == "junie" and junie_bin:
            # On Windows, if JUNIE_BIN is a .py file, prepend python
            if sys.platform == "win32" and junie_bin.endswith(".py"):
                result.append(sys.executable)
                result.append(junie_bin)
            else:
                result.append(junie_bin)
        else:
            resolved = part.replace("{task}", task).replace("{project}", project)
            result.append(resolved)
    return result


def get_runner_config(config: Dict[str, Any], runner_name: str) -> Dict[str, Any]:
    runners = config.get("runners", {})
    if runner_name not in runners:
        raise KeyError(f"Runner '{runner_name}' not found in config")
    return runners[runner_name]


def get_agent_config(config: Dict[str, Any], agent_name: str) -> Dict[str, Any]:
    agents = config.get("agents", {})
    if agent_name not in agents:
        raise KeyError(f"Agent '{agent_name}' not found in config")
    return agents[agent_name]


def list_agents(config: Dict[str, Any]) -> List[str]:
    return list(config.get("agents", {}).keys())


def add_agent(config: Dict[str, Any], name: str, agent_data: Dict[str, Any]) -> Dict[str, Any]:
    if not validate_name(name):
        raise ValueError(f"Invalid agent name: {name}")
    if name in config.get("agents", {}):
        raise ValueError(f"Agent '{name}' already exists")
    if "runners" not in config:
        config["runners"] = {}
    if "agents" not in config:
        config["agents"] = {}
    config["agents"][name] = dict(agent_data)
    return config


def update_agent(config: Dict[str, Any], name: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    if name not in config.get("agents", {}):
        raise KeyError(f"Agent '{name}' not found")
    allowed = {"title", "description", "runner", "project_dir", "skills", "guidelines", "permissions"}
    for key in updates:
        if key not in allowed:
            raise ValueError(f"Cannot update agent field: {key}")
    config["agents"][name].update(updates)
    return config


def delete_agent(config: Dict[str, Any], name: str) -> Dict[str, Any]:
    if name not in config.get("agents", {}):
        raise KeyError(f"Agent '{name}' not found")
    del config["agents"][name]
    return config
