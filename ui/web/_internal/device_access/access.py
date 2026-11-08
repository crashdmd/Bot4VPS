"""Device pairing for the separate mobile API, independent of Web login.

Only public P-256 keys are persisted. Private keys stay in Android Keystore;
one-use challenges and short-lived access tokens live in this process.
"""
from __future__ import annotations

import argparse
import base64
from collections import deque
import hashlib
import json
import secrets
import threading
import time
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from core.json_store import JsonDocumentStore

PAIR_TTL = 600
CHALLENGE_TTL = 30
SESSION_TTL = 900
ACCESS_HEADER = b"x-bot4vps-mobile-session"


class AccessDenied(ValueError):
    def __init__(self, status: int = 403, message: str = "Телефон не привязан или доступ отозван"):
        self.status = status
        super().__init__(message)


def _decode(value: str, limit: int) -> bytes:
    if not isinstance(value, str) or len(value) > limit:
        raise AccessDenied()
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise AccessDenied() from exc


def _public_key(value: str):
    try:
        key = serialization.load_der_public_key(_decode(value, 1024))
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise AccessDenied()
        return key
    except (ValueError, TypeError) as exc:
        raise AccessDenied() from exc


def challenge_message(device_id: str, challenge_id: str, nonce: str) -> bytes:
    return f"bot4vps-mobile-v1\n{device_id}\n{challenge_id}\n{nonce}".encode("ascii")


def pairing_invitation(url: str, code: str, server_pin: str) -> str:
    data = {"version": 1, "url": url, "code": code, "server_pin": server_pin}
    return "b4vps:" + base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")


class MobileAccess:
    def __init__(self, path: Path = Path("data/mobile_devices.json"), *, clock=time.time):
        self.store = JsonDocumentStore(path, name="MOBILE ACCESS")
        self.clock = clock
        self._lock = threading.RLock()
        self._challenges: dict = {}
        self._sessions: dict = {}
        self._rates: dict = {}

    def issue_pairing_code(self, name: str) -> str:
        code = secrets.token_urlsafe(32)
        now = self.clock()
        def create(rows):
            rows = [r for r in rows if r.get("kind") != "invite" or r.get("expires", 0) > now]
            if sum(r.get("kind") == "invite" for r in rows) >= 16:
                raise AccessDenied(409, "Слишком много активных кодов привязки")
            return rows + [{"kind": "invite", "hash": hashlib.sha256(code.encode()).hexdigest(),
                            "name": name.strip()[:80] or "Телефон", "expires": now + PAIR_TTL}]
        self.store.mutate(create)
        return code

    def pair(self, code: str, public_key: str) -> dict:
        if not isinstance(code, str) or not 40 <= len(code) <= 64:
            raise AccessDenied(403, "Код привязки недействителен или истёк")
        _public_key(public_key)
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        now = self.clock()
        device = {"kind": "device", "id": str(uuid.uuid4()), "public_key": public_key, "created": now}
        def enroll(rows):
            # Strictly one use, including retries with the same phone key.
            # Consumption and enrollment share the atomic storage transaction.
            invite = next((r for r in rows if r.get("kind") == "invite" and
                           secrets.compare_digest(str(r.get("hash", "")), code_hash) and r.get("expires", 0) > now), None)
            if invite is None:
                raise AccessDenied(403, "Код привязки уже использован, недействителен или истёк. Создайте новый код в веб-панели.")
            if sum(r.get("kind") == "device" for r in rows) >= 32:
                raise AccessDenied(409, "Достигнут лимит привязанных телефонов")
            device["name"] = invite.get("name", "Телефон")
            return [r for r in rows if r is not invite and (r.get("kind") != "invite" or r.get("expires", 0) > now)] + [device]
        self.store.mutate(enroll)
        return {"device_id": device["id"], "name": device["name"]}

    def devices(self) -> list:
        return [{k: row[k] for k in ("id", "name", "created") if k in row}
                for row in self.store.read() if row.get("kind") == "device"]

    def device_exists(self, device_id: str) -> bool:
        return any(r.get("kind") == "device" and r.get("id") == device_id for r in self.store.read())

    def revoke(self, device_id: str) -> dict | None:
        removed = None
        def remove(rows):
            nonlocal removed
            removed = next((r for r in rows if r.get("kind") == "device" and r.get("id") == device_id), None)
            return [r for r in rows if r is not removed]
        self.store.mutate(remove)
        with self._lock:
            self._sessions = {k: v for k, v in self._sessions.items() if v["device_id"] != device_id}
        return {"id": removed["id"], "name": removed.get("name")} if removed else None

    def rate_limit(self, client: str) -> None:
        now = self.clock()
        with self._lock:
            self._rates = {k: v for k, v in self._rates.items() if v and v[-1] > now - 60}
            if client not in self._rates and len(self._rates) >= 1024:
                raise AccessDenied(429, "Слишком много попыток подключения")
            attempts = self._rates.setdefault(client, deque())
            while attempts and attempts[0] <= now - 60:
                attempts.popleft()
            if len(attempts) >= 30:
                raise AccessDenied(429, "Слишком много попыток подключения. Подождите минуту")
            attempts.append(now)

    def challenge(self, device_id: str) -> dict:
        try:
            if str(uuid.UUID(device_id)) != device_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError) as exc:
            raise AccessDenied() from exc
        with self._lock:
            now = self.clock()
            self._challenges = {k: v for k, v in self._challenges.items() if v["expires"] > now}
            if len(self._challenges) >= 1024:
                raise AccessDenied(429, "Слишком много попыток подключения")
            challenge_id, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
            self._challenges[challenge_id] = {"device_id": device_id, "nonce": nonce, "expires": now + CHALLENGE_TTL}
        return {"challenge_id": challenge_id, "nonce": nonce, "expires_in": CHALLENGE_TTL}

    def handshake(self, device_id: str, challenge_id: str, signature: str) -> dict:
        if not isinstance(challenge_id, str) or len(challenge_id) > 128:
            raise AccessDenied()
        with self._lock:
            challenge = self._challenges.pop(challenge_id, None)
        if not challenge or challenge["device_id"] != device_id or challenge["expires"] <= self.clock():
            raise AccessDenied()
        record = next((r for r in self.store.read() if r.get("kind") == "device" and r.get("id") == device_id), None)
        if not record:
            raise AccessDenied()
        try:
            _public_key(record["public_key"]).verify(_decode(signature, 256),
                challenge_message(device_id, challenge_id, challenge["nonce"]), ec.ECDSA(hashes.SHA256()))
        except (InvalidSignature, ValueError, KeyError) as exc:
            raise AccessDenied() from exc
        token = secrets.token_urlsafe(32)
        with self._lock:
            now = self.clock()
            self._sessions = {k: v for k, v in self._sessions.items() if v["expires"] > now and v["device_id"] != device_id}
            if len(self._sessions) >= 64:
                raise AccessDenied(429, "Слишком много подключений")
            self._sessions[hashlib.sha256(token.encode()).hexdigest()] = {"device_id": device_id, "expires": now + SESSION_TTL}
        return {"session": token, "expires_in": SESSION_TTL}

    def authorize(self, token: str | None) -> str | None:
        if not isinstance(token, str) or not 40 <= len(token) <= 64:
            return None
        with self._lock:
            entry = self._sessions.get(hashlib.sha256(token.encode()).hexdigest())
        if not entry or entry["expires"] <= self.clock() or not self.device_exists(entry["device_id"]):
            return None
        return entry["device_id"]


def main():
    parser = argparse.ArgumentParser(description="Привязка телефонов к отдельному API Bot4VPS")
    sub = parser.add_subparsers(dest="command", required=True)
    pair = sub.add_parser("pair", help="Создать одноразовый код на 10 минут")
    pair.add_argument("--name", default="Телефон")
    sub.add_parser("list", help="Показать привязанные телефоны")
    revoke = sub.add_parser("revoke", help="Отозвать доступ телефона")
    revoke.add_argument("device_id")
    args = parser.parse_args()
    access = MobileAccess()
    if args.command == "pair":
        from core.config import get_web_config
        from .identity import configured_identity
        config = get_web_config().get("mobile_api") or {}
        if not config.get("public_url"):
            parser.error("Сначала задайте адрес API в скрытом разделе настроек веб-панели")
        identity = configured_identity(config)
        print("Одноразовый код привязки (10 минут):")
        print(pairing_invitation(config["public_url"], access.issue_pairing_code(args.name), identity["server_pin"]))
    elif args.command == "list":
        for device in access.devices():
            print(f"{device['id']}  {device.get('name', 'Телефон')}")
    else:
        access.revoke(args.device_id)
        print("Доступ телефона отозван")


if __name__ == "__main__":
    main()
