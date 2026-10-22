"""Server-Sent Events (SSE) streaming for mission execution logs.

Provides real-time log streaming to the Slammer dashboard so users can
watch mission progress as it happens.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from hub.mission import storage as mission_storage

logger = logging.getLogger(__name__)

# Poll interval for SSE updates (seconds)
SSE_POLL_INTERVAL = 1.0


async def stream_mission_logs(
    mission_id: str,
    since: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Stream mission execution logs via Server-Sent Events.

    Yields SSE-formatted strings with new log entries as they appear.
    The stream continues until the client disconnects or the mission
    reaches a terminal state.

    Args:
        mission_id: The mission to stream logs for.
        since: ISO timestamp to start streaming from. If None, starts from now.

    Yields:
        SSE-formatted strings like "data: {...}\n\n"
    """
    if since is None:
        since = datetime.now(timezone.utc).isoformat()

    # Send initial connection event
    yield f"event: connected\ndata: {json.dumps({'mission_id': mission_id})}\n\n"

    # Check if mission exists
    mission = mission_storage.get_mission(mission_id)
    if mission is None:
        yield f"event: error\ndata: {json.dumps({'error': 'Mission not found'})}\n\n"
        return

    # Send current mission status
    yield f"event: status\ndata: {json.dumps({'mission_id': mission_id, 'status': mission.status})}\n\n"

    terminal_states = {"completed", "failed", "cancelled"}

    try:
        while True:
            # Check if mission is in a terminal state
            mission = mission_storage.get_mission(mission_id)
            if mission and mission.status in terminal_states:
                # Send final status and close
                yield f"event: complete\ndata: {json.dumps({'mission_id': mission_id, 'status': mission.status})}\n\n"
                break

            # Fetch new logs since last check
            logs = mission_storage.get_mission_logs_since(mission_id, since, limit=50)

            for log in logs:
                yield f"event: log\ndata: {json.dumps(log)}\n\n"
                since = log["timestamp"]

            if not logs:
                # No new logs, wait before polling again
                await asyncio.sleep(SSE_POLL_INTERVAL)

    except asyncio.CancelledError:
        logger.info("SSE stream cancelled for mission %s", mission_id)
    except Exception as e:
        logger.error("SSE stream error for mission %s: %s", mission_id, e)
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"


def format_sse(data: dict, event: str = "message") -> str:
    """Format a dictionary as an SSE message.

    Args:
        data: Dictionary to serialize as JSON.
        event: Event type name.

    Returns:
        SSE-formatted string.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def get_log_count(mission_id: str) -> int:
    """Get the total number of log entries for a mission."""
    logs = mission_storage.get_mission_logs(mission_id, limit=1)
    # We need a proper count; for now approximate via retrieval
    all_logs = mission_storage.get_mission_logs(mission_id, limit=10000)
    return len(all_logs)
