"""Shared existing Telegram recovery OTP: 10 minutes, five attempts.

Delivery stays in app._send_recovery_message. Each caller stores and consumes
its own pending record, bound to its operation, without cross-purpose reuse.
"""
import hmac
import secrets
import time


async def send_telegram_code(title, instruction, *, clock=time.monotonic):
    from .app import _send_recovery_message
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = clock()
    await _send_recovery_message(
        f"🔐 <b>{title}</b>\n\nКод подтверждения: <code>{code}</code>\n"
        f"Действует 10 минут.\n\n{instruction}"
    )
    return {"code": code, "expires_at": now + 600, "attempts": 0}


def check_telegram_code(pending, code, *, now):
    return bool(pending and pending.get("expires_at", 0) > now and pending.get("attempts", 5) < 5
                and isinstance(code, str) and isinstance(pending.get("code"), str)
                and hmac.compare_digest(code.strip(), pending["code"]))
