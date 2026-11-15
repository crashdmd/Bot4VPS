"""One-use signed management requests available only to the primary phone."""
from __future__ import annotations

import hashlib
import secrets

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from .access import PAIR_TTL, AccessDenied, _decode, _public_key, pairing_invitation
from .primary import require
from ..auth_flows import AuthFlows, decision_message, audit_flow, ACTIVE


def challenge(flows: AuthFlows, device_id: str, operation: str, *, target_id="", name="Телефон"):
    if operation not in ("pair", "revoke"):
        raise HTTPException(400, "Неизвестная операция с телефоном")
    result = {}
    def create(rows):
        nonlocal result
        rows = flows._prune(rows)
        require(rows, device_id)
        if operation == "revoke":
            if target_id == device_id:
                raise HTTPException(400, "Для этого телефона используйте «Отключить на этом телефоне»")
            target = next((r for r in rows if r.get("kind") == "device" and r["id"] == target_id), None)
            if target is None:
                raise HTTPException(404, "Телефон уже отвязан")
            name_value = target.get("name", "Телефон")
        else:
            name_value = name.strip()[:80] or "Телефон"
        # One pending management challenge per actor; superseding cannot leave
        # an older signed request usable for a different target or operation.
        rows = [r for r in rows if not (r.get("purpose") == "phone_management" and r.get("device_id") == device_id)]
        row = flows._new("auth", "phone:" + device_id, ttl=120, purpose="phone_management",
                         device_id=device_id, operation=operation, target_device_id=target_id, name=name_value)
        result = {k: row[k] for k in ("id", "nonce", "operation", "target_device_id", "name", "expires")}
        return rows + [row]
    flows._mutate(create)
    return result


def execute(flows: AuthFlows, device_id: str, flow_id: str, signature: str):
    result = {}
    def apply(rows):
        nonlocal result
        require(rows, device_id)
        row = flows._find(rows, flow_id, "auth")
        flows._live(row)
        if row.get("purpose") != "phone_management" or row.get("device_id") != device_id or row.get("state") != "pending":
            raise HTTPException(409, "Запрос уже завершён или принадлежит другому телефону")
        device = next(r for r in rows if r.get("kind") == "device" and r["id"] == device_id)
        try:
            _public_key(device["public_key"]).verify(_decode(signature, 256),
                decision_message(flow_id, row["nonce"], device_id, "approve"), ec.ECDSA(hashes.SHA256()))
        except (InvalidSignature, AccessDenied, ValueError, KeyError):
            raise HTTPException(403, "Подпись телефона недействительна") from None
        row["state"] = "approved"
        if row["operation"] == "pair":
            from core.config import get_web_config
            from .identity import configured_identity
            cfg = get_web_config().get("mobile_api") or {}
            if not cfg.get("enabled") or not cfg.get("public_url"):
                raise HTTPException(409, "Восстановите работу Mobile API")
            rows = [r for r in rows if r.get("kind") != "invite" or r.get("expires", 0) > flows.clock()]
            if sum(r.get("kind") == "invite" for r in rows) >= 16:
                raise HTTPException(409, "Слишком много активных кодов привязки")
            code, status_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            rows.append({"kind": "invite", "hash": hashlib.sha256(code.encode()).hexdigest(), "name": row["name"],
                         "expires": flows.clock() + PAIR_TTL, "status_hash": hashlib.sha256(status_token.encode()).hexdigest()})
            result = {"ok": True, "code": pairing_invitation(cfg["public_url"], code, configured_identity(cfg)["server_pin"]),
                      "expires": flows.clock() + PAIR_TTL, "status_token": status_token}
            audit_flow("mobile_api.pair_code_create", row, via="primary_phone")
        else:
            target_id = row["target_device_id"]
            if target_id == device_id or not any(r.get("kind") == "device" and r["id"] == target_id for r in rows):
                raise HTTPException(404, "Телефон уже отвязан")
            for previous in rows:
                if previous.get("kind") == "unlink" and previous.get("device_id") == target_id and previous["state"] in ACTIVE:
                    flows._cancel(rows, previous, "primary_phone")
            unlink = flows._new("unlink", "phone:" + device_id, device_id=target_id, method="mobile")
            rows.append(unlink)
            audit_flow("mobile_api.unlink_start", unlink, result="started", via="primary_phone")
            rows = flows._finish(rows, unlink, "primary_phone")
            result = {"ok": True, "device_id": target_id}
        return rows
    flows._mutate(apply)
    return result
