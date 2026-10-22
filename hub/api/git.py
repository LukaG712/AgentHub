"""Route module: git."""

from fastapi import Depends

from hub.api.core import _verify_token


async def api_git_status(
    project: str,
    _auth: None = Depends(_verify_token),
):
    """Get Git status for a project directory."""
    from hub import git_service
    status = git_service.get_git_status(project)
    return status.to_dict()


async def api_git_worktrees(
    project: str,
    _auth: None = Depends(_verify_token),
):
    """List worktrees for a Git repository."""
    from hub import git_service
    worktrees = git_service.list_worktrees(project)
    return {"worktrees": [wt.to_dict() for wt in worktrees]}


# --- Multi-Agent Coordinator ---



def register(app):
    """Register git routes with the FastAPI app."""
    app.get("/api/git/status")(api_git_status)
    app.get("/api/git/worktrees")(api_git_worktrees)
