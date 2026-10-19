"""Git service layer for safe repository inspection and worktree management.

Provides Git status, branch info, dirty tree detection, and worktree
creation/cleanup without automatic merges or resets.
"""

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class GitStatus:
    """Git repository status information."""
    is_git_repo: bool = False
    branch: str = ""
    staged: List[str] = field(default_factory=list)
    unstaged: List[str] = field(default_factory=list)
    untracked: List[str] = field(default_factory=list)
    is_dirty: bool = False
    ahead: int = 0
    behind: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_git_repo": self.is_git_repo,
            "branch": self.branch,
            "staged": self.staged,
            "unstaged": self.unstaged,
            "untracked": self.untracked,
            "is_dirty": self.is_dirty,
            "ahead": self.ahead,
            "behind": self.behind,
            "error": self.error,
        }


@dataclass
class WorktreeInfo:
    """Information about a Git worktree."""
    path: str
    branch: str
    is_current: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "branch": self.branch,
            "is_current": self.is_current,
        }


def _run_git(args: List[str], cwd: Optional[str] = None) -> Optional[str]:
    """Run a git command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def is_git_repo(path: str) -> bool:
    """Check if a path is inside a Git repository."""
    output = _run_git(["rev-parse", "--git-dir"], cwd=path)
    return output is not None


def get_git_status(path: str) -> GitStatus:
    """Get detailed Git status for a repository."""
    status = GitStatus()

    if not is_git_repo(path):
        return status

    status.is_git_repo = True

    # Branch name
    branch = _run_git(["branch", "--show-current"], cwd=path)
    if branch:
        status.branch = branch

    # Staged changes
    staged_output = _run_git(["diff", "--cached", "--name-only"], cwd=path)
    if staged_output:
        status.staged = [f for f in staged_output.split("\n") if f.strip()]

    # Unstaged changes
    unstaged_output = _run_git(["diff", "--name-only"], cwd=path)
    if unstaged_output:
        status.unstaged = [f for f in unstaged_output.split("\n") if f.strip()]

    # Untracked files
    untracked_output = _run_git(["ls-files", "--others", "--exclude-standard"], cwd=path)
    if untracked_output:
        status.untracked = [f for f in untracked_output.split("\n") if f.strip()]

    # Dirty check
    status.is_dirty = bool(status.staged or status.unstaged or status.untracked)

    # Ahead/behind (only if tracking a remote)
    track = _run_git(["rev-parse", "--abbrev-ref", "@{u}"], cwd=path)
    if track:
        count = _run_git(
            ["rev-list", "--left-right", "--count", f"HEAD...{track}"],
            cwd=path,
        )
        if count:
            parts = count.split("\t")
            if len(parts) == 2:
                status.ahead = int(parts[0])
                status.behind = int(parts[1])

    return status


def get_git_diff(path: str, staged: bool = False) -> Optional[str]:
    """Get the diff for a repository."""
    args = ["diff", "--cached"] if staged else ["diff"]
    return _run_git(args, cwd=path)


def list_worktrees(main_repo: str) -> List[WorktreeInfo]:
    """List all worktrees for a repository."""
    worktrees = []
    output = _run_git(["worktree", "list", "--porcelain"], cwd=main_repo)
    if not output:
        return worktrees

    current_dir = _run_git(["rev-parse", "--show-toplevel"], cwd=main_repo)
    lines = output.split("\n")
    for line in lines:
        if line.startswith("worktree "):
            parts = line.split()
            if len(parts) >= 2:
                wt_path = parts[1]
                branch = ""
                # Find the HEAD branch for this worktree
                for l in lines:
                    if l.startswith("HEAD ") and wt_path:
                        head_parts = l.split()
                        if len(head_parts) >= 2:
                            branch = head_parts[1]
                            break
                is_current = (Path(wt_path).resolve() == Path(current_dir or "").resolve())
                worktrees.append(WorktreeInfo(
                    path=wt_path,
                    branch=branch,
                    is_current=is_current,
                ))

    return worktrees


def create_worktree(main_repo: str, branch: str, path: str) -> bool:
    """Create a new worktree for a branch.

    Returns True on success, False on failure.
    Never forces or overwrites existing worktrees.
    """
    result = subprocess.run(
        ["git", "-C", main_repo, "worktree", "add", "--detach", path, branch],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0


def remove_worktree(path: str, force: bool = False) -> bool:
    """Remove a worktree.

    Returns True on success, False on failure.
    """
    args = ["git", "worktree", "prune", path]
    if force:
        args = ["git", "worktree", "remove", "--force", path]
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        return True
    # Fallback: try pruning from the main repo
    main_repo = _run_git(["rev-parse", "--show-toplevel"], cwd=path)
    if main_repo:
        result = subprocess.run(
            ["git", "-C", main_repo, "worktree", "prune"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return True
    # Last resort: try remove with force
    result = subprocess.run(
        ["git", "worktree", "remove", "--force", path],
        capture_output=True, text=True, timeout=30,
    )
    return result.returncode == 0


def get_git_root(path: str) -> Optional[str]:
    """Get the Git root directory for a path."""
    return _run_git(["rev-parse", "--show-toplevel"], cwd=path)
