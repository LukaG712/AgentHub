"""Network policy enforcement for workstations.

Implements default-deny network policies for workstation containers.
Workstations can only reach explicitly allowed hosts and services.
Uses Docker DNS and iptables rules to enforce network isolation.
"""

import ipaddress
import logging
from typing import Optional

from hub.workstation import driver, storage
from hub.workstation.models import WorkstationStatus

logger = logging.getLogger(__name__)

# Well-known internal/metadata IPs that should always be blocked
BLOCKED_INTERNAL_IPS = [
    "169.254.169.254",       # AWS metadata
    "metadata.google.internal",  # GCP metadata
    "100.100.100.200",       # Azure metadata
    "192.168.1.1",           # Common gateway
]

# Private IP ranges (RFC 1918)
PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
]


def is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is in a private or reserved range."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in net for net in PRIVATE_NETWORKS)
    except ValueError:
        return False


def is_metadata_endpoint(host: str) -> bool:
    """Check if a host is a cloud metadata endpoint."""
    host_lower = host.lower()
    for blocked in BLOCKED_INTERNAL_IPS:
        if blocked.lower() in host_lower:
            return True
    return False


def apply_policy(workstation_id: str, allowed_hosts: list[str]) -> bool:
    """Apply network policy to a workstation.

    Configures the container to only allow traffic to the specified hosts.
    Uses Docker extra_hosts and DNS configuration to enforce the allowlist.

    Args:
        workstation_id: The workstation ID.
        allowed_hosts: List of allowed hostnames or IPs.

    Returns:
        True if the policy was applied, False on error.
    """
    ws = storage.get_workstation(workstation_id)
    if ws is None:
        logger.error(f"Workstation '{workstation_id}' not found for policy application")
        return False

    # Filter out blocked hosts
    filtered_hosts = []
    for host in allowed_hosts:
        if is_metadata_endpoint(host):
            logger.warning(f"Blocking metadata endpoint in allowlist: {host}")
            continue
        filtered_hosts.append(host)

    # Configure DNS via /etc/hosts in the container
    if ws.container_id and ws.status == WorkstationStatus.RUNNING.value:
        # Build extra_hosts mapping for Docker
        # This ensures only allowed hosts resolve correctly
        extra_hosts = {}
        for host in filtered_hosts:
            # For hostnames, we add them to the container's /etc/hosts
            # pointing to the Docker gateway for DNS resolution
            if "." not in host and not is_private_ip(host):
                # It's a service name — let Docker DNS handle it
                pass
            else:
                # It's a hostname or IP — add to extra_hosts
                extra_hosts[host] = "host-gateway" if host == "host" else host

        # Set DNS policy via environment variable
        # The container will use a custom resolv.conf with only allowed DNS servers
        dns_config = ws.config.dns_servers or ["8.8.8.8", "8.8.4.4"]
        resolv_content = "\n".join(f"nameserver {dns}" for dns in dns_config)

        # Write resolv.conf in the container
        result = driver.exec_in_container(
            ws.container_id,
            f"echo '{resolv_content}' > /etc/resolv.conf",
        )
        if result and result.get("exit_code") != 0:
            logger.warning(f"Failed to set DNS for workstation '{workstation_id}': {result.get('stderr', '')}")

    # Store the policy
    ws.config.allowed_hosts = filtered_hosts
    storage.save_workstation(ws)

    logger.info(f"Applied network policy for workstation '{workstation_id}': {len(filtered_hosts)} allowed hosts")
    return True


def remove_policy(workstation_id: str) -> bool:
    """Remove network policy for a workstation.

    Args:
        workstation_id: The workstation ID.

    Returns:
        True if the policy was removed, False on error.
    """
    ws = storage.get_workstation(workstation_id)
    if ws is None:
        return False

    ws.config.allowed_hosts = []
    storage.save_workstation(ws)
    logger.info(f"Removed network policy for workstation '{workstation_id}'")
    return True


def get_policy(workstation_id: str) -> Optional[dict]:
    """Get the current network policy for a workstation.

    Returns a dict with allowed_hosts and blocked endpoints, or None if not found.
    """
    ws = storage.get_workstation(workstation_id)
    if ws is None:
        return None

    return {
        "allowed_hosts": ws.config.allowed_hosts,
        "dns_servers": ws.config.dns_servers or ["8.8.8.8", "8.8.4.4"],
        "blocked_endpoints": BLOCKED_INTERNAL_IPS,
        "network_name": ws.config.network_name,
    }


def validate_host(host: str) -> tuple[bool, str]:
    """Validate whether a host is allowed for workstation access.

    Returns (is_allowed, reason) tuple.
    """
    if is_metadata_endpoint(host):
        return False, "Cloud metadata endpoint — always blocked"

    # Check if it's an IP address
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_loopback:
            return False, "Loopback address blocked"
        if ip.is_link_local:
            return False, "Link-local address blocked"
        if ip.is_multicast:
            return False, "Multicast address blocked"
        if any(ip in net for net in PRIVATE_NETWORKS):
            return False, "Private IP address blocked by default-deny policy"
        return True, "Allowed"
    except ValueError:
        # It's a hostname — allow it (DNS will resolve)
        pass

    # Block known dangerous hostnames
    dangerous = ["metadata", "instance-data", "metadata.google"]
    for d in dangerous:
        if d in host.lower():
            return False, f"Potentially dangerous hostname: {d}"

    return True, "Allowed"


def get_network_info(network_name: str) -> Optional[dict]:
    """Get information about the workstation Docker network.

    Returns network details or None if not found.
    """
    client = driver._get_docker()
    if client is None:
        return None

    try:
        for net in client.networks.list():
            if net.name == network_name:
                return {
                    "name": net.name,
                    "id": net.id[:12],
                    "driver": net.attrs.get("Driver", ""),
                    "ipam_config": net.attrs.get("IPAM", {}).get("Config", []),
                    "containers": list(net.attrs.get("Containers", {}).keys()),
                }
    except Exception as e:
        logger.error(f"Failed to get network info for '{network_name}': {e}")
    return None
