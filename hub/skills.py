"""Skill management: CRUD, symlink sync, guidelines writing."""

import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from hub.config import (
    get_config_path,
    load_config,
    save_config,
    validate_name,
)

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

HUB_BEGIN = "<!-- hub:begin -->"
HUB_END = "<!-- hub:end -->"


def _skills_dir() -> Path:
    return _SKILLS_DIR


def _skill_path(name: str) -> Path:
    """Get the path for a skill, verifying it stays within skills dir."""
    p = _skills_dir() / name
    try:
        p.resolve().relative_to(_skills_dir().resolve())
    except ValueError:
        raise ValueError(f"Skill path escapes skills directory: {name}")
    return p


def list_skills() -> List[Dict[str, Any]]:
    """List all skills with name and description."""
    skills = []
    if not _skills_dir().exists():
        return skills
    for d in sorted(_skills_dir().iterdir()):
        if not d.is_dir():
            continue
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            continue
        name = d.name
        if not validate_name(name):
            continue
        desc = _extract_description(skill_md)
        skills.append({"name": name, "description": desc})
    return skills


def _extract_description(skill_md: Path) -> str:
    """Extract description from SKILL.md frontmatter."""
    text = skill_md.read_text(encoding="utf-8")
    # Look for description: in YAML frontmatter
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            frontmatter = text[3:end]
            for line in frontmatter.split("\n"):
                if line.startswith("description:"):
                    return line.split(":", 1)[1].strip().strip('"').strip("'")
    # Fallback: first line
    for line in text.split("\n"):
        line = line.strip()
        if line and not line.startswith("---"):
            return line[:100]
    return ""


def create_skill(name: str, description: str = "", content: str = "") -> Dict[str, Any]:
    """Create a new skill."""
    if not validate_name(name):
        raise ValueError(f"Invalid skill name: {name}")
    p = _skill_path(name)
    if p.exists():
        raise ValueError(f"Skill '{name}' already exists")
    p.mkdir(parents=True)
    if not content:
        content = f"---\nname: {name}\ndescription: {description}\n---\n\n{description}\n"
    skill_md = p / "SKILL.md"
    skill_md.write_text(content, encoding="utf-8")
    return {"name": name, "description": description}


def update_skill(name: str, description: str = "", content: str = "") -> Dict[str, Any]:
    """Update an existing skill."""
    p = _skill_path(name)
    skill_md = p / "SKILL.md"
    if not skill_md.exists():
        raise KeyError(f"Skill '{name}' not found")
    if content:
        skill_md.write_text(content, encoding="utf-8")
    elif description:
        # Update description in frontmatter
        text = skill_md.read_text(encoding="utf-8")
        if "description:" in text:
            text = re.sub(
                r"(description:\s*).*",
                f"description: {description}",
                text,
                count=1,
            )
        else:
            # Add description after name:
            text = re.sub(
                r"(name:\s*[^\\n]*)",
                f"\\1\ndescription: {description}",
                text,
                count=1,
            )
        skill_md.write_text(text, encoding="utf-8")
    return {"name": name, "description": description or _extract_description(skill_md)}


def delete_skill(name: str) -> None:
    """Delete a skill."""
    p = _skill_path(name)
    if not p.exists():
        raise KeyError(f"Skill '{name}' not found")
    shutil.rmtree(str(p))


def skill_usage(name: str) -> List[str]:
    """List agents that use a given skill."""
    config = load_config()
    agents = []
    for agent_name, agent_data in config.get("agents", {}).items():
        skills = agent_data.get("skills", [])
        if name in skills:
            agents.append(agent_name)
    return agents


def enable_skill(agent_name: str, skill_name: str) -> None:
    """Enable a skill for an agent."""
    config = load_config()
    if agent_name not in config.get("agents", {}):
        raise KeyError(f"Agent '{agent_name}' not found")
    skill_path = _skill_path(skill_name)
    if not (skill_path / "SKILL.md").exists():
        raise KeyError(f"Skill '{skill_name}' not found")
    agent = config["agents"][agent_name]
    if "skills" not in agent:
        agent["skills"] = []
    if skill_name not in agent["skills"]:
        agent["skills"].append(skill_name)
    save_config(config)


def disable_skill(agent_name: str, skill_name: str) -> None:
    """Disable a skill for an agent."""
    config = load_config()
    if agent_name not in config.get("agents", {}):
        raise KeyError(f"Agent '{agent_name}' not found")
    agent = config["agents"][agent_name]
    if "skills" in agent and skill_name in agent["skills"]:
        agent["skills"].remove(skill_name)
    save_config(config)


def sync_agent(agent_name: str) -> None:
    """Sync skills and guidelines for an agent."""
    config = load_config()
    if agent_name not in config.get("agents", {}):
        raise KeyError(f"Agent '{agent_name}' not found")
    agent = config["agents"][agent_name]
    runner_name = agent.get("runner", "junie")
    runners = config.get("runners", {})
    if runner_name not in runners:
        return
    runner = runners[runner_name]
    project_dir = Path(agent.get("project_dir", ""))
    if not project_dir.exists():
        return

    skills_dir_rel = runner.get("skills_dir", ".junie/skills")
    guidelines_file_rel = runner.get("guidelines_file", ".junie/AGENTS.md")

    agent_skills_dir = project_dir / skills_dir_rel
    agent_guidelines = project_dir / guidelines_file_rel

    enabled_skills = agent.get("skills", [])

    # Create skills dir if needed
    agent_skills_dir.mkdir(parents=True, exist_ok=True)

    # Create symlinks for enabled skills
    hub_skills = _skills_dir()
    for skill_name in enabled_skills:
        skill_source = hub_skills / skill_name
        skill_link = agent_skills_dir / skill_name
        if skill_source.exists():
            if skill_link.exists() or skill_link.is_symlink():
                skill_link.unlink()
            try:
                skill_link.symlink_to(skill_source.resolve())
            except (OSError, NotImplementedError):
                # Symlinks may not work on Windows without admin rights
                # Fall back to copy
                if skill_link.exists():
                    shutil.rmtree(str(skill_link))
                shutil.copytree(str(skill_source), str(skill_link))

    # Remove stale hub symlinks
    for item in agent_skills_dir.iterdir():
        if item.is_symlink():
            target = item.resolve()
            try:
                target.relative_to(hub_skills.resolve())
                # This is a hub symlink — check if still enabled
                if item.name not in enabled_skills:
                    item.unlink()
            except ValueError:
                # Not a hub symlink — leave it alone
                pass
        elif item.is_dir():
            # Could be a copied skill — check if it matches a hub skill
            # Only remove if it's a copy of a hub skill no longer enabled
            hub_skill = hub_skills / item.name
            if item.name not in enabled_skills and hub_skill.exists():
                # Check if this looks like a copy of a hub skill
                if (item / "SKILL.md").exists():
                    shutil.rmtree(str(item))

    # Write guidelines
    guidelines_text = agent.get("guidelines", "")
    if guidelines_text:
        _write_guidelines_block(agent_guidelines, guidelines_text)


def _write_guidelines_block(path: Path, content: str) -> None:
    """Write guidelines inside hub:begin/hub:end markers."""
    # Create parent dirs
    path.parent.mkdir(parents=True, exist_ok=True)

    new_block = f"{HUB_BEGIN}\n{content}\n{HUB_END}\n"

    if path.exists():
        text = path.read_text(encoding="utf-8")
        # Replace existing block
        begin_idx = text.find(HUB_BEGIN)
        end_idx = text.find(HUB_END)
        if begin_idx != -1 and end_idx != -1:
            end_idx += len(HUB_END)
            text = text[:begin_idx] + new_block + text[end_idx:]
        else:
            # Append block
            text = text.rstrip() + "\n" + new_block
        path.write_text(text, encoding="utf-8")
    else:
        path.write_text(new_block, encoding="utf-8")


def sync_all_agents() -> None:
    """Sync all agents."""
    config = load_config()
    for agent_name in config.get("agents", {}):
        try:
            sync_agent(agent_name)
        except Exception:
            pass
