"""Route module: Polter."""

from fastapi import Depends, HTTPException
from hub.api.core import _verify_token
from typing import Any, Dict, List, Optional
import httpx
import json
import time


async def api_Polter_tasks(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    _auth: None = Depends(_verify_token),
):
    """Proxy: List tasks from Polter."""
    import os
    import httpx
    base_url = os.environ.get("Polter_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Polter_API_KEY", "")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    params = {}
    if project_id:
        params["project_id"] = project_id
    if status:
        params["status"] = status
    params["limit"] = limit
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/api/v1/tasks", headers=headers, params=params)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Polter at {base_url}")


async def api_Polter_workers(_auth: None = Depends(_verify_token)):
    """Proxy: List active workers from Polter."""
    import os
    import httpx
    base_url = os.environ.get("Polter_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Polter_API_KEY", "")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/api/v1/workers", headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Polter at {base_url}")


async def api_Polter_queue(_auth: None = Depends(_verify_token)):
    """Proxy: Get queue status from Polter."""
    import os
    import httpx
    base_url = os.environ.get("Polter_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Polter_API_KEY", "")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/api/v1/queue", headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Polter at {base_url}")


async def api_Polter_projects(_auth: None = Depends(_verify_token)):
    """Proxy: List registered projects from Polter."""
    import os
    import httpx
    base_url = os.environ.get("Polter_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Polter_API_KEY", "")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/api/v1/projects", headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Polter at {base_url}")


async def api_Polter_create_project(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Proxy: Register a new project in Polter."""
    import os
    import httpx
    base_url = os.environ.get("Polter_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Polter_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{base_url}/api/v1/projects", json=body, headers=headers)
            if resp.status_code not in (200, 201):
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Polter at {base_url}")


async def api_Polter_task_detail(task_id: str, _auth: None = Depends(_verify_token)):
    """Proxy: Get a specific task detail from Polter."""
    import os
    import httpx
    base_url = os.environ.get("Polter_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Polter_API_KEY", "")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/api/v1/tasks/{task_id}", headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Polter at {base_url}")


async def api_Polter_sessions(
    task_id: Optional[str] = None,
    limit: int = 50,
    _auth: None = Depends(_verify_token),
):
    """Proxy: List sessions from Polter."""
    import os
    import httpx
    base_url = os.environ.get("Polter_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Polter_API_KEY", "")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    params = {"limit": limit}
    if task_id:
        params["task_id"] = task_id
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/api/v1/sessions", headers=headers, params=params)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Polter at {base_url}")


async def api_Polter_worker_detail(worker_id: str, _auth: None = Depends(_verify_token)):
    """Proxy: Get a specific worker detail from Polter."""
    import os
    import httpx
    base_url = os.environ.get("Polter_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Polter_API_KEY", "")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/api/v1/workers/{worker_id}", headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Polter at {base_url}")


async def api_Polter_chat(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Proxy: Execute a task via Polter's OpenAI-compatible chat endpoint."""
    import os
    import httpx
    base_url = os.environ.get("Polter_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Polter_API_KEY", "")
    messages = body.get("messages")
    if not messages:
        raise HTTPException(status_code=400, detail="messages are required")
    payload = {"messages": messages}
    payload.update({k: v for k, v in body.items() if k != "messages"})
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=1800.0) as client:
            resp = await client.post(
                f"{base_url}/v1/chat/completions", json=payload, headers=headers
            )
            if resp.status_code == 503:
                raise HTTPException(status_code=503, detail="Polter is busy. Please try again later.")
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Polter at {base_url}")


async def api_Polter_health(_auth: None = Depends(_verify_token)):
    """Proxy: Polter health check (no Polter auth required)."""
    import os
    import httpx
    base_url = os.environ.get("Polter_URL", "http://localhost:8000").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/health")
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Polter at {base_url}")


async def api_Polter_ready(_auth: None = Depends(_verify_token)):
    """Proxy: Polter readiness check."""
    import os
    import httpx
    base_url = os.environ.get("Polter_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Polter_API_KEY", "")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/ready", headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Polter at {base_url}")


async def api_Polter_models(_auth: None = Depends(_verify_token)):
    """Proxy: List available models from Polter."""
    import os
    import httpx
    base_url = os.environ.get("Polter_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Polter_API_KEY", "")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/v1/models", headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Polter at {base_url}")


async def api_Polter_submit_task(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Proxy: Submit a task via Polter's chat endpoint and return the task ID for polling."""
    import os
    import httpx
    base_url = os.environ.get("Polter_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Polter_API_KEY", "")
    messages = body.get("messages")
    if not messages:
        raise HTTPException(status_code=400, detail="messages are required")
    payload = {"messages": messages, "stream": False}
    payload.update({k: v for k, v in body.items() if k != "messages"})
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=1800.0) as client:
            resp = await client.post(
                f"{base_url}/v1/chat/completions", json=payload, headers=headers
            )
            if resp.status_code == 503:
                raise HTTPException(status_code=503, detail="Polter is busy. Please try again later.")
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Polter at {base_url}")


async def api_Polter_task_output(task_id: str, _auth: None = Depends(_verify_token)):
    """Proxy: Get task output by task_id from Polter (convenience wrapper)."""
    import os
    import httpx
    base_url = os.environ.get("Polter_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Polter_API_KEY", "")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/api/v1/tasks/{task_id}", headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            data = resp.json()
            # Return just the output fields for convenience
            return {
                "task_id": data.get("task_id"),
                "status": data.get("status"),
                "output": data.get("output", ""),
                "changed_files": data.get("changed_files", []),
                "diff_summary": data.get("diff_summary", ""),
            }
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Polter at {base_url}")


# ─── Unified Dashboard ──────────────────────────────────────────────────────



def register(app):
    """Register Polter routes with the FastAPI app."""
    app.get("/api/Polter/tasks")(api_Polter_tasks)
    app.get("/api/Polter/workers")(api_Polter_workers)
    app.get("/api/Polter/queue")(api_Polter_queue)
    app.get("/api/Polter/projects")(api_Polter_projects)
    app.post("/api/Polter/projects")(api_Polter_create_project)
    app.get("/api/Polter/tasks/{task_id}")(api_Polter_task_detail)
    app.get("/api/Polter/sessions")(api_Polter_sessions)
    app.get("/api/Polter/workers/{worker_id}")(api_Polter_worker_detail)
    app.post("/api/Polter/chat")(api_Polter_chat)
    app.get("/api/Polter/health")(api_Polter_health)
    app.get("/api/Polter/ready")(api_Polter_ready)
    app.get("/api/Polter/models")(api_Polter_models)
    app.post("/api/Polter/tasks")(api_Polter_submit_task)
    app.get("/api/Polter/tasks/{task_id}/output")(api_Polter_task_output)
