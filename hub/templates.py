"""Marketplace templates: local library of Bot templates.

Templates are YAML files in the templates/ directory. Each template defines
a Bot's name, title, description, guidelines, and suggested skills.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from hub.config import load_config, save_config, validate_name

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def list_templates() -> List[Dict[str, Any]]:
    """List all available Bot templates."""
    templates = []
    if not _TEMPLATES_DIR.exists():
        return templates
    for yaml_file in sorted(_TEMPLATES_DIR.glob("*.yaml")):
        try:
            with open(yaml_file, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            templates.append({
                "name": data.get("name", yaml_file.stem),
                "title": data.get("title", yaml_file.stem.replace("-", " ").title()),
                "description": data.get("description", ""),
                "runner": data.get("runner", "junie"),
                "guidelines": data.get("guidelines", ""),
                "suggested_skills": data.get("suggested_skills", []),
            })
        except Exception:
            continue
    return templates


def get_template(name: str) -> Optional[Dict[str, Any]]:
    """Get a single template by name."""
    path = _TEMPLATES_DIR / f"{name}.yaml"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return {
            "name": data.get("name", name),
            "title": data.get("title", name.replace("-", " ").title()),
            "description": data.get("description", ""),
            "runner": data.get("runner", "junie"),
            "guidelines": data.get("guidelines", ""),
            "suggested_skills": data.get("suggested_skills", []),
        }
    except Exception:
        return None


def create_agent_from_template(name: str, agent_name: Optional[str] = None) -> Dict[str, Any]:
    """Create an agent from a template.

    Returns the created agent config.
    """
    template = get_template(name)
    if template is None:
        raise ValueError(f"Template '{name}' not found")

    agent_name = agent_name or template["name"]
    if not validate_name(agent_name):
        raise ValueError(f"Invalid agent name: {agent_name}")

    config = load_config()
    if agent_name in config.get("agents", {}):
        raise ValueError(f"Agent '{agent_name}' already exists")

    agent_data = {
        "title": template["title"],
        "description": template["description"],
        "runner": template["runner"],
        "guidelines": template["guidelines"],
        "skills": template.get("suggested_skills", []),
    }

    config["agents"][agent_name] = agent_data
    save_config(config)

    return agent_data


def generate_bot_config(description: str) -> Dict[str, Any]:
    """Generate a Bot config from a one-sentence description.

    Uses simple template-based generation. Falls back to a generic config.
    """
    desc_lower = description.lower()

    # Try to match a template based on keywords
    templates = list_templates()
    for t in templates:
        title_words = set(t["title"].lower().split())
        desc_words = set(desc_lower.split())
        if title_words & desc_words:
            return {
                "name": t["name"],
                "title": t["title"],
                "description": description,
                "guidelines": t["guidelines"],
                "runner": t["runner"],
            }

    # Generate a name from the description
    words = re.findall(r"[a-z]+", desc_lower[:50])
    name = "-".join(words[:3]) if words else "assistant"
    if not validate_name(name):
        name = "assistant"

    return {
        "name": name,
        "title": description[:50],
        "description": description,
        "guidelines": f"You are a helpful assistant. {description}",
        "runner": "junie",
    }
