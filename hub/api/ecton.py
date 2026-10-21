"""Route module: Ecton."""

from fastapi import Depends, HTTPException
from hub.api.core import _verify_token
from typing import Any, Dict, List, Optional
import httpx
import json
import time


async def api_Ecton_tasks(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    _auth: None = Depends(_verify_token),
):
    """Proxy: List tasks from Ecton."""
    import os
    import httpx
    base_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Ecton_API_KEY", "")
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
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ecton at {base_url}")


async def api_Ecton_workers(_auth: None = Depends(_verify_token)):
    """Proxy: List active workers from Ecton."""
    import os
    import httpx
    base_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Ecton_API_KEY", "")
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
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ecton at {base_url}")


async def api_Ecton_queue(_auth: None = Depends(_verify_token)):
    """Proxy: Get queue status from Ecton."""
    import os
    import httpx
    base_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Ecton_API_KEY", "")
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
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ecton at {base_url}")


async def api_Ecton_projects(_auth: None = Depends(_verify_token)):
    """Proxy: List registered projects from Ecton."""
    import os
    import httpx
    base_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Ecton_API_KEY", "")
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
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ecton at {base_url}")


async def api_Ecton_create_project(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Proxy: Register a new project in Ecton."""
    import os
    import httpx
    base_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Ecton_API_KEY", "")
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
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ecton at {base_url}")


async def api_Ecton_task_detail(task_id: str, _auth: None = Depends(_verify_token)):
    """Proxy: Get a specific task detail from Ecton."""
    import os
    import httpx
    base_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Ecton_API_KEY", "")
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
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ecton at {base_url}")


async def api_Ecton_sessions(
    task_id: Optional[str] = None,
    limit: int = 50,
    _auth: None = Depends(_verify_token),
):
    """Proxy: List sessions from Ecton."""
    import os
    import httpx
    base_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Ecton_API_KEY", "")
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
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ecton at {base_url}")


async def api_Ecton_worker_detail(worker_id: str, _auth: None = Depends(_verify_token)):
    """Proxy: Get a specific worker detail from Ecton."""
    import os
    import httpx
    base_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Ecton_API_KEY", "")
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
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ecton at {base_url}")


async def api_Ecton_chat(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Proxy: Execute a task via Ecton's OpenAI-compatible chat endpoint."""
    import os
    import httpx
    base_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Ecton_API_KEY", "")
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
                raise HTTPException(status_code=503, detail="Ecton is busy. Please try again later.")
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ecton at {base_url}")


async def api_Ecton_health(_auth: None = Depends(_verify_token)):
    """Proxy: Ecton health check (no Ecton auth required)."""
    import os
    import httpx
    base_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/health")
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ecton at {base_url}")


async def api_Ecton_ready(_auth: None = Depends(_verify_token)):
    """Proxy: Ecton readiness check."""
    import os
    import httpx
    base_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Ecton_API_KEY", "")
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
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ecton at {base_url}")


async def api_Ecton_models(_auth: None = Depends(_verify_token)):
    """Proxy: List available models from Ecton."""
    import os
    import httpx
    base_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Ecton_API_KEY", "")
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
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ecton at {base_url}")


async def api_Ecton_submit_task(body: Dict[str, Any], _auth: None = Depends(_verify_token)):
    """Proxy: Submit a task via Ecton's chat endpoint and return the task ID for polling."""
    import os
    import httpx
    base_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Ecton_API_KEY", "")
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
                raise HTTPException(status_code=503, detail="Ecton is busy. Please try again later.")
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ecton at {base_url}")


async def api_Ecton_task_output(task_id: str, _auth: None = Depends(_verify_token)):
    """Proxy: Get task output by task_id from Ecton (convenience wrapper)."""
    import os
    import httpx
    base_url = os.environ.get("Ecton_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("Ecton_API_KEY", "")
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
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ecton at {base_url}")


# ─── Unified Dashboard ──────────────────────────────────────────────────────



def register(app):
    """Register Ecton routes with the FastAPI app."""
    app.get("/api/Ecton/tasks")(api_Ecton_tasks)
    app.get("/api/Ecton/workers")(api_Ecton_workers)
    app.get("/api/Ecton/queue")(api_Ecton_queue)
    app.get("/api/Ecton/projects")(api_Ecton_projects)
    app.post("/api/Ecton/projects")(api_Ecton_create_project)
    app.get("/api/Ecton/tasks/{task_id}")(api_Ecton_task_detail)
    app.get("/api/Ecton/sessions")(api_Ecton_sessions)
    app.get("/api/Ecton/workers/{worker_id}")(api_Ecton_worker_detail)
    app.post("/api/Ecton/chat")(api_Ecton_chat)
    app.get("/api/Ecton/health")(api_Ecton_health)
    app.get("/api/Ecton/ready")(api_Ecton_ready)
    app.get("/api/Ecton/models")(api_Ecton_models)
    app.post("/api/Ecton/tasks")(api_Ecton_submit_task)
    app.get("/api/Ecton/tasks/{task_id}/output")(api_Ecton_task_output)
