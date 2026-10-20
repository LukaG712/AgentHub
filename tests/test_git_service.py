"""Tests for hub/git_service.py — Git status and worktree management."""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from hub.git_service import (
    create_worktree,
    get_git_diff,
    get_git_root,
    get_git_status,
    is_git_repo,
    list_worktrees,
    remove_worktree,
)


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary Git repository."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True)
    # Create initial commit
    (repo / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "README.md"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo, capture_output=True, check=True)
    return str(repo)


class TestIsGitRepo:
    def test_git_repo(self, git_repo):
        assert is_git_repo(git_repo) is True

    def test_not_git_repo(self, tmp_path):
        assert is_git_repo(str(tmp_path)) is False

    def test_nonexistent_path(self):
        assert is_git_repo("/nonexistent/path/xyz") is False


class TestGitStatus:
    def test_clean_repo(self, git_repo):
        status = get_git_status(git_repo)
        assert status.is_git_repo is True
        assert status.is_dirty is False
        assert status.branch == "master"

    def test_dirty_repo_unstaged(self, git_repo):
        # Modify a file without staging
        (Path(git_repo) / "README.md").write_text("# Modified")
        status = get_git_status(git_repo)
        assert status.is_dirty is True
        assert "README.md" in status.unstaged

    def test_dirty_repo_staged(self, git_repo):
        # Stage a new file
        (Path(git_repo) / "new.txt").write_text("new file")
        subprocess.run(["git", "add", "new.txt"], cwd=git_repo, capture_output=True, check=True)
        status = get_git_status(git_repo)
        assert status.is_dirty is True
        assert "new.txt" in status.staged

    def test_untracked_files(self, git_repo):
        (Path(git_repo) / "untracked.txt").write_text("untracked")
        status = get_git_status(git_repo)
        assert status.is_dirty is True
        assert "untracked.txt" in status.untracked

    def test_non_git_repo(self, tmp_path):
        status = get_git_status(str(tmp_path))
        assert status.is_git_repo is False


class TestGitRoot:
    def test_git_root(self, git_repo):
        root = get_git_root(git_repo)
        assert root is not None
        assert Path(root).resolve() == Path(git_repo).resolve()

    def test_non_git_root(self, tmp_path):
        root = get_git_root(str(tmp_path))
        assert root is None


class TestGitDiff:
    def test_no_diff(self, git_repo):
        diff = get_git_diff(git_repo)
        # No diff returns empty string or None
        assert diff in (None, "")

    def test_with_diff(self, git_repo):
        (Path(git_repo) / "README.md").write_text("# Modified")
        diff = get_git_diff(git_repo)
        assert diff is not None
        assert "Modified" in diff


class TestWorktrees:
    def test_list_worktrees(self, git_repo):
        worktrees = list_worktrees(git_repo)
        # At least the main worktree should be listed
        assert len(worktrees) >= 1

    def test_create_worktree(self, git_repo, tmp_path):
        wt_path = str(tmp_path / "worktree1")
        success = create_worktree(git_repo, "master", wt_path)
        assert success is True
        assert Path(wt_path).exists()

    def test_remove_worktree(self, git_repo, tmp_path):
        wt_path = str(tmp_path / "worktree2")
        create_worktree(git_repo, "master", wt_path)
        # Try with force on Windows where remove may fail
        success = remove_worktree(wt_path, force=True)
        assert success is True
