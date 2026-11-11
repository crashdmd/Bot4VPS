"""Web origin guard for managing paired mobile devices."""
from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit

MANAGEMENT_PREFIX = "/api/settings/mobile-access"


def _private_address(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128", "fc00::/7")
        return any(ip in ipaddress.ip_network(network) for network in networks)
    except ValueError:
        return False


def private_web_request(request) -> bool:
    """Never trust X-Forwarded-For, a mobile session or an arbitrary DNS host.

    With Web auth enabled, the router's normal authenticated session grants
    access automatically for public IP/DNS too. Without Web auth, retain the
    private network/host restrictions to prevent DNS rebinding. A legacy
    configured origin adds a local DNS option; it never disables IP access.
    """
    if request.scope.get("state", {}).get("mobile_device_id") or request.headers.get("x-bot4vps-mobile-session"):
        return False
    if not request.client:
        return False
    from ...security import auth_enabled
    if auth_enabled():
        # private_management/require_auth still enforce the real Web session,
        # exact browser Origin and second factor before any management operation.
        return True
    if not _private_address(request.client.host):
        return False
    origin = f"{request.url.scheme}://{request.url.netloc}"
    host = urlsplit(origin).hostname or ""
    allowed = os.environ.get("BOT4VPS_MOBILE_API_WEB_ORIGIN", "").rstrip("/")
    return host == "localhost" or _private_address(host) or bool(allowed and origin == allowed)
