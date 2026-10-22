"""Repository intelligence module.

Analyzes a target repository before mission planning to provide context
about structure, conventions, dependencies, and relevant files.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class RepoInfo:
    """Analysis result of a repository."""
    path: str = ""
    # Top-level directory structure
    directories: list[str] = field(default_factory=list)
    # Entry points (main files)
    entry_points: list[str] = field(default_factory=list)
    # Detected frameworks
    frameworks: list[str] = field(default_factory=list)
    # Build commands found
    build_commands: list[str] = field(default_factory=list)
    # Test commands found
    test_commands: list[str] = field(default_factory=list)
    # Dependencies
    dependencies: list[str] = field(default_factory=list)
    # Conventions from AGENTS.md, README, CONTRIBUTING
    conventions: list[str] = field(default_factory=list)
    # Relevant files for a mission scope
    relevant_files: list[str] = field(default_factory=list)
    # Git branch info
    current_branch: str = ""
    # Total file count
    total_files: int = 0
    # Python-specific info
    is_python: bool = False
    has_pytest: bool = False
    has_ruff: bool = False
    has_mypy: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_repository(repo_path: str, max_depth: int = 3) -> RepoInfo:
    """Analyze a repository structure and conventions.

    Args:
        repo_path: Path to the repository root.
        max_depth: Maximum directory depth to scan.

    Returns:
        RepoInfo with analysis results.
    """
    path = Path(repo_path)
    if not path.exists():
        raise ValueError(f"Repository path does not exist: {repo_path}")

    info = RepoInfo(path=str(path))

    # Directory structure
    info.directories = _get_directories(path, max_depth)

    # Entry points
    info.entry_points = _find_entry_points(path)

    # Framework detection
    info.frameworks = _detect_frameworks(path)

    # Build/test commands
    info.build_commands = _find_build_commands(path)
    info.test_commands = _find_test_commands(path)

    # Dependencies
    info.dependencies = _find_dependencies(path)

    # Conventions
    info.conventions = _read_conventions(path)

    # Python-specific checks
    info.is_python = (path / "pyproject.toml").exists() or (path / "setup.py").exists()
    info.has_pytest = _has_tool(path, "pytest")
    info.has_ruff = _has_tool(path, "ruff")
    info.has_mypy = _has_tool(path, "mypy")

    # File count
    info.total_files = sum(1 for p in path.rglob("*") if p.is_file() and not _is_hidden(p))

    return info


def find_relevant_files(repo_path: str, query: str) -> list[str]:
    """Find files in a repository relevant to a mission query.

    Uses lightweight keyword matching on file names and first lines.
    """
    path = Path(repo_path)
    if not path.exists():
        return []

    keywords = set(query.lower().split())
    relevant = []

    for file_path in path.rglob("*"):
        if not file_path.is_file():
            continue
        if _is_hidden(file_path):
            continue
        if file_path.suffix in (".pyc", ".so", ".o", ".class", ".exe", ".dll"):
            continue

        name_lower = file_path.name.lower()
        # Match file name against keywords
        if any(kw in name_lower for kw in keywords if len(kw) > 2):
            relevant.append(str(file_path.relative_to(path)))

    return relevant[:50]  # Limit to 50 files


def _get_directories(path: Path, max_depth: int) -> list[str]:
    """Get directory structure up to max_depth."""
    dirs = []
    for dirpath in path.rglob("*"):
        if not dirpath.is_dir():
            continue
        rel = dirpath.relative_to(path)
        depth = len(rel.parts)
        if depth <= max_depth:
            dirs.append(str(rel))
    return sorted(dirs)


def _find_entry_points(path: Path) -> list[str]:
    """Find common entry point files."""
    entries = []
    candidates = [
        "main.py", "app.py", "__main__.py", "index.ts", "index.js",
        "server.py", "api.py", "program.cs", "Cargo.toml",
        "package.json", "Dockerfile", "docker-compose.yml",
    ]
    for candidate in candidates:
        if (path / candidate).exists():
            entries.append(candidate)
    return entries


def _detect_frameworks(path: Path) -> list[str]:
    """Detect frameworks from common files and dependencies."""
    frameworks = []

    # Python frameworks
    if (path / "pyproject.toml").exists():
        content = (path / "pyproject.toml").read_text(errors="ignore")
        if "fastapi" in content.lower():
            frameworks.append("fastapi")
        if "django" in content.lower():
            frameworks.append("django")
        if "flask" in content.lower():
            frameworks.append("flask")
        if "pytest" in content.lower():
            frameworks.append("pytest")

    # Node.js
    if (path / "package.json").exists():
        content = (path / "package.json").read_text(errors="ignore")
        deps = content.lower()
        if "react" in deps:
            frameworks.append("react")
        if "next" in deps:
            frameworks.append("next.js")
        if "vue" in deps:
            frameworks.append("vue")
        if "express" in deps:
            frameworks.append("express")

    # Rust
    if (path / "Cargo.toml").exists():
        frameworks.append("rust")

    # Go
    if (path / "go.mod").exists():
        frameworks.append("go")

    return frameworks


def _find_build_commands(path: Path) -> list[str]:
    """Find build commands from config files."""
    commands = []

    # pyproject.toml
    pyproject = path / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text(errors="ignore")
        if "build" in content.lower():
            commands.append("python -m build")

    # Makefile
    makefile = path / "Makefile"
    if makefile.exists():
        commands.append("make")

    # package.json scripts
    package = path / "package.json"
    if package.exists():
        try:
            data = json.loads(package.read_text(errors="ignore"))
            scripts = data.get("scripts", {})
            if "build" in scripts:
                commands.append(f"npm run build")
        except json.JSONDecodeError:
            pass

    # setup.py
    if (path / "setup.py").exists():
        commands.append("python setup.py build")

    return commands


def _find_test_commands(path: Path) -> list[str]:
    """Find test commands from config files."""
    commands = []

    # pytest
    if (path / "pytest.ini").exists() or (path / "pyproject.toml").exists():
        commands.append("pytest")

    # Makefile with test target
    makefile = path / "Makefile"
    if makefile.exists():
        content = makefile.read_text(errors="ignore")
        if "test" in content.lower():
            commands.append("make test")

    # package.json
    package = path / "package.json"
    if package.exists():
        try:
            data = json.loads(package.read_text(errors="ignore"))
            scripts = data.get("scripts", {})
            if "test" in scripts:
                commands.append("npm test")
        except json.JSONDecodeError:
            pass

    return commands


def _find_dependencies(path: Path) -> list[str]:
    """Find dependencies from config files."""
    deps = []

    # requirements.txt
    req = path / "requirements.txt"
    if req.exists():
        content = req.read_text(errors="ignore")
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                deps.append(line.split("[")[0].split(">")[0].split("<")[0].split("=")[0].strip())

    # pyproject.toml
    pyproject = path / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text(errors="ignore")
        # Simple extraction of package names
        for line in content.splitlines():
            line = line.strip()
            if "=" in line and '"' in line:
                pkg = line.split('"')[1] if '"' in line else ""
                if pkg and not pkg.startswith(".") and len(pkg) < 50:
                    deps.append(pkg)

    # package.json
    package = path / "package.json"
    if package.exists():
        try:
            data = json.loads(package.read_text(errors="ignore"))
            for dep_name in data.get("dependencies", {}).keys():
                deps.append(dep_name)
            for dep_name in data.get("devDependencies", {}).keys():
                deps.append(dep_name)
        except json.JSONDecodeError:
            pass

    return list(set(deps))[:50]


def _read_conventions(path: Path) -> list[str]:
    """Read conventions from documentation files."""
    conventions = []
    conv_files = ["AGENTS.md", "README.md", "README", "CONTRIBUTING.md", "CONTRIBUTING"]

    for fname in conv_files:
        file_path = path / fname
        if file_path.exists():
            content = file_path.read_text(errors="ignore")
            # Extract first 2000 chars as convention summary
            conventions.append(f"{fname}: {content[:2000]}")

    return conventions


def _has_tool(path: Path, tool_name: str) -> bool:
    """Check if a tool is referenced in config files."""
    pyproject = path / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text(errors="ignore")
        return tool_name in content

    req = path / "requirements.txt"
    if req.exists():
        content = req.read_text(errors="ignore")
        return tool_name in content

    return False


def _is_hidden(path: Path) -> bool:
    """Check if a path is hidden (starts with .)."""
    return any(part.startswith(".") for part in path.parts)
