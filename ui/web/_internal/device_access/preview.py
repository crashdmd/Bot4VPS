"""Local, explicit opt-in for the internal device access preview."""
from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit

PREVIEW_ENV = "BOT4VPS_MOBILE_API_PREVIEW"
MANAGEMENT_PREFIX = "/api/settings/mobile-access"


def preview_enabled() -> bool:
    return os.environ.get(PREVIEW_ENV) == "1"


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

    Default management origin is a private numeric address / localhost. A LAN
    DNS name needs an explicit origin in the service environment. This also
    prevents a browser on an unrelated site using DNS rebinding to enroll keys.
    """
    if request.scope.get("state", {}).get("mobile_device_id") or request.headers.get("x-bot4vps-mobile-session"):
        return False
    if not request.client or not _private_address(request.client.host):
        return False
    origin = f"{request.url.scheme}://{request.url.netloc}"
    allowed = os.environ.get("BOT4VPS_MOBILE_API_WEB_ORIGIN", "").rstrip("/")
    if allowed:
        return origin == allowed
    host = urlsplit(origin).hostname or ""
    return host == "localhost" or _private_address(host)
