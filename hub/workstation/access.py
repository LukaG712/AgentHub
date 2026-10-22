"""Human access to workstations: terminal and desktop.

Provides live terminal (TTY) access via WebSocket and desktop (VNC/noVNC)
access for running workstation containers. Supports both direct and proxy-based
access patterns.
"""

import logging
import os
import secrets
from typing import Optional

from hub.workstation.models import (
    Workstation,
    WorkstationAccess,
    AccessType,
)
from hub.workstation import driver

logger = logging.getLogger(__name__)

# Configuration
WORKSTATION_GATEWAY_URL = os.environ.get("WORKSTATION_GATEWAY_URL", "http://localhost:8080")
VNC_PORT = 5900
NOVNC_PORT = 6080
TERMINAL_WS_PATH = "/ws/terminal"


def setup_access(ws: Workstation) -> WorkstationAccess:
    """Setup access for a running workstation.

    Configures terminal and/or desktop access based on the workstation's
    configuration. Returns the access information.

    Args:
        ws: The running workstation.

    Returns:
        WorkstationAccess with URLs and credentials.
    """
    access = WorkstationAccess()

    # Setup terminal access
    if ws.config.enable_terminal:
        terminal_url = setup_terminal(ws)
        if terminal_url:
            access.terminal_url = terminal_url
            access.access_type = AccessType.TTY.value

    # Setup desktop access
    if ws.config.enable_desktop:
        desktop_url, vnc_password = setup_desktop(ws, ws.config.desktop_type)
        if desktop_url:
            access.desktop_url = desktop_url
            access.vnc_password = vnc_password
            access.access_type = AccessType.NO_VNC.value if ws.config.desktop_type == "novnc" else AccessType.VNC.value

    # Get exposed ports
    if ws.container_id:
        info = driver.inspect_container(ws.container_id)
        if info:
            access.exposed_ports = info.get("ports", [])

    return access


def setup_terminal(ws: Workstation) -> Optional[str]:
    """Setup terminal (TTY) access for a workstation.

    The terminal is accessed via a WebSocket endpoint that proxies
    stdin/stdout/stderr to the container's TTY.

    Args:
        ws: The running workstation.

    Returns:
        WebSocket URL for terminal access, or None on failure.
    """
    # The terminal WebSocket endpoint
    # Format: ws://<gateway>/ws/terminal/<workstation_id>
    gateway = WORKSTATION_GATEWAY_URL.replace("http://", "ws://").replace("https://", "wss://")
    terminal_url = f"{gateway}{TERMINAL_WS_PATH}/{ws.id}"

    logger.info(f"Terminal access configured for workstation '{ws.id}': {terminal_url}")
    return terminal_url


def setup_desktop(ws: Workstation, desktop_type: str = "novnc") -> tuple[Optional[str], Optional[str]]:
    """Setup desktop (VNC/noVNC) access for a workstation.

    Installs a VNC server inside the container and optionally a noVNC web client.

    Args:
        ws: The running workstation.
        desktop_type: "vnc" for raw VNC, "novnc" for browser-based access.

    Returns:
        Tuple of (desktop_url, vnc_password) or (None, None) on failure.
    """
    if not ws.container_id:
        logger.error(f"Cannot setup desktop: no container ID for workstation '{ws.id}'")
        return None, None

    # Generate a random VNC password
    vnc_password = secrets.token_hex(4)  # 8-character hex password

    try:
        # Install and configure VNC server in the container
        install_commands = []

        # Detect package manager and install VNC
        install_commands.append("""
            # Detect OS and install VNC
            if command -v apt-get &> /dev/null; then
                apt-get update && apt-get install -y tightvncserver x11-utils
            elif command -v yum &> /dev/null; then
                yum install -y tigervnc-server
            elif command -v apk &> /dev/null; then
                apk add --no-cache tightvnc x11-utils
            else
                echo "Unsupported package manager" >&2
                exit 1
            fi
        """).strip()

        # Configure VNC
        install_commands.append(f"""
            # Set VNC password
            echo '{vnc_password}' | vncpasswd -f > ~/.vnc/passwd
            chmod 600 ~/.vnc/passwd

            # Start VNC server
            vncserver :1 -geometry 1280x720 -depth 24 -localhost no
        """).strip()

        # Install noVNC if requested
        if desktop_type == "novnc":
            install_commands.append("""
                # Install noVNC
                if [ ! -d /usr/share/novnc ]; then
                    git clone --depth 1 https://github.com/novnc/noVNC.git /usr/share/novnc
                    git clone --depth 1 https://github.com/novnc/websockify.git /usr/share/novnc/utils/websockify
                fi

                # Start noVNC websockify proxy
                python3 /usr/share/novnc/utils/websockify/run --vnc localhost:5901 6080 &
            """).strip()

        # Execute installation
        for cmd in install_commands:
            result = driver.exec_in_container(ws.container_id, cmd)
            if result and result.get("exit_code", 0) != 0:
                logger.error(f"Failed to install desktop components: {result.get('stderr', '')}")
                return None, None

        # Determine the desktop URL
        if desktop_type == "novnc":
            host_port = driver.get_host_port(ws.container_id, NOVNC_PORT)
            if host_port:
                desktop_url = f"http://localhost:{host_port}/vnc"
            else:
                # Fall back to gateway URL
                desktop_url = f"{WORKSTATION_GATEWAY_URL}/desktop/{ws.id}"
        else:
            # Raw VNC — return the connection info
            host_port = driver.get_host_port(ws.container_id, VNC_PORT)
            if host_port:
                desktop_url = f"localhost:{host_port}"
            else:
                desktop_url = f"{WORKSTATION_GATEWAY_URL}/vnc/{ws.id}"

        logger.info(f"Desktop access configured for workstation '{ws.id}': {desktop_url}")
        return desktop_url, vnc_password

    except Exception as e:
        logger.error(f"Failed to setup desktop for workstation '{ws.id}': {e}")
        return None, None


def get_terminal_websocket_handler(workstation_id: str):
    """Get a WebSocket handler for terminal access.

    This returns a callable that can be used as a WebSocket endpoint handler.
    It proxies WebSocket messages to the container's TTY.

    Args:
        workstation_id: The workstation ID.

    Returns:
        A WebSocket handler function, or None if the workstation is not found.
    """
    from hub.workstation import storage
    ws = storage.get_workstation(workstation_id)
    if ws is None or not ws.container_id:
        return None

    def handler(websocket, path):
        """Handle a terminal WebSocket connection."""
        import asyncio

        async def forward_to_container():
            """Forward WebSocket messages to the container."""
            try:
                # Start an interactive shell in the container
                client = driver._get_docker()
                if client is None:
                    return

                exec_id = client.api.exec_create(
                    ws.container_id,
                    "/bin/sh",
                    tty=True,
                    stdin=True,
                    stdout=True,
                    stderr=True,
                )
                socket = client.api.exec_start(exec_id, socket=True, tty=True)

                # Forward input from WebSocket to container
                async for message in websocket:
                    if isinstance(message, str):
                        message = message.encode("utf-8")
                    socket.send(message)

                # Close the socket
                socket.close()
            except Exception as e:
                logger.error(f"Terminal WebSocket error for '{workstation_id}': {e}")

        return forward_to_container()

    return handler


def validate_access_token(workstation_id: str, token: str) -> bool:
    """Validate an access token for a workstation.

    In production, this would check against a stored token or JWT.
    For now, it validates against the Bearer token configured for Greenie.

    Args:
        workstation_id: The workstation ID.
        token: The access token.

    Returns:
        True if the token is valid.
    """
    # Get the API token from environment
    api_token = os.environ.get("EVERSHADE_GREENIE_API_TOKEN", "")
    if not api_token:
        # No token configured — allow access (development mode)
        return True

    # Constant-time comparison
    import hmac
    return hmac.compare_digest(token, api_token)


def get_access_info(workstation_id: str) -> Optional[dict]:
    """Get access information for a workstation.

    Returns a dict with terminal URL, desktop URL, and credentials.

    Args:
        workstation_id: The workstation ID.

    Returns:
        Access information dict or None if not found.
    """
    from hub.workstation import storage
    ws = storage.get_workstation(workstation_id)
    if ws is None:
        return None

    if ws.access is None:
        return {
            "terminal_url": None,
            "desktop_url": None,
            "access_type": None,
            "vnc_password": None,
            "exposed_ports": [],
        }

    # Return access info without the VNC password (security)
    info = ws.access.to_dict().copy()
    info["vnc_password"] = "***" if info.get("vnc_password") else None
    return info


def get_vnc_password(workstation_id: str) -> Optional[str]:
    """Get the VNC password for a workstation.

    This endpoint requires elevated privileges.

    Args:
        workstation_id: The workstation ID.

    Returns:
        The VNC password or None if not available.
    """
    from hub.workstation import storage
    ws = storage.get_workstation(workstation_id)
    if ws is None or ws.access is None:
        return None
    return ws.access.vnc_password
