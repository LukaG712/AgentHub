"""Marketplace API routes — Package registry for agents, skills, and templates."""

import logging
from typing import Optional

from fastapi import HTTPException, Query, UploadFile
from fastapi.responses import Response

from hub.api.core import _verify_token
from hub.marketplace import registry

logger = logging.getLogger(__name__)


def api_get_stats():
    """Get marketplace statistics."""
    return registry.get_stats()


def api_list_packages(
    pkg_type: Optional[str] = Query(None, description="Filter by type: agent, skill, template"),
    category: Optional[str] = Query(None, description="Filter by category"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    search: Optional[str] = Query(None, description="Search by name, title, or description"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List published packages with optional filters."""
    return registry.list_packages(
        pkg_type=pkg_type,
        category=category,
        tag=tag,
        search=search,
        limit=limit,
        offset=offset,
    )


def api_get_categories():
    """Get all unique categories."""
    return {"categories": registry.get_categories()}


def api_get_tags():
    """Get all unique tags."""
    return {"tags": registry.get_tags()}


def api_get_package(pkg_id: str):
    """Get a package by ID."""
    package = registry.get_package(pkg_id)
    if not package:
        raise HTTPException(status_code=404, detail=f"Package not found: {pkg_id}")
    return package


def api_get_package_by_name(name: str, pkg_type: str):
    """Get the latest version of a package by name and type."""
    package = registry.get_package_by_name(name, pkg_type)
    if not package:
        raise HTTPException(status_code=404, detail=f"Package not found: {pkg_type}/{name}")
    return package


def api_get_package_versions(name: str, pkg_type: str):
    """Get all versions of a package."""
    versions = registry.get_package_versions(name, pkg_type)
    if not versions:
        raise HTTPException(status_code=404, detail=f"Package not found: {pkg_type}/{name}")
    return versions


def api_publish_package(
    pkg_type: str,
    name: str,
    version: str,
    config: dict,
    title: str = "",
    description: str = "",
    author: str = "",
    category: str = "",
    tags: Optional[list] = None,
    dependencies: Optional[list] = None,
    metadata: Optional[dict] = None,
):
    """Publish a new package or update an existing one."""
    try:
        pkg_id = registry.publish(
            pkg_type=pkg_type,
            name=name,
            version=version,
            config=config,
            title=title,
            description=description,
            author=author,
            category=category,
            tags=tags,
            dependencies=dependencies,
            metadata=metadata,
        )
        return {
            "id": pkg_id,
            "type": pkg_type,
            "name": name,
            "version": version,
            "message": f"Published {pkg_type} '{name}' v{version}",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def api_import_package(file: UploadFile):
    """Import a package from a tar.gz archive."""
    data = file.file.read()
    try:
        pkg_id = registry.import_package(data)
        return {
            "id": pkg_id,
            "message": "Package imported successfully",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def api_export_package(pkg_id: str):
    """Export a package as a tar.gz archive."""
    try:
        data = registry.export_package(pkg_id)
        package = registry.get_package(pkg_id)
        filename = f"{package['name']}-{package['type']}-{package['version']}.tar.gz" if package else f"package-{pkg_id}.tar.gz"
        return Response(
            content=data,
            media_type="application/gzip",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


def api_install_package(
    pkg_id: str,
    install_name: Optional[str] = None,
    custom_config: Optional[dict] = None,
):
    """Install a package from the registry."""
    try:
        result = registry.install(pkg_id, install_name=install_name, custom_config=custom_config)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("message", "Installation failed"))
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


def api_list_installed(
    pkg_type: Optional[str] = Query(None, description="Filter by type"),
):
    """List all installed packages."""
    return registry.list_installed(pkg_type=pkg_type)


def api_uninstall_package(install_id: str):
    """Uninstall a previously installed package."""
    try:
        result = registry.uninstall(install_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


def api_unpublish_package(pkg_id: str):
    """Unpublish a package (soft delete)."""
    package = registry.get_package(pkg_id)
    if not package:
        # Check if it exists but is unpublished
        import sqlite3
        row = registry._db.execute(
            "SELECT id FROM packages WHERE id = ?", (pkg_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Package not found: {pkg_id}")
    registry.unpublish(pkg_id)
    return {"message": f"Package {pkg_id} unpublished"}


def api_delete_package(pkg_id: str):
    """Permanently delete a package."""
    registry.delete_package(pkg_id)
    return {"message": f"Package {pkg_id} deleted permanently"}


def api_publish_from_agent(agent_name: str, version: str = "1.0.0", **kwargs):
    """Publish an existing agent as a marketplace package."""
    try:
        from hub.agents import get_agent
        agent = get_agent(agent_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_name}")

    config = {
        "runner": agent.get("runner", "junie"),
        "project_dir": agent.get("project_dir", ""),
        "title": agent.get("title", ""),
        "description": agent.get("description", ""),
        "skills": agent.get("skills", []),
        "guidelines": agent.get("guidelines", ""),
        "permissions": agent.get("permissions"),
    }

    pkg_id = registry.publish(
        pkg_type="agent",
        name=agent_name,
        version=version,
        config=config,
        title=agent.get("title", agent_name),
        description=agent.get("description", ""),
        **{k: v for k, v in kwargs.items() if v},
    )
    return {
        "id": pkg_id,
        "type": "agent",
        "name": agent_name,
        "version": version,
        "message": f"Published agent '{agent_name}' v{version} to marketplace",
    }


def api_publish_from_skill(skill_name: str, version: str = "1.0.0", **kwargs):
    """Publish an existing skill as a marketplace package."""
    from pathlib import Path

    skills_dir = Path(__file__).resolve().parent.parent / "skills"
    skill_dir = skills_dir / skill_name
    skill_md_path = skill_dir / "SKILL.md"

    if not skill_md_path.exists():
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

    # Read SKILL.md content
    skill_md = skill_md_path.read_text(encoding="utf-8")

    # Extract description from frontmatter
    description = ""
    if skill_md.startswith("---"):
        end = skill_md.find("---", 3)
        if end != -1:
            frontmatter = skill_md[3:end]
            for line in frontmatter.split("\n"):
                if line.startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip('"').strip("'")
                    break

    # Read reference files
    reference_files = {}
    ref_dir = skill_dir / "reference"
    if ref_dir.exists():
        for f in ref_dir.rglob("*"):
            if f.is_file():
                reference_files[f.relative_to(ref_dir).as_posix()] = f.read_text(encoding="utf-8")

    config = {
        "skill_md": skill_md,
        "description": description,
        "reference_files": reference_files,
    }

    pkg_id = registry.publish(
        pkg_type="skill",
        name=skill_name,
        version=version,
        config=config,
        title=skill_name,
        description=description,
        **{k: v for k, v in kwargs.items() if v},
    )
    return {
        "id": pkg_id,
        "type": "skill",
        "name": skill_name,
        "version": version,
        "message": f"Published skill '{skill_name}' v{version} to marketplace",
    }


def api_publish_from_template(template_id: str, version: str = "1.0.0", **kwargs):
    """Publish an existing template as a marketplace package."""
    from hub.api.core import _templates, _templates_lock

    with _templates_lock:
        template = _templates.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")

    config = {
        "type": template.get("type", "pipeline"),
        "description": template.get("description", ""),
        "content": template.get("content", ""),
        "variables": template.get("variables", []),
        "tags": template.get("tags", []),
    }

    pkg_id = registry.publish(
        pkg_type="template",
        name=template.get("name", template_id),
        version=version,
        config=config,
        title=template.get("name", template_id),
        description=template.get("description", ""),
        **{k: v for k, v in kwargs.items() if v},
    )
    return {
        "id": pkg_id,
        "type": "template",
        "name": template.get("name", template_id),
        "version": version,
        "message": f"Published template '{template.get('name', template_id)}' v{version} to marketplace",
    }


def register(app):
    """Register marketplace routes with the FastAPI app."""
    # Stats and browsing
    app.get("/api/marketplace/stats")(api_get_stats)
    app.get("/api/marketplace/packages")(api_list_packages)
    app.get("/api/marketplace/categories")(api_get_categories)
    app.get("/api/marketplace/tags")(api_get_tags)

    # Package details
    app.get("/api/marketplace/packages/{pkg_id}")(api_get_package)
    app.get("/api/marketplace/{pkg_type}/{name}")(api_get_package_by_name)
    app.get("/api/marketplace/{pkg_type}/{name}/versions")(api_get_package_versions)

    # Publish
    app.post("/api/marketplace/packages", status_code=201)(api_publish_package)
    app.post("/api/marketplace/import", status_code=201)(api_import_package)
    app.get("/api/marketplace/packages/{pkg_id}/export")(api_export_package)

    # Publish from existing resources
    app.post("/api/marketplace/agents/{agent_name}/publish", status_code=201)(api_publish_from_agent)
    app.post("/api/marketplace/skills/{skill_name}/publish", status_code=201)(api_publish_from_skill)
    app.post("/api/marketplace/templates/{template_id}/publish", status_code=201)(api_publish_from_template)

    # Install/Uninstall
    app.post("/api/marketplace/packages/{pkg_id}/install", status_code=201)(api_install_package)
    app.get("/api/marketplace/installed")(api_list_installed)
    app.delete("/api/marketplace/installed/{install_id}")(api_uninstall_package)

    # Package management
    app.put("/api/marketplace/packages/{pkg_id}/unpublish")(api_unpublish_package)
    app.delete("/api/marketplace/packages/{pkg_id}")(api_delete_package)
