"""Tests for hub/skills.py"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from hub.config import save_config
from hub import skills


@pytest.fixture
def hub_env(tmp_path):
    """Set up a temporary hub config and skills dir for testing."""
    config_path = tmp_path / "hub.yaml"
    config = {
        "runners": {
            "junie": {
                "command": ["junie", "--task", "{task}", "--project", "{project}"],
                "skills_dir": ".junie/skills",
                "guidelines_file": ".junie/AGENTS.md",
            }
        },
        "agents": {
            "vault": {
                "title": "Vault",
                "runner": "junie",
                "project_dir": str(tmp_path / "vault-project"),
                "skills": [],
                "guidelines": "Never delete files.",
            }
        },
    }
    save_config(config, config_path)

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    old_config = os.environ.get("HUB_CONFIG")
    os.environ["HUB_CONFIG"] = str(config_path)

    with patch("hub.skills._SKILLS_DIR", skills_dir):
        yield tmp_path, config_path, skills_dir

    if old_config is not None:
        os.environ["HUB_CONFIG"] = old_config
    else:
        os.environ.pop("HUB_CONFIG", None)


class TestListSkills:
    def test_empty_list(self, hub_env):
        assert skills.list_skills() == []

    def test_list_after_create(self, hub_env):
        skills.create_skill("test-skill", "A test skill")
        skill_list = skills.list_skills()
        assert len(skill_list) == 1
        assert skill_list[0]["name"] == "test-skill"


class TestCreateSkill:
    def test_create_basic(self, hub_env):
        result = skills.create_skill("test-skill", "A test skill")
        assert result["name"] == "test-skill"
        assert result["description"] == "A test skill"
        skill_md = hub_env[2] / "test-skill" / "SKILL.md"
        assert skill_md.exists()

    def test_create_with_content(self, hub_env):
        result = skills.create_skill("test-skill", "Desc", content="# Custom content\n")
        skill_md = hub_env[2] / "test-skill" / "SKILL.md"
        assert "# Custom content" in skill_md.read_text()

    def test_create_invalid_name(self, hub_env):
        with pytest.raises(ValueError, match="Invalid"):
            skills.create_skill("Bad Name", "desc")

    def test_create_duplicate(self, hub_env):
        skills.create_skill("test-skill", "A test skill")
        with pytest.raises(ValueError, match="already exists"):
            skills.create_skill("test-skill", "Another")


class TestUpdateSkill:
    def test_update_content(self, hub_env):
        skills.create_skill("test-skill", "Old desc")
        result = skills.update_skill("test-skill", content="# New content\n")
        skill_md = hub_env[2] / "test-skill" / "SKILL.md"
        assert "# New content" in skill_md.read_text()

    def test_update_description(self, hub_env):
        skills.create_skill("test-skill", "Old desc")
        result = skills.update_skill("test-skill", description="New desc")
        assert result["description"] == "New desc"

    def test_update_nonexistent(self, hub_env):
        with pytest.raises(KeyError, match="not found"):
            skills.update_skill("nonexistent", description="X")


class TestDeleteSkill:
    def test_delete_existing(self, hub_env):
        skills.create_skill("test-skill", "A test skill")
        skills.delete_skill("test-skill")
        assert not (hub_env[2] / "test-skill").exists()

    def test_delete_nonexistent(self, hub_env):
        with pytest.raises(KeyError, match="not found"):
            skills.delete_skill("nonexistent")


class TestSkillUsage:
    def test_no_usage(self, hub_env):
        skills.create_skill("test-skill", "A test skill")
        assert skills.skill_usage("test-skill") == []

    def test_usage_after_enable(self, hub_env):
        skills.create_skill("test-skill", "A test skill")
        skills.enable_skill("vault", "test-skill")
        usage = skills.skill_usage("test-skill")
        assert "vault" in usage


class TestEnableDisableSkill:
    def test_enable_skill(self, hub_env):
        skills.create_skill("test-skill", "A test skill")
        skills.enable_skill("vault", "test-skill")
        from hub.config import load_config
        config = load_config(hub_env[1])
        assert "test-skill" in config["agents"]["vault"]["skills"]

    def test_disable_skill(self, hub_env):
        skills.create_skill("test-skill", "A test skill")
        skills.enable_skill("vault", "test-skill")
        skills.disable_skill("vault", "test-skill")
        from hub.config import load_config
        config = load_config(hub_env[1])
        assert "test-skill" not in config["agents"]["vault"]["skills"]

    def test_enable_nonexistent_agent(self, hub_env):
        skills.create_skill("test-skill", "A test skill")
        with pytest.raises(KeyError, match="not found"):
            skills.enable_skill("nonexistent", "test-skill")

    def test_enable_nonexistent_skill(self, hub_env):
        with pytest.raises(KeyError, match="not found"):
            skills.enable_skill("vault", "nonexistent")


class TestSyncAgent:
    def test_sync_creates_skills_dir(self, hub_env):
        tmp_path, _, _ = hub_env
        project_dir = tmp_path / "vault-project"
        project_dir.mkdir()
        skills.sync_agent("vault")
        agent_skills = project_dir / ".junie" / "skills"
        assert agent_skills.exists()

    def test_sync_creates_guidelines(self, hub_env):
        tmp_path, _, _ = hub_env
        project_dir = tmp_path / "vault-project"
        project_dir.mkdir()
        skills.sync_agent("vault")
        guidelines = project_dir / ".junie" / "AGENTS.md"
        assert guidelines.exists()
        content = guidelines.read_text()
        assert "<!-- hub:begin -->" in content
        assert "<!-- hub:end -->" in content
        assert "Never delete files" in content

    def test_sync_replaces_guidelines_block(self, hub_env):
        tmp_path, _, _ = hub_env
        project_dir = tmp_path / "vault-project"
        project_dir.mkdir()
        guidelines = project_dir / ".junie" / "AGENTS.md"
        guidelines.parent.mkdir(parents=True)
        guidelines.write_text("Some existing content\n")
        skills.sync_agent("vault")
        content = guidelines.read_text()
        assert "Some existing content" in content
        assert "<!-- hub:begin -->" in content
        assert "Never delete files" in content

    def test_sync_creates_skill_symlinks(self, hub_env):
        tmp_path, _, _ = hub_env
        project_dir = tmp_path / "vault-project"
        project_dir.mkdir()
        skills.create_skill("test-skill", "A test skill")
        skills.enable_skill("vault", "test-skill")
        skills.sync_agent("vault")
        agent_skills = project_dir / ".junie" / "skills"
        skill_link = agent_skills / "test-skill"
        assert skill_link.exists()

    def test_sync_removes_stale_symlinks(self, hub_env):
        tmp_path, _, _ = hub_env
        project_dir = tmp_path / "vault-project"
        project_dir.mkdir()
        skills.create_skill("test-skill", "A test skill")
        skills.enable_skill("vault", "test-skill")
        skills.sync_agent("vault")
        # Now disable
        skills.disable_skill("vault", "test-skill")
        skills.sync_agent("vault")
        agent_skills = project_dir / ".junie" / "skills"
        skill_link = agent_skills / "test-skill"
        # Should be removed (symlink or copy)
        assert not skill_link.exists()

    def test_sync_leaves_foreign_files(self, hub_env):
        tmp_path, _, _ = hub_env
        project_dir = tmp_path / "vault-project"
        project_dir.mkdir()
        agent_skills = project_dir / ".junie" / "skills"
        agent_skills.mkdir(parents=True)
        # Create a foreign file
        foreign = agent_skills / "my-custom-file.txt"
        foreign.write_text("my data")
        skills.sync_agent("vault")
        assert foreign.exists()


class TestPathSafety:
    def test_path_traversal_rejected(self, hub_env):
        with pytest.raises(ValueError, match="escapes"):
            skills._skill_path("../etc/passwd")

    def test_path_traversal_in_create(self, hub_env):
        with pytest.raises(ValueError):
            skills.create_skill("../evil", "evil skill")


class TestGuidelinesBlock:
    def test_write_new_file(self, hub_env):
        tmp_path, _, _ = hub_env
        path = tmp_path / "new" / "guidelines.md"
        skills._write_guidelines_block(path, "Be nice")
        content = path.read_text()
        assert "<!-- hub:begin -->" in content
        assert "Be nice" in content
        assert "<!-- hub:end -->" in content

    def test_replace_existing_block(self, hub_env):
        tmp_path, _, _ = hub_env
        path = tmp_path / "guidelines.md"
        path.write_text(
            "Before\n"
            "<!-- hub:begin -->\n"
            "Old content\n"
            "<!-- hub:end -->\n"
            "After\n"
        )
        skills._write_guidelines_block(path, "New content")
        content = path.read_text()
        assert "Before" in content
        assert "Old content" not in content
        assert "New content" in content
        assert "After" in content
