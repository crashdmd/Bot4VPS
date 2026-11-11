"""Device pairing for the separate mobile API, independent of Web login.

Only public P-256 keys are persisted. Private keys stay in Android Keystore;
one-use challenges and short-lived access tokens live in this process.
"""
from __future__ import annotations

import argparse
import base64
from collections import deque
from dataclasses import dataclass
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


@dataclass(frozen=True)
class MobileSession:
    device_id: str
    expires: float


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


def masterkey_message(device_id: str, challenge_id: str, nonce: str) -> bytes:
    return f"bot4vps-masterkey-view-v1\n{device_id}\n{challenge_id}\n{nonce}".encode("ascii")


def masterkey_enrollment_message(device_id: str, challenge_id: str, nonce: str, public_key: str, device_operation_public_key: str) -> bytes:
    return f"bot4vps-masterkey-enroll-v1\n{device_id}\n{challenge_id}\n{nonce}\n{public_key}\n{device_operation_public_key}".encode("ascii")


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
        self._masterkey_challenges: dict = {}
        self._masterkey_enrollments: dict = {}

    def masterkey_public_key(self, device_id: str) -> str | None:
        row = next((r for r in self.store.read() if r.get("kind") == "device" and r.get("id") == device_id), None)
        if row is None:
            raise AccessDenied()
        return row.get("masterkey_public_key")

    def masterkey_device_public_key(self, device_id: str) -> str | None:
        row = next((r for r in self.store.read() if r.get("kind") == "device" and r.get("id") == device_id), None)
        if row is None:
            raise AccessDenied()
        return row.get("masterkey_device_public_key")

    def enroll_masterkey(self, device_id: str, public_key: str) -> None:
        # Called only after server-side owner password + second factor.
        key = _public_key(public_key)
        canonical = base64.b64encode(key.public_bytes(serialization.Encoding.DER,
                                  serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        def enroll(rows):
            row = next((r for r in rows if r.get("kind") == "device" and r.get("id") == device_id), None)
            if row is None or canonical == row.get("public_key"):
                raise AccessDenied()
            row["masterkey_public_key"] = canonical
            return rows
        with self._lock:
            self.store.mutate(enroll)
            self._masterkey_challenges = {k: v for k, v in self._masterkey_challenges.items() if v["device_id"] != device_id}

    def masterkey_enrollment_challenge(self, device_id: str, public_key: str, device_operation_public_key: str) -> dict:
        self.rate_limit("masterkey-enroll:" + device_id)
        key = _public_key(public_key)
        canonical = base64.b64encode(key.public_bytes(serialization.Encoding.DER,
                                    serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        native = _public_key(device_operation_public_key)
        native_canonical = base64.b64encode(native.public_bytes(serialization.Encoding.DER,
                                           serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        with self._lock:
            row = next((r for r in self.store.read() if r.get("kind") == "device" and r.get("id") == device_id), None)
            if row is None or canonical == row.get("public_key") or native_canonical in (canonical, row.get("public_key")):
                raise AccessDenied()
            if row.get("masterkey_public_key") not in (None, canonical):
                raise AccessDenied(409, "Ключ защиты телефона изменился. Перепривяжите телефон для настройки защищённого просмотра.")
            if row.get("masterkey_device_public_key") not in (None, native_canonical):
                raise AccessDenied(409, "Ключ Keystore изменился. Перепривяжите телефон.")
            now = self.clock()
            self._masterkey_enrollments = {k: v for k, v in self._masterkey_enrollments.items()
                                           if v["expires"] > now and v["device_id"] != device_id}
            if len(self._masterkey_enrollments) >= 64:
                raise AccessDenied(429, "Слишком много попыток настройки")
            challenge_id, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
            self._masterkey_enrollments[challenge_id] = {
                "device_id": device_id, "nonce": nonce, "public_key": canonical,
                "device_operation_public_key": native_canonical,
                "device_public_key": row["public_key"], "expires": now + CHALLENGE_TTL}
        return {"ok": True, "device_id": device_id, "challenge_id": challenge_id,
                "nonce": nonce, "public_key": canonical, "device_operation_public_key": native_canonical, "expires_in": CHALLENGE_TTL}

    def confirm_masterkey_enrollment(self, device_id: str, challenge_id: str,
                                    device_signature: str, operation_signature: str, keystore_signature: str) -> None:
        with self._lock:
            pending = self._masterkey_enrollments.pop(challenge_id, None)
            row = next((r for r in self.store.read() if r.get("kind") == "device" and r.get("id") == device_id), None)
            if (not pending or not row or pending["device_id"] != device_id
                    or pending["expires"] <= self.clock() or pending["device_public_key"] != row.get("public_key")
                    or row.get("masterkey_public_key") not in (None, pending["public_key"])
                    or row.get("masterkey_device_public_key") not in (None, pending["device_operation_public_key"])):
                raise AccessDenied()
            message = masterkey_enrollment_message(device_id, challenge_id, pending["nonce"], pending["public_key"], pending["device_operation_public_key"])
            try:
                _public_key(row["public_key"]).verify(_decode(device_signature, 256), message, ec.ECDSA(hashes.SHA256()))
                _public_key(pending["public_key"]).verify(_decode(operation_signature, 256), message, ec.ECDSA(hashes.SHA256()))
                _public_key(pending["device_operation_public_key"]).verify(_decode(keystore_signature, 256), message, ec.ECDSA(hashes.SHA256()))
            except (InvalidSignature, ValueError, KeyError) as exc:
                raise AccessDenied() from exc
            # Pairing already grants this device access. A session token or UI
            # flag alone cannot enroll: both independent private keys must sign.
            # Replacing an existing operation key requires a new Web pairing or
            # the legacy owner-factor flow; this path never silently replaces it.
            def enroll(rows):
                current = next((r for r in rows if r.get("kind") == "device" and r.get("id") == device_id), None)
                if (current is None or current.get("public_key") != pending["device_public_key"]
                        or current.get("masterkey_public_key") not in (None, pending["public_key"])
                        or current.get("masterkey_device_public_key") not in (None, pending["device_operation_public_key"])):
                    raise AccessDenied()
                current["masterkey_public_key"] = pending["public_key"]
                current["masterkey_device_public_key"] = pending["device_operation_public_key"]
                return rows
            self.store.mutate(enroll)
            self._masterkey_challenges = {k: v for k, v in self._masterkey_challenges.items() if v["device_id"] != device_id}

    def masterkey_challenge(self, device_id: str) -> dict:
        self.rate_limit("masterkey:" + device_id)
        with self._lock:
            key = self.masterkey_public_key(device_id)
            if not key:
                raise AccessDenied(409, "Подтвердите владельца для настройки защищённого просмотра")
            now = self.clock()
            self._masterkey_challenges = {k: v for k, v in self._masterkey_challenges.items()
                                          if v["expires"] > now and v["device_id"] != device_id}
            if len(self._masterkey_challenges) >= 64:
                raise AccessDenied(429, "Слишком много попыток просмотра")
            challenge_id, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
            self._masterkey_challenges[challenge_id] = {"device_id": device_id, "nonce": nonce,
                                                      "public_key": key, "device_operation_public_key": self.masterkey_device_public_key(device_id),
                                                      "expires": now + CHALLENGE_TTL}
        return {"ok": True, "challenge_id": challenge_id, "nonce": nonce, "expires_in": CHALLENGE_TTL,
                "device_id": device_id}

    def confirm_masterkey(self, device_id: str, challenge_id: str, signature: str, keystore_signature: str = "") -> None:
        with self._lock:
            challenge = self._masterkey_challenges.pop(challenge_id, None)
            if (not challenge or challenge["device_id"] != device_id or challenge["expires"] <= self.clock()
                    or self.masterkey_public_key(device_id) != challenge["public_key"]
                    or self.masterkey_device_public_key(device_id) != challenge.get("device_operation_public_key")):
                raise AccessDenied()
            try:
                _public_key(challenge["public_key"]).verify(_decode(signature, 256),
                    masterkey_message(device_id, challenge_id, challenge["nonce"]), ec.ECDSA(hashes.SHA256()))
                if challenge.get("device_operation_public_key"):
                    _public_key(challenge["device_operation_public_key"]).verify(_decode(keystore_signature, 256),
                        masterkey_message(device_id, challenge_id, challenge["nonce"]), ec.ECDSA(hashes.SHA256()))
            except (InvalidSignature, ValueError, KeyError) as exc:
                raise AccessDenied() from exc

    def issue_pairing_code(self, name: str, *, status_token: str | None = None) -> str:
        code = secrets.token_urlsafe(32)
        now = self.clock()
        def create(rows):
            rows = [r for r in rows if r.get("kind") != "invite" or r.get("expires", 0) > now]
            if sum(r.get("kind") == "invite" for r in rows) >= 16:
                raise AccessDenied(409, "Слишком много активных кодов привязки")
            invite = {"kind": "invite", "hash": hashlib.sha256(code.encode()).hexdigest(),
                      "name": name.strip()[:80] or "Телефон", "expires": now + PAIR_TTL}
            if status_token:
                invite["status_hash"] = hashlib.sha256(status_token.encode()).hexdigest()
            return rows + [invite]
        self.store.mutate(create)
        return code

    def pair(self, code: str, public_key: str, masterkey_device_public_key: str | None = None) -> dict:
        if not isinstance(code, str) or not 40 <= len(code) <= 64:
            raise AccessDenied(403, "Код привязки недействителен или истёк")
        key = _public_key(public_key)
        public_key = base64.b64encode(key.public_bytes(serialization.Encoding.DER,
                                     serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        if masterkey_device_public_key is not None:
            native = _public_key(masterkey_device_public_key)
            masterkey_device_public_key = base64.b64encode(native.public_bytes(serialization.Encoding.DER,
                                                         serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
            if masterkey_device_public_key == public_key:
                raise AccessDenied(400, "Для мастер-ключа нужен отдельный ключ телефона")
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        now = self.clock()
        device = {"kind": "device", "id": str(uuid.uuid4()), "public_key": public_key, "created": now}
        if masterkey_device_public_key is not None:
            device["masterkey_device_public_key"] = masterkey_device_public_key
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
            if invite.get("status_hash"):
                device.update(status_hash=invite["status_hash"], status_expires=invite["expires"])
            return [r for r in rows if r is not invite and (r.get("kind") != "invite" or r.get("expires", 0) > now)] + [device]
        self.store.mutate(enroll)
        return {"device_id": device["id"], "name": device["name"]}

    def pairing_status(self, token: str) -> dict:
        # A separate read-only token cannot enroll a phone or recover the code.
        if not isinstance(token, str) or not 40 <= len(token) <= 64:
            raise AccessDenied(400, "Некорректный запрос состояния привязки")
        digest = hashlib.sha256(token.encode()).hexdigest()
        for row in self.store.read():
            if secrets.compare_digest(str(row.get("status_hash", "")), digest):
                expires = row.get("status_expires", row.get("expires", 0))
                if expires > self.clock():
                    if row.get("kind") == "device":
                        return {"state": "paired", "name": row.get("name", "Телефон")}
                    return {"state": "pending"}
        return {"state": "expired"}

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

    def session_details(self, token: str | None) -> MobileSession | None:
        if not isinstance(token, str) or not 40 <= len(token) <= 64:
            return None
        with self._lock:
            entry = self._sessions.get(hashlib.sha256(token.encode()).hexdigest())
            entry = dict(entry) if entry else None
        if not entry or entry["expires"] <= self.clock() or not self.device_exists(entry["device_id"]):
            return None
        return MobileSession(entry["device_id"], entry["expires"])

    def authorize(self, token: str | None) -> str | None:
        session = self.session_details(token)
        return session.device_id if session else None


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
