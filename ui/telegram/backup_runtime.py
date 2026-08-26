"""Small read-only Web UI availability probe for Telegram Backup."""
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request

from core.web_port import current_port_from_unit

WEB_INSTALL_URL = "https://github.com/crashdmd/Bot4VPS"
_HEALTH_TIMEOUT = 2.5


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _probe_health(port: int | None) -> bool:
    """Return true only for a bounded, valid loopback health response."""
    if not isinstance(port, int) or not (1 <= port <= 65535):
        return False
    url = f"http://127.0.0.1:{port}/api/upd/health"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "bot4vps-telegram-backup"},
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=_HEALTH_TIMEOUT) as response:
            if int(getattr(response, "status", 0) or 0) != 200:
                return False
            raw = response.read(4096)
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, UnicodeError, urllib.error.URLError):
        return False
    return isinstance(payload, dict) and payload.get("ok") is True


async def web_ui_available() -> bool:
    """Check the already-running Web UI without starting or reconfiguring it."""
    port = await asyncio.to_thread(current_port_from_unit)
    return await asyncio.to_thread(_probe_health, port)


__all__ = ["WEB_INSTALL_URL", "web_ui_available"]
