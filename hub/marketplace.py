"""Agent Marketplace — Registry for sharing agents, skills, and templates.

Provides a local registry for publishing, browsing, and installing packages
(agents, skills, templates) so they can be shared across deployments.

Key features:
- SQLite-based registry for persistent package storage
- Standardized package manifest with version, dependencies, and metadata
- Publish agents, skills, and templates to the registry
- Browse and search packages by type, category, tags, and keywords
- Install packages from registry to local deployment
- Uninstall packages cleanly, removing all associated files
- Version management with semantic versioning
- Dependency resolution during installation

Package types:
- agent: A complete agent configuration with runner, skills, and guidelines
- skill: A reusable skill with SKILL.md and reference files
- template: A reusable pipeline/task template with variable substitution

Usage:
    from hub.marketplace import registry

    # Initialize on startup
    registry.initialize()

    # Publish a package
    pkg_id = registry.publish("agent", "my-agent", "1.0.0", config_data)

    # Browse packages
    packages = registry.list_packages(type="agent", category="research")

    # Install a package
    registry.install(pkg_id)

    # Uninstall a package
    registry.uninstall(pkg_id)
"""

import json
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Registry database path
_REGISTRY_DB = Path(__file__).resolve().parent.parent / "marketplace.db"
# Packages storage directory
_PACKAGES_DIR = Path(__file__).resolve().parent.parent / "marketplace_packages"


class MarketplaceRegistry:
    """SQLite-based registry for marketplace packages."""

    def __init__(self):
        self._db_path = _REGISTRY_DB
        self._packages_dir = _PACKAGES_DIR
        self._db: Optional[sqlite3.Connection] = None

    def initialize(self) -> None:
        """Initialize the registry database and directories."""
        self._packages_dir.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self._db_path))
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        logger.info("Marketplace registry initialized at %s", self._db_path)

    def _create_tables(self) -> None:
        """Create registry tables if they don't exist."""
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS packages (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('agent', 'skill', 'template')),
                version TEXT NOT NULL,
                title TEXT,
                description TEXT,
                author TEXT,
                category TEXT,
                tags TEXT,  -- JSON array
                dependencies TEXT,  -- JSON array of {"name": "x", "version": "y"}
                config TEXT NOT NULL,  -- JSON: package configuration/data
                metadata TEXT,  -- JSON: additional metadata
                published_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                download_count INTEGER DEFAULT 0,
                install_count INTEGER DEFAULT 0,
                is_featured INTEGER DEFAULT 0,
                is_published INTEGER DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_packages_type ON packages(type);
            CREATE INDEX IF NOT EXISTS idx_packages_name ON packages(name);
            CREATE INDEX IF NOT EXISTS idx_packages_category ON packages(category);
            CREATE INDEX IF NOT EXISTS idx_packages_published ON packages(is_published);

            CREATE TABLE IF NOT EXISTS installed_packages (
                id TEXT PRIMARY KEY,
                package_id TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                version TEXT NOT NULL,
                installed_at TEXT NOT NULL,
                config TEXT,  -- JSON: installation-specific config
                FOREIGN KEY (package_id) REFERENCES packages(id)
            );

            CREATE INDEX IF NOT EXISTS idx_installed_type ON installed_packages(type);

            CREATE TABLE IF NOT EXISTS package_versions (
                id TEXT PRIMARY KEY,
                package_name TEXT NOT NULL,
                package_type TEXT NOT NULL,
                version TEXT NOT NULL,
                published_at TEXT NOT NULL,
                FOREIGN KEY (package_name, package_type, version)
                    REFERENCES packages(name, type, version)
            );

            CREATE INDEX IF NOT EXISTS idx_versions_name ON package_versions(package_name);
        """)
        self._db.commit()

    def _next_id(self) -> str:
        """Generate a unique package ID."""
        return f"pkg-{uuid.uuid4().hex[:12]}"

    def publish(
        self,
        pkg_type: str,
        name: str,
        version: str,
        config: Dict[str, Any],
        title: str = "",
        description: str = "",
        author: str = "",
        category: str = "",
        tags: Optional[List[str]] = None,
        dependencies: Optional[List[Dict[str, str]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Publish a new package or update an existing one.

        Returns the package ID.
        """
        if pkg_type not in ("agent", "skill", "template"):
            raise ValueError(f"Invalid package type: {pkg_type}")

        pkg_id = self._next_id()
        now = datetime.now(timezone.utc).isoformat()

        # Check if this name/version already exists
        existing = self._db.execute(
            "SELECT id FROM packages WHERE name = ? AND type = ? AND version = ?",
            (name, pkg_type, version),
        ).fetchone()

        if existing:
            # Update existing package
            self._db.execute(
                """UPDATE packages
                   SET config = ?, title = ?, description = ?, author = ?,
                       category = ?, tags = ?, dependencies = ?, metadata = ?,
                       updated_at = ?
                   WHERE name = ? AND type = ? AND version = ?""",
                (
                    json.dumps(config), title, description, author,
                    category, json.dumps(tags or []),
                    json.dumps(dependencies or []), json.dumps(metadata or {}),
                    now, name, pkg_type, version,
                ),
            )
            pkg_id = existing["id"]
            logger.info("Updated package: %s %s %s", pkg_type, name, version)
        else:
            # Insert new package
            self._db.execute(
                """INSERT INTO packages
                   (id, name, type, version, title, description, author,
                    category, tags, dependencies, config, metadata,
                    published_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    pkg_id, name, pkg_type, version, title, description, author,
                    category, json.dumps(tags or []),
                    json.dumps(dependencies or []), json.dumps(config),
                    json.dumps(metadata or {}), now, now,
                ),
            )
            # Track version
            self._db.execute(
                """INSERT INTO package_versions
                   (id, package_name, package_type, version, published_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (self._next_id(), name, pkg_type, version, now),
            )
            logger.info("Published package: %s %s %s", pkg_type, name, version)

        self._db.commit()
        return pkg_id

    def get_package(self, pkg_id: str) -> Optional[Dict[str, Any]]:
        """Get a package by ID."""
        row = self._db.execute(
            "SELECT * FROM packages WHERE id = ? AND is_published = 1", (pkg_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_package_by_name(self, name: str, pkg_type: str, version: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get a package by name and type, optionally with version."""
        if version:
            row = self._db.execute(
                "SELECT * FROM packages WHERE name = ? AND type = ? AND version = ? AND is_published = 1",
                (name, pkg_type, version),
            ).fetchone()
        else:
            # Get latest version
            row = self._db.execute(
                """SELECT * FROM packages
                   WHERE name = ? AND type = ? AND is_published = 1
                   ORDER BY published_at DESC LIMIT 1""",
                (name, pkg_type),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_packages(
        self,
        pkg_type: Optional[str] = None,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List packages with optional filters."""
        query = "SELECT * FROM packages WHERE is_published = 1"
        params: List[Any] = []

        if pkg_type:
            query += " AND type = ?"
            params.append(pkg_type)
        if category:
            query += " AND category = ?"
            params.append(category)
        if tag:
            query += " AND tags LIKE ?"
            params.append(f"%\"{tag}\"%")
        if search:
            query += " AND (name LIKE ? OR title LIKE ? OR description LIKE ?)"
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])

        query += " ORDER BY published_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._db.execute(query, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_package_versions(self, name: str, pkg_type: str) -> List[Dict[str, Any]]:
        """Get all versions of a package."""
        rows = self._db.execute(
            """SELECT * FROM packages
               WHERE name = ? AND type = ? AND is_published = 1
               ORDER BY published_at DESC""",
            (name, pkg_type),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_categories(self) -> List[str]:
        """Get all unique categories."""
        rows = self._db.execute(
            "SELECT DISTINCT category FROM packages WHERE category IS NOT NULL AND category != '' AND is_published = 1"
        ).fetchall()
        return [row["category"] for row in rows if row["category"]]

    def get_tags(self) -> List[str]:
        """Get all unique tags."""
        rows = self._db.execute(
            "SELECT tags FROM packages WHERE tags IS NOT NULL AND tags != '[]' AND is_published = 1"
        ).fetchall()
        tags = set()
        for row in rows:
            try:
                tag_list = json.loads(row["tags"])
                tags.update(tag_list)
            except (json.JSONDecodeError, TypeError):
                pass
        return sorted(tags)

    def install(
        self,
        pkg_id: str,
        install_name: Optional[str] = None,
        custom_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Install a package from the registry.

        Returns installation details including any conflicts or errors.
        """
        package = self.get_package(pkg_id)
        if not package:
            raise ValueError(f"Package not found: {pkg_id}")

        name = install_name or package["name"]
        pkg_type = package["type"]
        version = package["version"]
        config = json.loads(package["config"])

        # Check for conflicts
        conflicts = self._check_conflicts(pkg_type, name)

        # Check dependencies
        dependencies = json.loads(package.get("dependencies") or "[]")
        missing_deps = self._check_dependencies(dependencies)

        if missing_deps:
            return {
                "success": False,
                "package_id": pkg_id,
                "name": name,
                "type": pkg_type,
                "version": version,
                "conflicts": conflicts,
                "missing_dependencies": missing_deps,
                "message": f"Missing dependencies: {', '.join(missing_deps)}",
            }

        # Perform installation based on type
        install_result = self._install_package(pkg_type, name, version, config, custom_config)

        # Track installation
        install_id = self._next_id()
        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            """INSERT INTO installed_packages
               (id, package_id, name, type, version, installed_at, config)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (install_id, pkg_id, name, pkg_type, version, now,
             json.dumps(custom_config or {})),
        )

        # Update install count
        self._db.execute(
            "UPDATE packages SET install_count = install_count + 1 WHERE id = ?",
            (pkg_id,),
        )
        self._db.commit()

        return {
            "success": True,
            "install_id": install_id,
            "package_id": pkg_id,
            "name": name,
            "type": pkg_type,
            "version": version,
            "conflicts": conflicts,
            "result": install_result,
            "message": f"Successfully installed {pkg_type} '{name}' v{version}",
        }

    def _check_conflicts(self, pkg_type: str, name: str) -> List[Dict[str, Any]]:
        """Check for naming conflicts with existing installations."""
        conflicts = []

        if pkg_type == "agent":
            # Check if agent already exists
            try:
                from hub.agents import agent_exists
                if agent_exists(name):
                    conflicts.append({
                        "type": "agent",
                        "name": name,
                        "issue": "An agent with this name already exists",
                    })
            except ImportError:
                pass

        elif pkg_type == "skill":
            # Check if skill directory already exists
            skills_dir = Path(__file__).resolve().parent.parent / "skills" / name
            if skills_dir.exists():
                conflicts.append({
                    "type": "skill",
                    "name": name,
                    "issue": "A skill with this name already exists",
                })

        elif pkg_type == "template":
            # Check templates store
            from hub.api.core import _templates, _templates_lock
            with _templates_lock:
                for tid, t in _templates.items():
                    if t.get("name") == name:
                        conflicts.append({
                            "type": "template",
                            "name": name,
                            "issue": "A template with this name already exists",
                        })
                        break

        return conflicts

    def _check_dependencies(self, dependencies: List[Dict[str, str]]) -> List[str]:
        """Check if all dependencies are installed."""
        missing = []
        for dep in dependencies:
            dep_name = dep.get("name", "")
            dep_type = dep.get("type", "agent")
            dep_version = dep.get("version", "")

            # Check if dependency is installed
            installed = self._db.execute(
                """SELECT 1 FROM installed_packages ip
                   JOIN packages p ON ip.package_id = p.id
                   WHERE ip.name = ? AND ip.type = ?""",
                (dep_name, dep_type),
            ).fetchone()

            if not installed:
                missing.append(f"{dep_type}:{dep_name}")

        return missing

    def _install_package(
        self,
        pkg_type: str,
        name: str,
        version: str,
        config: Dict[str, Any],
        custom_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Install a package based on its type."""
        if pkg_type == "agent":
            return self._install_agent(name, config, custom_config)
        elif pkg_type == "skill":
            return self._install_skill(name, config, custom_config)
        elif pkg_type == "template":
            return self._install_template(name, config, custom_config)
        else:
            raise ValueError(f"Cannot install unknown package type: {pkg_type}")

    def _install_agent(
        self,
        name: str,
        config: Dict[str, Any],
        custom_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Install an agent from package config."""
        from hub.agents import create_agent

        # Merge custom config overrides
        agent_config = {
            "runner": config.get("runner", "junie"),
            "project_dir": config.get("project_dir", f"./agents/{name}"),
            "title": config.get("title", name),
            "description": config.get("description", ""),
            "skills": config.get("skills", []),
            "guidelines": config.get("guidelines", ""),
            "permissions": config.get("permissions"),
        }
        if custom_config:
            agent_config.update({k: v for k, v in custom_config.items() if v is not None})

        # Create the agent
        result = create_agent(name, **agent_config)

        # Install skills if specified
        installed_skills = []
        for skill_name in agent_config.get("skills", []):
            skill_pkg = self.get_package_by_name(skill_name, "skill")
            if skill_pkg:
                try:
                    self.install(skill_pkg["id"])
                    installed_skills.append(skill_name)
                except Exception as e:
                    logger.warning("Failed to install skill %s: %s", skill_name, e)

        return {
            "agent": result,
            "installed_skills": installed_skills,
        }

    def _install_skill(
        self,
        name: str,
        config: Dict[str, Any],
        custom_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Install a skill from package config."""
        from hub.skills import create_skill

        skill_md = config.get("skill_md", "")
        description = config.get("description", "")

        if not skill_md:
            skill_md = f"---\nname: {name}\ndescription: {description}\n---\n\n{description}\n"

        result = create_skill(name, description=description, content=skill_md)

        # Copy reference files if present
        reference_files = config.get("reference_files", {})
        if reference_files:
            skills_dir = Path(__file__).resolve().parent.parent / "skills" / name
            ref_dir = skills_dir / "reference"
            ref_dir.mkdir(parents=True, exist_ok=True)
            for filename, content in reference_files.items():
                (ref_dir / filename).write_text(content, encoding="utf-8")

        return result

    def _install_template(
        self,
        name: str,
        config: Dict[str, Any],
        custom_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Install a template from package config."""
        from hub.api.core import _templates, _templates_lock

        template_id = f"tpl-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        template = {
            "id": template_id,
            "name": name,
            "type": config.get("type", "pipeline"),
            "description": config.get("description", ""),
            "content": config.get("content", ""),
            "variables": config.get("variables", []),
            "tags": config.get("tags", []),
            "created_at": now,
            "updated_at": now,
            "usage_count": 0,
        }
        if custom_config:
            template.update({k: v for k, v in custom_config.items() if v is not None})

        with _templates_lock:
            _templates[template_id] = template

        # Persist to feature store
        try:
            from hub import feature_store
            feature_store.save_template(template)
        except Exception as e:
            logger.warning("Failed to persist template: %s", e)

        return template

    def uninstall(self, install_id: str) -> Dict[str, Any]:
        """Uninstall a previously installed package."""
        row = self._db.execute(
            "SELECT * FROM installed_packages WHERE id = ?", (install_id,)
        ).fetchone()

        if not row:
            raise ValueError(f"Installation not found: {install_id}")

        pkg_type = row["type"]
        name = row["name"]

        # Remove based on type
        if pkg_type == "agent":
            try:
                from hub.agents import delete_agent_by_name
                delete_agent_by_name(name)
            except (ImportError, KeyError) as e:
                logger.warning("Failed to delete agent %s: %s", name, e)

        elif pkg_type == "skill":
            skills_dir = Path(__file__).resolve().parent.parent / "skills" / name
            if skills_dir.exists():
                shutil.rmtree(skills_dir)

        elif pkg_type == "template":
            from hub.api.core import _templates, _templates_lock
            to_remove = []
            with _templates_lock:
                for tid, t in _templates.items():
                    if t.get("name") == name:
                        to_remove.append(tid)
                        # Remove from feature store
                        try:
                            from hub import feature_store
                            feature_store.delete_template(tid)
                        except Exception:
                            pass
                for tid in to_remove:
                    _templates.pop(tid, None)

        # Remove installation record
        self._db.execute("DELETE FROM installed_packages WHERE id = ?", (install_id,))
        self._db.commit()

        return {
            "success": True,
            "install_id": install_id,
            "name": name,
            "type": pkg_type,
            "message": f"Successfully uninstalled {pkg_type} '{name}'",
        }

    def list_installed(self, pkg_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all installed packages."""
        query = """SELECT ip.*, p.title, p.description, p.author, p.category, p.tags
                   FROM installed_packages ip
                   JOIN packages p ON ip.package_id = p.id"""
        params: List[Any] = []

        if pkg_type:
            query += " WHERE ip.type = ?"
            params.append(pkg_type)

        query += " ORDER BY ip.installed_at DESC"
        rows = self._db.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def unpublish(self, pkg_id: str) -> bool:
        """Unpublish a package (soft delete)."""
        self._db.execute(
            "UPDATE packages SET is_published = 0 WHERE id = ?", (pkg_id,)
        )
        self._db.commit()
        return True

    def delete_package(self, pkg_id: str) -> bool:
        """Permanently delete a package."""
        self._db.execute("DELETE FROM installed_packages WHERE package_id = ?", (pkg_id,))
        self._db.execute("DELETE FROM package_versions WHERE id IN (SELECT id FROM package_versions WHERE package_name IN (SELECT name FROM packages WHERE id = ?))", (pkg_id,))
        self._db.execute("DELETE FROM packages WHERE id = ?", (pkg_id,))
        self._db.commit()
        return True

    def get_stats(self) -> Dict[str, Any]:
        """Get marketplace statistics."""
        total = self._db.execute("SELECT COUNT(*) as count FROM packages WHERE is_published = 1").fetchone()["count"]
        agents = self._db.execute("SELECT COUNT(*) as count FROM packages WHERE type = 'agent' AND is_published = 1").fetchone()["count"]
        skills = self._db.execute("SELECT COUNT(*) as count FROM packages WHERE type = 'skill' AND is_published = 1").fetchone()["count"]
        templates = self._db.execute("SELECT COUNT(*) as count FROM packages WHERE type = 'template' AND is_published = 1").fetchone()["count"]
        installed = self._db.execute("SELECT COUNT(*) as count FROM installed_packages").fetchone()["count"]
        total_downloads = self._db.execute("SELECT COALESCE(SUM(download_count), 0) as total FROM packages").fetchone()["total"]
        total_installs = self._db.execute("SELECT COALESCE(SUM(install_count), 0) as total FROM packages").fetchone()["total"]

        return {
            "total_packages": total,
            "agents": agents,
            "skills": skills,
            "templates": templates,
            "installed_packages": installed,
            "total_downloads": total_downloads,
            "total_installs": total_installs,
            "categories": self.get_categories(),
            "tags": self.get_tags(),
        }

    def export_package(self, pkg_id: str) -> bytes:
        """Export a package as a tar.gz archive."""
        package = self.get_package(pkg_id)
        if not package:
            raise ValueError(f"Package not found: {pkg_id}")

        # Create tar archive in memory
        import io
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            # Add manifest
            manifest = {
                "name": package["name"],
                "type": package["type"],
                "version": package["version"],
                "title": package["title"],
                "description": package["description"],
                "author": package["author"],
                "category": package["category"],
                "tags": json.loads(package.get("tags") or "[]"),
                "dependencies": json.loads(package.get("dependencies") or "[]"),
                "config": json.loads(package["config"]),
                "metadata": json.loads(package.get("metadata") or "{}"),
                "published_at": package["published_at"],
            }
            manifest_data = json.dumps(manifest, indent=2).encode("utf-8")
            info = tarfile.TarInfo(name="manifest.json")
            info.size = len(manifest_data)
            tar.addfile(info, io.BytesIO(manifest_data))

        return buf.getvalue()

    def import_package(self, data: bytes) -> str:
        """Import a package from a tar.gz archive.

        Returns the package ID.
        """
        import io
        buf = io.BytesIO(data)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            manifest_file = tar.extractfile("manifest.json")
            if not manifest_file:
                raise ValueError("Invalid package archive: missing manifest.json")

            manifest = json.loads(manifest_file.read().decode("utf-8"))

        return self.publish(
            pkg_type=manifest["type"],
            name=manifest["name"],
            version=manifest["version"],
            config=manifest["config"],
            title=manifest.get("title", ""),
            description=manifest.get("description", ""),
            author=manifest.get("author", ""),
            category=manifest.get("category", ""),
            tags=manifest.get("tags", []),
            dependencies=manifest.get("dependencies", []),
            metadata=manifest.get("metadata", {}),
        )

    def _row_to_dict(self, row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        """Convert a database row to a dictionary with parsed JSON fields."""
        if row is None:
            return None

        result = dict(row)
        for json_field in ("tags", "dependencies", "config", "metadata"):
            if json_field in result and result[json_field]:
                try:
                    result[json_field] = json.loads(result[json_field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return result

    def shutdown(self) -> None:
        """Close the database connection."""
        if self._db:
            self._db.close()
            self._db = None


# Global singleton
registry = MarketplaceRegistry()
