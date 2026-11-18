"""Durable browser challenges and device unlink procedures.

Device records and unlink transitions share one atomic document. The same
file lock is used by MobileAccess, so a decision cannot race revocation.
Only temporary challenges are exposed to phones; browser capabilities and
TOTP/Telegram secrets never appear in the inbox or audit.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from pathlib import Path

from fastapi import HTTPException
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from core.actor import Actor, get_actor
from core.json_store import JsonDocumentStore
from ..security import auth_version
from .device_access.access import AccessDenied, _decode, _public_key

LOGIN_TTL = 300
BROWSER_LEASE = 90
OTP_TTL = 600
UNLINK_HOUR = 3600
UNLINK_DELAY = 72 * 3600
ACTIVE = {"code", "phone", "waiting", "ready"}


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def decision_message(flow_id: str, nonce: str, device_id: str, action: str) -> bytes:
    return f"bot4vps-auth-v1\n{flow_id}\n{nonce}\n{device_id}\n{action}".encode("ascii")


def browser_id(request) -> str:
    value = request.session.get("auth_browser")
    if not isinstance(value, str) or len(value) != 43:
        value = secrets.token_urlsafe(32)
        request.session["auth_browser"] = value
    return value


def protection_enabled() -> bool:
    from core.config import get_web_config
    # New protection is opt-in; migration preserves existing owner settings.
    return get_web_config().get("device_unlink_protected") is True


def audit_flow(action, flow, *, result="ok", via=None):
    params = {k: flow[k] for k in ("device_id", "method", "started_at", "finished_at") if k in flow}
    if via:
        params["via"] = via
    flow.setdefault("audit_outbox", []).append({
        "id": secrets.token_hex(16), "action": action, "result": result,
        "op_id": flow["id"], "params": params, "actor": get_actor().to_dict(),
        "ts": int(time.time()),
    })


class AuthFlows:
    def __init__(self, path=Path("data/mobile_devices.json"), *, clock=time.time):
        self.store = JsonDocumentStore(path, name="AUTH FLOWS")
        self.clock = clock

    def _mutate(self, fn):
        from core import config
        from core.json_store import locked
        # Account changes and device changes use the same lock order.
        with locked(config.CONFIG_FILE.with_name(config.CONFIG_FILE.name + ".lock"), config._CONFIG_LOCK):
            result = self.store.mutate(fn)
        from .device_access.access import invalidate_device_sessions
        for row in result:
            if row.get("kind") == "unlink" and row["state"] == "completed":
                invalidate_device_sessions(self.store.path, row["device_id"])
        self.flush_audit()
        return result

    def flush_audit(self):
        from core import audit
        delivered = set()
        for row in self.store.read():
            for event in row.get("audit_outbox", []):
                if audit.record(event["action"], result=event["result"], op_id=event["op_id"],
                                actor=Actor.from_dict(event["actor"]), params=event["params"],
                                ts=event["ts"], record_id=event["id"]):
                    delivered.add(event["id"])
        if not delivered:
            return
        def acknowledge(rows):
            for row in rows:
                if "audit_outbox" in row:
                    row["audit_outbox"] = [e for e in row["audit_outbox"] if e["id"] not in delivered]
                    if not row["audit_outbox"]:
                        row.pop("audit_outbox")
            return [r for r in rows if r.get("kind") != "audit_outbox" or r.get("audit_outbox")]
        self.store.mutate(acknowledge)

    def failed_attempt(self, device_id, method, *, op_id=None, via=None):
        row = {"kind": "audit_outbox", "id": secrets.token_urlsafe(24),
               "device_id": device_id, "method": method, "started_at": self.clock()}
        audit_flow("mobile_api.unlink_attempt", row, result="failed", via=via)
        if op_id:
            row["audit_outbox"][0]["op_id"] = op_id
        self._mutate(lambda rows: rows + [row])

    def _prune(self, rows):
        now = self.clock()
        return [r for r in rows if r.get("kind") not in ("auth", "notice", "cli_access")
                or r.get("expires", 0) > now]

    def _new(self, kind, browser, *, ttl=LOGIN_TTL, **extra):
        return {"kind": kind, "id": secrets.token_urlsafe(24),
                "nonce": secrets.token_urlsafe(32), "browser": fingerprint(browser),
                "version": auth_version(), "state": "pending", "started_at": self.clock(),
                "expires": self.clock() + ttl, "attempts": 0, **extra}

    def _notice(self, rows, device_id, event, **data):
        rows.append({"kind": "notice", "id": secrets.token_urlsafe(24), "device_id": device_id,
                     "event": event, "created": self.clock(), "expires": self.clock() + UNLINK_DELAY,
                     **data})

    def _find(self, rows, flow_id, kind=None):
        row = next((r for r in rows if r.get("id") == flow_id and
                    r.get("kind") in ((kind,) if kind else ("auth", "unlink"))), None)
        if row is None:
            raise HTTPException(404, "Запрос не найден или истёк")
        return row

    def _browser(self, row, browser):
        if not secrets.compare_digest(row.get("browser", ""), fingerprint(browser)):
            raise HTTPException(403, "Запрос принадлежит другой браузерной сессии")

    def _live(self, row):
        if row.get("expires", 0) <= self.clock() or row.get("version") != auth_version():
            raise HTTPException(410, "Запрос истёк или учётные данные изменились")

    def create_login(self, browser, method, username, *, ip=None, agent="", expected_version=None, factor_channel=None):
        result = {}
        def create(rows):
            nonlocal result
            rows = self._prune(rows)
            if method == "qr" and any(r.get("kind") == "auth" and r.get("purpose") == "login"
                    and r.get("method") == "password" and r.get("state") == "pending"
                    and r.get("browser") == fingerprint(browser) for r in rows):
                raise HTTPException(409, "Завершите вход по паролю или отмените его")
            # One login attempt per browser, while other browsers are independent.
            rows = [r for r in rows if not (r.get("kind") == "auth" and
                    r.get("purpose") == "login" and r.get("browser") == fingerprint(browser))]
            if sum(r.get("kind") == "auth" for r in rows) >= 512:
                raise HTTPException(429, "Слишком много запросов входа")
            from .device_access.primary import current
            from ..security import second_factor_enabled
            devices = [] if factor_channel == "telegram" else ([current(rows)] if current(rows) else []) if second_factor_enabled() else [r["id"] for r in rows if r.get("kind") == "device"]
            result = self._new("auth", browser, ttl=OTP_TTL if factor_channel == "telegram" else LOGIN_TTL, purpose="login", method=method, username=username,
                               devices=devices, ip=ip, agent=agent[:256], heartbeat=self.clock(), factor_channel=factor_channel or "totp")
            if expected_version is not None:
                result["version"] = expected_version
            return rows + [result]
        self._mutate(create)
        return result

    def login_status(self, flow_id, browser, *, consume=False):
        result = {}
        def check(rows):
            nonlocal result
            row = self._find(rows, flow_id, "auth")
            self._browser(row, browser)
            self._live(row)
            if row.get("purpose") != "login":
                raise HTTPException(400, "Это не запрос входа")
            if self.clock() - row.get("heartbeat", 0) > BROWSER_LEASE:
                raise HTTPException(410, "Браузерная сессия завершилась")
            row["heartbeat"] = self.clock()
            result = dict(row)
            if consume and row["state"] == "approved":
                row["state"] = "used"
            return rows
        self._mutate(check)
        return result

    def cancel_login(self, browser):
        self._mutate(lambda rows: [r for r in rows if not (r.get("kind") == "auth" and
                          r.get("purpose") == "login" and r.get("browser") == fingerprint(browser))])

    def login_totp(self, flow_id, browser, code):
        from ..security import get_totp_secret, verify_totp_code, second_factor_channel
        error = None
        def confirm(rows):
            nonlocal error
            row = self._find(rows, flow_id, "auth")
            self._browser(row, browser)
            self._live(row)
            if row.get("purpose") != "login" or row.get("method") != "password" or row["state"] != "pending":
                raise HTTPException(409, "Запрос входа уже завершён")
            if self.clock() - row.get("heartbeat", 0) > BROWSER_LEASE:
                raise HTTPException(410, "Браузерная сессия завершилась")
            row["heartbeat"] = self.clock()
            if row["attempts"] >= 5:
                raise HTTPException(429, "Попытки исчерпаны — войдите заново")
            channel = row.get("factor_channel", "totp")
            if channel != second_factor_channel():
                raise HTTPException(410, "Способ подтверждения изменился — войдите заново")
            if channel == "telegram":
                from core.secretbox import decrypt
                from ..telegram_otp import check_telegram_code
                pending = row.get("telegram_otp") or {}
                valid = check_telegram_code({**pending, "code": decrypt(pending["code"]) if pending.get("code") else None},
                                            code, now=self.clock())
            else:
                valid = verify_totp_code(code, get_totp_secret())
            if not valid:
                row["attempts"] += 1
                error = HTTPException(400, "Неверный код")
            else:
                row["state"] = "approved"
                row.pop("telegram_otp", None)
            return rows
        self._mutate(confirm)
        if error:
            raise error

    def attach_login_telegram(self, flow_id, browser, pending, delivery):
        from core.secretbox import encrypt
        from ..security import telegram_delivery_fingerprint
        def attach(rows):
            row = self._find(rows, flow_id, "auth")
            self._browser(row, browser)
            self._live(row)
            if row.get("purpose") != "login" or row.get("state") != "pending" or row.get("method") != "password" or row.get("factor_channel") != "telegram":
                raise HTTPException(409, "Запрос входа завершён")
            if delivery != telegram_delivery_fingerprint():
                raise HTTPException(409, "Настройки Telegram изменились")
            row.update(factor_channel="telegram", devices=[], telegram_otp={**pending, "code": encrypt(pending["code"])})
            return rows
        self._mutate(attach)

    def new_ip_notice(self, ip, agent, *, notify=True):
        from core import config
        from core.json_store import locked
        with locked(config.CONFIG_FILE.with_name(config.CONFIG_FILE.name + ".lock"), config._CONFIG_LOCK):
            previous = config.get_web_config().get("last_login_ip")
            config.patch_web_config({"last_login_ip": ip})
        if not notify or previous == ip:
            return
        def add(rows):
            rows = self._prune(rows)
            from .device_access.primary import current
            primary = current(rows)
            for row in list(rows):
                if row.get("kind") == "device" and row["id"] == primary:
                    self._notice(rows, row["id"], "new_login", ip=ip, agent=agent[:256])
            return rows
        self._mutate(add)

    def start_unlink(self, device_id, method, browser):
        if method not in ("mobile", "totp", "telegram", "delayed", "immediate"):
            raise HTTPException(400, "Неизвестный способ отвязки")
        result = {}
        def start(rows):
            nonlocal result
            rows = self._prune(rows)
            if not any(r.get("kind") == "device" and r.get("id") == device_id for r in rows):
                raise HTTPException(404, "Телефон уже отвязан")
            if any(r.get("kind") == "unlink" and r.get("device_id") == device_id and r["state"] in ACTIVE for r in rows):
                raise HTTPException(409, "Процедура уже идёт. Доступна её отмена.")
            if method == "immediate" and protection_enabled():
                raise HTTPException(403, "Выберите способ подтверждения отвязки")
            result = self._new("unlink", browser, ttl=OTP_TTL, device_id=device_id, method=method,
                               actor=get_actor().to_dict())
            result["state"] = {"mobile": "phone", "totp": "code", "telegram": "code",
                               "delayed": "waiting", "immediate": "waiting"}[method]
            from .device_access.primary import current
            result["recipient_device_id"] = current(rows)
            if method == "mobile" and not result["recipient_device_id"]:
                raise HTTPException(409, "Сначала выберите основной телефон в настройках подключения")
            if method == "mobile":
                result["expires"] = self.clock() + LOGIN_TTL
            if method == "delayed":
                result["deadline"] = self.clock() + UNLINK_DELAY
            audit_flow("mobile_api.unlink_start", result, result="started")
            rows.append(result)
            if method == "immediate":
                rows = self._finish(rows, result, "web_unprotected")
            else:
                self._notice(rows, device_id, "unlink_started", flow_id=result["id"], method=method,
                             deadline=result.get("deadline"))
                if result["state"] != "code":
                    self._unlink_information(rows, result)
            return rows
        try:
            self._mutate(start)
        except HTTPException:
            self.failed_attempt(device_id, method)
            raise
        return self.public_unlink(result)

    def attach_telegram_code(self, flow_id, browser, pending):
        from core.secretbox import encrypt
        def attach(rows):
            row = self._find(rows, flow_id, "unlink")
            self._browser(row, browser)
            self._live(row)
            if row["method"] != "telegram" or row["state"] != "code":
                raise HTTPException(409, "Процедура уже завершена")
            row["otp"] = encrypt(pending["code"])
            row["expires"] = pending["expires_at"]
            return rows
        self._mutate(attach)

    def confirm_unlink_code(self, flow_id, browser, code):
        from ..security import get_totp_secret, verify_totp_code, totp_registered
        from ..telegram_otp import check_telegram_code
        from core.secretbox import decrypt
        result, error = {}, None
        def confirm(rows):
            nonlocal result, error
            row = self._find(rows, flow_id, "unlink")
            self._browser(row, browser)
            self._live(row)
            if row["state"] != "code" or row["method"] not in ("totp", "telegram"):
                raise HTTPException(409, "Подтверждение уже завершено")
            if row["attempts"] >= 5:
                raise HTTPException(429, "Попытки исчерпаны")
            if row["method"] == "totp":
                valid = totp_registered() and verify_totp_code(code, get_totp_secret())
            else:
                pending = {"code": decrypt(row.get("otp", "")), "expires_at": row["expires"], "attempts": row["attempts"]}
                valid = check_telegram_code(pending, code, now=self.clock())
            if not valid:
                row["attempts"] += 1
                audit_flow("mobile_api.unlink_confirmation", row, result="failed", via=row["method"])
                if row["attempts"] >= 5:
                    self._cancel(rows, row, "attempts_exhausted")
                error = HTTPException(400, "Неверный или просроченный код")
            else:
                row.pop("otp", None)
                row.update(state="waiting", deadline=self.clock() + UNLINK_HOUR, nonce=secrets.token_urlsafe(32))
                audit_flow("mobile_api.unlink_confirmation", row, via=row["method"])
                self._notice(rows, row["device_id"], "unlink_waiting", flow_id=row["id"],
                             method=row["method"], deadline=row["deadline"])
                self._unlink_information(rows, row)
            result = self.public_unlink(row)
            return rows
        self._mutate(confirm)
        if error:
            raise error
        return result

    def _finish(self, rows, row, via):
        row.update(state="completed", finished_at=self.clock(), completion=via)
        row.pop("otp", None)
        audit_flow("mobile_api.device_revoke", row, via=via)
        device_id = row["device_id"]
        self._unlinked_notice(rows, device_id)
        self._primary_unlinked(rows, device_id, completion=row)
        # Public keys, enrollment proofs, device notices and device operations
        # are removed together. Gateway watches the registry on open sockets.
        return [r for r in rows if not (r.get("kind") == "auth" and r.get("approved_by") == device_id)
                and not (r.get("device_id") == device_id and r is not row
                                       and r.get("kind") in ("auth", "notice"))
                and not (r.get("kind") == "device" and r.get("id") == device_id)]

    def _unlinked_notice(self, rows, device_id):
        from .device_access.primary import current
        chief = current(rows)
        if chief and chief != device_id:
            target = next((r for r in rows if r.get("kind") == "device" and r.get("id") == device_id), None)
            if target:
                name = target.get("name", "Телефон")
                self._notice(rows, chief, "device_unlinked", target_device_id=device_id, target_name=name,
                             message="Доступ телефона «" + name + "» отозван")

    def _primary_unlinked(self, rows, device_id, *, completion=None):
        from core.config import get_web_config
        from ..security import totp_enabled, clear_totp_secret, second_factor_channel
        from .device_access.primary import current, assign
        primary = current(rows)
        remaining = [r for r in rows if r.get("kind") == "device" and r["id"] != device_id]
        if primary == device_id or primary is None and get_web_config().get("mobile_primary_selection_pending"):
            selected = remaining[0] if len(remaining) == 1 else None
            assign(selected["id"] if selected else None, selection_pending=len(remaining) > 1)
            if completion is not None:
                completion.update(primary_phone_unlinked=primary == device_id,
                    primary_device_id=selected["id"] if selected else None,
                    primary_device_name=selected.get("name", "Телефон") if selected else None,
                    primary_selection_required=len(remaining) > 1)
            if selected:
                self._notice(rows, selected["id"], "primary_assigned", target_name=selected.get("name", "Телефон"),
                    message="Телефон «" + selected.get("name", "Телефон") + "» автоматически назначен основным после отвязки другого устройства")
            elif remaining:
                for device in remaining:
                    self._notice(rows, device["id"], "primary_selection_required",
                        message="Основной телефон отвязан. Выберите новый основной телефон в веб-панели, подтвердив выбор паролем администратора.")
        if not totp_enabled() or get_web_config().get("totp_device_id") != device_id:
            return
        generation = clear_totp_secret(via="primary_phone_unlink", fallback_telegram=True, preserve_sessions=True)
        channel = second_factor_channel()
        if completion is not None:
            completion["two_factor_channel"] = channel
            completion["primary_phone_unlinked"] = True
        for device in list(rows):
            if device.get("kind") == "device" and device["id"] != device_id:
                if generation:
                    self._notice(rows, device["id"], "totp_removed", totp_generation=generation)
                self._notice(rows, device["id"], "two_factor_telegram" if channel else "two_factor_disabled")

    def disconnect_phone(self, device_id):
        """A verified phone may relinquish only its own access, including protected access."""
        result = {}
        def disconnect(rows):
            nonlocal result
            rows = self._prune(rows)
            if not any(r.get("kind") == "device" and r.get("id") == device_id for r in rows):
                raise HTTPException(404, "Телефон уже отвязан")
            for row in rows:
                if row.get("kind") == "unlink" and row.get("device_id") == device_id and row["state"] in ACTIVE:
                    row.update(state="cancelled", finished_at=self.clock(), cancellation="phone_disconnect")
                    row.pop("otp", None)
            result = self._new("unlink", "phone:" + device_id, ttl=OTP_TTL, device_id=device_id,
                               method="mobile", actor=get_actor().to_dict())
            audit_flow("mobile_api.unlink_start", result, result="started", via="phone_disconnect")
            rows.append(result)
            return self._finish(rows, result, "phone_disconnect")
        self._mutate(disconnect)
        return {"ok": True, "device_id": device_id,
                **{key: result[key] for key in ("primary_phone_unlinked", "two_factor_channel", "primary_device_id", "primary_device_name", "primary_selection_required") if key in result}}

    def _cancel(self, rows, row, via):
        row.update(state="cancelled", finished_at=self.clock(), cancellation=via)
        row.pop("otp", None)
        audit_flow("mobile_api.unlink_cancel", row, result="cancelled", via=via)
        self._notice(rows, row["device_id"], "unlink_cancelled", flow_id=row["id"], via=via)

    def web_unlink_action(self, flow_id, action):
        result = {}
        def change(rows):
            nonlocal result
            row = self._find(rows, flow_id, "unlink")
            if row["state"] not in ACTIVE:
                raise HTTPException(409, "Процедура уже завершена")
            if action == "cancel":
                self._cancel(rows, row, "web")
            elif action == "finish" and row["method"] == "delayed" and row.get("deadline", float("inf")) <= self.clock():
                rows = self._finish(rows, row, "web_after_72h")
            else:
                audit_flow("mobile_api.unlink_attempt", row, result="failed", via="web_early_finish")
                raise HTTPException(403, "В веб-панели сейчас доступна только отмена отвязки")
            result = self.public_unlink(row)
            return rows
        try:
            self._mutate(change)
        except HTTPException:
            failed = next((r for r in self.store.read() if r.get("kind") == "unlink" and r.get("id") == flow_id), None)
            if failed:
                self.failed_attempt(failed["device_id"], failed["method"], op_id=flow_id, via="web")
            raise
        return result

    def _unlink_information(self, rows, row):
        from .device_access.primary import current
        if row["device_id"] != current(rows):
            self._notice(rows, row["device_id"], "unlink_requested", flow_id=row["id"],
                deadline=row.get("deadline"), method=row["method"],
                message="Администратор запросил отзыв доступа этого телефона. Для отмены свяжитесь с администратором.",
                mobile_actions=["ack"], acknowledge_label="Ок")

    def public_unlink(self, row):
        result = {k: row[k] for k in ("id", "device_id", "method", "state", "started_at", "deadline", "finished_at", "cancellation", "completion", "primary_phone_unlinked", "two_factor_channel", "primary_device_id", "primary_device_name", "primary_selection_required") if k in row}
        result["remaining"] = max(0, int(row.get("deadline", 0) - self.clock()))
        result["can_finish"] = row["state"] in ("waiting", "ready") and row["method"] == "delayed" and row.get("deadline", float("inf")) <= self.clock()
        result["mobile_actions"] = []
        if row["state"] == "phone":
            result["mobile_actions"] = ["approve", "reject"]
        elif row["state"] == "code":
            result["mobile_actions"] = ["cancel"]
        elif row["state"] in ("waiting", "ready"):
            result["mobile_actions"] = ["cancel"]
            if row["method"] != "delayed" or row.get("deadline", float("inf")) <= self.clock():
                result["mobile_actions"].insert(0, "approve")
        return result

    def reconcile(self):
        def tick(rows):
            rows = self._prune(rows)
            for row in list(rows):
                if row.get("kind") != "unlink" or row["state"] not in ACTIVE:
                    continue
                if row["state"] in ("code", "phone") and row["expires"] <= self.clock():
                    self._cancel(rows, row, "expired")
                elif row["state"] == "waiting" and row.get("deadline", float("inf")) <= self.clock():
                    if row["method"] == "delayed":
                        row["state"] = "ready"
                        self._notice(rows, row["device_id"], "unlink_ready", flow_id=row["id"])
                    else:
                        rows = self._finish(rows, row, "timer")
            # Procedure history lives in append-only audit; keep recent state.
            finished = [r for r in rows if r.get("kind") == "unlink" and r["state"] not in ACTIVE and not r.get("audit_outbox")]
            old = {r["id"] for r in finished[:-128]}
            return [r for r in rows if r.get("id") not in old]
        self._mutate(tick)

    def unlink_states(self):
        self.reconcile()
        return [self.public_unlink(r) for r in self.store.read() if r.get("kind") == "unlink" and r["state"] in ACTIVE]

    def inbox(self, device_id):
        self.reconcile()
        result = []
        from .device_access.primary import current
        rows = self.store.read()
        primary = current(rows)
        for row in rows:
            if row.get("kind") == "notice" and row.get("device_id") == device_id:
                result.append({k: v for k, v in row.items() if k not in ("kind", "device_id", "expires")})
            elif row.get("kind") == "unlink" and row["state"] in ACTIVE:
                if primary == device_id:
                    target = next((r for r in rows if r.get("kind") == "device" and r.get("id") == row["device_id"]), {})
                    result.append({**self.public_unlink(row), "purpose": "unlink" if row["device_id"] == device_id else "unlink_other",
                        "nonce": row["nonce"], "target_device_id": row["device_id"], "target_name": target.get("name", "Телефон")})
            elif row.get("kind") == "auth" and row.get("purpose") in ("login", "protection_disable", "two_factor_enable", "two_factor_disable", "primary_transfer") and not row.get("completed") and (row["state"] in ("pending", "confirming") or row.get("purpose") in ("two_factor_enable", "primary_transfer") and row["state"] == "approved") and row.get("version") == auth_version() and (
                    row.get("device_id") == device_id or device_id in row.get("devices", [])):
                if row.get("purpose") in ("protection_disable", "two_factor_enable", "two_factor_disable") and primary != device_id:
                    if not (row.get("purpose") == "two_factor_enable" and primary is None and row.get("primary_before") is None):
                        continue
                if row.get("purpose") == "login" and (row.get("method") == "qr" or self.clock() - row.get("heartbeat", 0) > BROWSER_LEASE):
                    continue
                result.append({k: row[k] for k in ("id", "nonce", "purpose", "started_at", "expires", "ip", "agent", "username", "received_at") if k in row})
        return result

    def received_primary(self, device_id, flow_id, nonce):
        """Record receipt, never a decision; keep the challenge available for retry."""
        result = {}
        def receive(rows):
            nonlocal result
            row = self._find(rows, flow_id, "auth")
            self._live(row)
            if (row.get("purpose") != "primary_transfer" or row.get("device_id") != device_id or
                    not any(r.get("kind") == "device" and r.get("id") == device_id for r in rows) or
                    not secrets.compare_digest(row.get("nonce", ""), nonce)):
                raise HTTPException(403, "Это запрос другого устройства")
            if row.get("completed") or row.get("state") not in ("pending", "approved", "confirming"):
                raise HTTPException(409, "Запрос уже завершён")
            row.setdefault("received_at", self.clock())
            result = {"ok": True, "received_at": row["received_at"]}
            return rows
        self._mutate(receive)
        return result

    def acknowledge(self, device_id, notice_id):
        self._mutate(lambda rows: [r for r in rows if not (r.get("kind") == "notice" and
                          r.get("device_id") == device_id and r.get("id") == notice_id)])

    def login_preview(self, device_id, flow_id):
        from .device_access.primary import require
        from ..security import second_factor_enabled
        if second_factor_enabled():
            require(self.store.read(), device_id)
        row = self._find(self._prune(self.store.read()), flow_id, "auth")
        self._live(row)
        if (row.get("purpose") != "login" or row.get("method") != "qr"
                or device_id not in row.get("devices", []) or row.get("state") != "pending"):
            raise HTTPException(404, "Запрос входа не найден")
        if self.clock() - row.get("heartbeat", 0) > BROWSER_LEASE:
            raise HTTPException(410, "Браузерная сессия завершилась")
        return {k: row[k] for k in ("id", "nonce", "purpose", "started_at", "expires", "ip", "agent") if k in row}

    def signed_decision(self, device_id, flow_id, action, signature):
        result = {}
        def decide(rows):
            nonlocal result
            row = self._find(rows, flow_id)
            from .device_access.primary import require
            from ..security import second_factor_enabled
            if row["kind"] == "unlink" or row.get("purpose") == "login" and second_factor_enabled():
                require(rows, device_id)
            if row.get("purpose") in ("two_factor_enable", "two_factor_disable", "protection_disable"):
                from .device_access.primary import require_factor_authority
                require_factor_authority(rows, device_id, row)
            device = next((r for r in rows if r.get("kind") == "device" and r.get("id") == device_id), None)
            if device is None or not (row.get("device_id") == device_id or device_id in row.get("devices", []) or
                    row["kind"] == "unlink"):
                raise HTTPException(403, "Это запрос другого устройства")
            if action not in ("approve", "reject", "cancel"):
                raise HTTPException(400, "Неизвестное действие")
            try:
                _public_key(device["public_key"]).verify(_decode(signature, 256),
                    decision_message(flow_id, row["nonce"], device_id, action), ec.ECDSA(hashes.SHA256()))
            except (InvalidSignature, AccessDenied, ValueError, KeyError):
                if row["kind"] == "unlink":
                    audit_flow("mobile_api.unlink_confirmation", row, result="failed", via="mobile_signature")
                raise HTTPException(403, "Подпись устройства недействительна") from None
            if row["kind"] == "unlink":
                if row["state"] not in ACTIVE:
                    raise HTTPException(409, "Процедура уже завершена")
                if action in ("cancel", "reject"):
                    self._cancel(rows, row, "mobile_reject" if action == "reject" else "mobile")
                elif row["state"] == "phone" or (row["state"] in ("waiting", "ready") and
                      (row["method"] != "delayed" or row["deadline"] <= self.clock())):
                    if row["state"] == "phone":
                        self._live(row)
                    rows = self._finish(rows, row, "mobile")
                else:
                    raise HTTPException(403, "Срок ожидания ещё не закончился")
                result = self.public_unlink(row)
            else:
                self._live(row)
                if row["state"] in ("approved", "confirming") and row.get("purpose") in ("two_factor_enable", "primary_transfer") and not row.get("completed"):
                    if action == "approve":
                        result = {"ok": True, "state": row["state"]}
                        return rows
                    row["state"] = "rejected"
                    rows = [r for r in rows if r.get("id") != row.get("setup_id")]
                    result = {"ok": True, "state": "rejected"}
                    return rows
                if row["state"] != "pending":
                    raise HTTPException(409, "Запрос уже использован")
                if row["purpose"] == "login" and self.clock() - row.get("heartbeat", 0) > BROWSER_LEASE:
                    raise HTTPException(410, "Браузерная сессия завершилась")
                if row["purpose"] not in ("login", "protection_disable", "two_factor_enable", "two_factor_disable", "primary_transfer"):
                    raise HTTPException(400, "Для этой операции требуется TOTP-код")
                row["state"] = "approved" if action == "approve" else "rejected"
                row["approved_by"] = device_id
                if row["purpose"] == "login":
                    from core import audit
                    audit.record("web.login_decision", result="ok" if action == "approve" else "failed",
                                 op_id=row["id"], params={"method": row["method"], "decision": action})
                if row["purpose"] == "protection_disable" and action == "approve":
                    self.set_protection(False, via="mobile", expected_version=row["version"])
                if row["purpose"] == "two_factor_disable" and action == "approve":
                    rows = self._disable_totp(rows, row["version"], "mobile", completion=row)
                result = {"ok": True, "state": row["state"]}
            return rows
        try:
            self._mutate(decide)
        except HTTPException:
            failed = next((r for r in self.store.read() if r.get("kind") == "unlink" and r.get("id") == flow_id), None)
            if failed:
                self.failed_attempt(failed["device_id"], failed["method"], op_id=flow_id, via="mobile")
            raise
        return result

    def set_protection(self, enabled, *, via, expected_version=None):
        from core import config
        from core.json_store import locked
        from core import audit
        with locked(config.CONFIG_FILE.with_name(config.CONFIG_FILE.name + ".lock"), config._CONFIG_LOCK):
            if expected_version is not None and expected_version != auth_version():
                raise HTTPException(409, "Учётные данные изменились — начните подтверждение заново")
            config.patch_web_config({"device_unlink_protected": bool(enabled)})
        audit.record("mobile_api.unlink_protection", result="ok", params={"enabled": bool(enabled), "via": via})

    def request_primary(self, browser, device_id, *, expected_version, code="", telegram_id=None):
        from core.config import get_web_config
        from .device_access.primary import current, assign
        from ..security import totp_enabled, verify_totp_code, get_totp_secret, telegram_delivery_fingerprint
        from ..app import _recovery_available
        result = {}
        def choose(rows):
            nonlocal result
            if expected_version != auth_version():
                raise HTTPException(409, "Учётные данные изменились — начните заново")
            if not any(row.get("kind") == "device" and row.get("id") == device_id for row in rows):
                raise HTTPException(404, "Телефон уже отвязан")
            if telegram_id:
                authorization = self._find(rows, telegram_id, "auth")
                self._browser(authorization, browser)
                self._live(authorization)
                if (authorization.get("purpose") != "primary_authorization" or authorization.get("device_id") != device_id or
                        authorization.get("state") != "approved" or not authorization.get("completed") or
                        authorization.get("delivery") != telegram_delivery_fingerprint() or not _recovery_available()):
                    raise HTTPException(403, "Подтвердите назначение этого телефона отдельным кодом Telegram")
                authorization["state"] = "used"
            elif get_web_config().get("mobile_primary_selection_pending") and current(rows) is None:
                pass  # The Web route has already verified the administrator password.
            elif totp_enabled():
                if not verify_totp_code(code, get_totp_secret()):
                    raise HTTPException(403, "Введите действующий TOTP-код")
            elif _recovery_available():
                raise HTTPException(403, "Подтвердите назначение кодом Telegram")
            web = get_web_config()
            if current(rows) == device_id:
                result = {"ok": True, "primary_device_id": device_id}
                return rows
            if (not totp_enabled() or web.get("totp_device_id") == device_id or
                    not web.get("totp_device_id") and web.get("totp_source") == "external"):
                assign(device_id)
                result = {"ok": True, "primary_device_id": device_id}
                return rows
            if any(row.get("kind") == "auth" and row.get("purpose") == "primary_transfer" and not row.get("completed") and row.get("state") in ("pending", "approved", "confirming") and row.get("expires", 0) > self.clock() for row in rows):
                raise HTTPException(409, "Сначала завершите или отмените перенос основного телефона")
            pending = self._new("auth", browser, ttl=OTP_TTL, purpose="primary_transfer", device_id=device_id,
                primary_before=current(rows), initiating_version=expected_version,
                username=web.get("username", "admin"))
            result = {"ok": False, "pending": True, "id": pending["id"], "primary_device_id": current(rows),
                "message": "Ожидаем установку TOTP на новом телефоне. Прежний основной телефон сохраняет доступ до подтверждения."}
            return rows + [pending]
        self._mutate(choose)
        return result

    def request_two_factor(self, browser, device_id, enabled, *, ip=None, agent="", expected_version=None):
        from ..security import totp_enabled, totp_registered, second_factor_enabled
        from core.config import get_web_config
        result = {}
        def add(rows):
            nonlocal result
            rows = self._prune(rows)
            if expected_version is not None and expected_version != auth_version():
                raise HTTPException(409, "Учётные данные изменились — начните заново")
            from .device_access.primary import current, require
            primary = current(rows)
            target = primary if device_id is None else device_id
            if primary:
                require(rows, target)
            elif get_web_config().get("mobile_primary_selection_pending"):
                raise HTTPException(409, "Сначала выберите основной телефон, подтвердив выбор паролем администратора")
            elif not enabled or target is None:
                raise HTTPException(409, "Сначала назначьте основной телефон в настройках мобильного приложения")
            if not any(r.get("kind") == "device" and r.get("id") == target for r in rows):
                raise HTTPException(404, "Доверенный телефон не найден")
            if enabled and totp_enabled():
                raise HTTPException(409, "2FA уже включена")
            if not enabled and not second_factor_enabled() and not totp_registered():
                raise HTTPException(409, "2FA уже выключена")
            purpose = "two_factor_enable" if enabled else "two_factor_disable"
            rows = [r for r in rows if not (r.get("kind") == "auth" and r.get("purpose") == purpose and r.get("browser") == fingerprint(browser))]
            result = self._new("auth", browser, purpose=purpose, device_id=target, primary_before=primary,
                               username=get_web_config().get("username", "admin"), ip=ip, agent=agent[:256])
            if expected_version is not None:
                result["version"] = expected_version
            result["initiating_version"] = result["version"]
            return rows + [result]
        self._mutate(add)
        return {"ok": False, "pending": True, "id": result["id"]}

    def two_factor_status(self, flow_id, browser):
        row = self._find(self._prune(self.store.read()), flow_id, "auth")
        self._browser(row, browser)
        self._live(row)
        if row.get("purpose") not in ("two_factor_enable", "two_factor_disable", "two_factor_telegram_enable", "two_factor_telegram_disable", "primary_transfer"):
            raise HTTPException(404, "Запрос 2FA не найден")
        return row

    def cancel_two_factor(self, flow_id, browser):
        def cancel(rows):
            row = self._find(rows, flow_id, "auth")
            self._browser(row, browser)
            self._live(row)
            if row.get("purpose") not in ("two_factor_enable", "two_factor_disable", "two_factor_telegram_enable", "two_factor_telegram_disable", "primary_transfer") or row.get("completed"):
                raise HTTPException(409, "Запрос уже завершён")
            row["state"] = "rejected"
            row.pop("telegram_otp", None)
            return [r for r in rows if r.get("id") != row.get("setup_id")]
        self._mutate(cancel)

    def setup_telegram_factor(self, browser, enabled, pending, *, expected_version, delivery, purpose=None, device_id=None):
        from core.secretbox import encrypt
        from ..security import telegram_delivery_fingerprint, second_factor_channel
        from core.config import get_web_config
        result = {}
        if purpose not in (None, "protection_telegram_disable", "primary_authorization"):
            raise HTTPException(400, "Неизвестное назначение кода")
        purpose = purpose or ("two_factor_telegram_enable" if enabled else "two_factor_telegram_disable")
        def setup(rows):
            nonlocal result
            if expected_version != auth_version() or delivery != telegram_delivery_fingerprint():
                raise HTTPException(409, "Настройки изменились — начните заново")
            if not enabled and second_factor_channel() != "telegram":
                raise HTTPException(409, "Второй фактор Telegram не включён")
            if purpose == "primary_authorization" and not any(row.get("kind") == "device" and row.get("id") == device_id for row in rows):
                raise HTTPException(404, "Телефон уже отвязан")
            result = self._new("auth", browser, ttl=OTP_TTL, purpose=purpose,
                               **({"device_id": device_id} if purpose == "primary_authorization" else {}),
                               username=get_web_config().get("username", "admin"),
                               initiating_version=expected_version, delivery=delivery,
                               telegram_otp={**pending, "code": encrypt(pending["code"])})
            rows = [row for row in self._prune(rows) if not (row.get("kind") == "auth"
                    and row.get("purpose") == purpose and row.get("browser") == fingerprint(browser))]
            return rows + [result]
        self._mutate(setup)
        return {"id": result["id"], "pending": True, "ok": False}

    def confirm_telegram_factor(self, flow_id, browser, code, *, purpose=None):
        from core.secretbox import decrypt
        from ..security import telegram_delivery_fingerprint, clear_totp_secret, second_factor_channel
        from ..telegram_otp import check_telegram_code
        from ..app import _recovery_available
        error, version = None, None
        def confirm(rows):
            nonlocal error, version
            row = self._find(rows, flow_id, "auth")
            self._browser(row, browser)
            self._live(row)
            allowed = (purpose,) if purpose in ("protection_telegram_disable", "primary_authorization") else ("two_factor_telegram_enable", "two_factor_telegram_disable")
            if row.get("purpose") not in allowed:
                raise HTTPException(404, "Запрос Telegram не найден")
            if row.get("completed"):
                if row.get("purpose") in ("protection_telegram_disable", "primary_authorization"):
                    raise HTTPException(409, "Код уже использован")
                version = row["version"]
                return rows
            if row.get("state") != "pending":
                raise HTTPException(409, "Запрос отменён")
            if not _recovery_available() or row["delivery"] != telegram_delivery_fingerprint():
                raise HTTPException(409, "Настройки Telegram изменились — начните заново")
            if row["attempts"] >= 5:
                raise HTTPException(429, "Попытки исчерпаны")
            pending = row.get("telegram_otp") or {}
            if not check_telegram_code({**pending, "code": decrypt(pending["code"]) if pending.get("code") else None}, code, now=self.clock()):
                row["attempts"] += 1
                error = HTTPException(400, "Неверный код")
                return rows
            if row["purpose"] == "two_factor_telegram_enable":
                generation, version = clear_totp_secret(via="telegram_code", expected_version=row["version"],
                                                        fallback_telegram=True, with_version=True)
                for device in list(rows):
                    if device.get("kind") == "device":
                        if generation:
                            self._notice(rows, device["id"], "totp_removed", totp_generation=generation)
                        self._notice(rows, device["id"], "two_factor_telegram")
            elif row["purpose"] == "protection_telegram_disable":
                self.set_protection(False, via="telegram_code", expected_version=row["version"])
                version = auth_version()
            elif row["purpose"] == "primary_authorization":
                version = auth_version()
            else:
                if second_factor_channel() != "telegram":
                    raise HTTPException(409, "Способ подтверждения изменился")
                rows = self._disable_totp(rows, row["version"], "telegram_code", completion=row)
                version = row["version"]
            row.update(version=version, completed=True, state="approved")
            row.pop("telegram_otp", None)
            return rows
        self._mutate(confirm)
        if error:
            raise error
        return version

    def _disable_totp(self, rows, expected_version, via, *, completion=None):
        from ..security import clear_totp_secret
        generation, version = clear_totp_secret(via=via, expected_version=expected_version, with_version=True)
        if completion is not None:
            completion.update(version=version, completed=True)
        for row in list(rows):
            if row.get("kind") == "device":
                if generation:
                    self._notice(rows, row["id"], "totp_removed", totp_generation=generation)
                self._notice(rows, row["id"], "two_factor_disabled")
        return rows

    def disable_totp(self, *, expected_version, via="settings"):
        completion = {}
        self._mutate(lambda rows: self._disable_totp(rows, expected_version, via, completion=completion))
        return completion["version"]

    def request_protection_disable(self, browser, device_id):
        result = {}
        def add(rows):
            nonlocal result
            rows = self._prune(rows)
            from .device_access.primary import require
            require(rows, device_id)
            if not any(r.get("kind") == "device" and r.get("id") == device_id for r in rows):
                raise HTTPException(404, "Телефон не найден")
            rows = [r for r in rows if not (r.get("kind") == "auth" and r.get("purpose") == "protection_disable" and r.get("browser") == fingerprint(browser))]
            result = self._new("auth", browser, purpose="protection_disable", device_id=device_id)
            return rows + [result]
        self._mutate(add)
        return {"ok": False, "pending": True, "id": result["id"]}

    def setup_totp(self, owner, *, device_id=None, replace=False, expected_version=None, enable_flow_id=None):
        from ..security import make_totp_secret, totp_registered, totp_provisioning_uri, totp_enabled
        from core.config import get_web_config
        from core.secretbox import encrypt
        result = {}
        def setup(rows):
            nonlocal result, replace
            rows = self._prune(rows)
            if expected_version is not None and expected_version != auth_version():
                raise HTTPException(409, "Учётные данные изменились — начните заново")
            if device_id and not any(r.get("kind") == "device" and r.get("id") == device_id for r in rows):
                raise HTTPException(403, "Телефон уже отвязан")
            enable = None
            if enable_flow_id:
                enable = self._find(rows, enable_flow_id, "auth")
                self._live(enable)
                if enable.get("purpose") not in ("two_factor_enable", "primary_transfer") or enable.get("device_id") != device_id or enable["state"] not in ("approved", "confirming"):
                    raise HTTPException(403, "Подтвердите включение 2FA на доверенном телефоне")
                if enable.get("purpose") == "primary_transfer":
                    from .device_access.primary import current
                    if current(rows) != enable.get("primary_before"):
                        raise HTTPException(409, "Основной телефон уже изменился")
                    replace = True
                else:
                    from .device_access.primary import require_factor_authority
                    require_factor_authority(rows, device_id, enable)
                existing = next((r for r in rows if r.get("id") == enable.get("setup_id") and r.get("state") == "pending"), None)
                if existing:
                    from core.secretbox import decrypt
                    result = {"id": existing["id"], "secret": decrypt(existing["secret"]), "uri": totp_provisioning_uri(decrypt(existing["secret"]), get_web_config().get("username", "admin"))}
                    return rows
            if device_id and enable is None:
                from .device_access.access import MobileAccess
                if not MobileAccess(self.store.path).totp_setup_allowed(device_id):
                    raise HTTPException(403, "TOTP доступен основному телефону. Другой телефон выбирается при настройке 2FA в веб-панели")
            if totp_registered() and totp_enabled() and not replace:
                result = {"registered": True, "reuse": True}
                return rows
            if totp_registered() and not totp_enabled():
                replace = True
            secret = make_totp_secret()
            row = self._new("auth", owner, ttl=OTP_TTL, purpose="totp_setup", secret=encrypt(secret),
                            device_id=device_id, replace=replace, enabled_after=True, enable_flow_id=enable_flow_id)
            if expected_version is not None:
                row["version"] = expected_version
            rows = [r for r in rows if not (r.get("kind") == "auth" and r.get("purpose") == "totp_setup" and r.get("browser") == fingerprint(owner))]
            if enable is not None:
                enable.update(state="confirming", setup_id=row["id"])
            result = {"id": row["id"], "secret": secret,
                      "uri": totp_provisioning_uri(secret, get_web_config().get("username", "admin"))}
            return rows + [row]
        self._mutate(setup)
        return result

    def confirm_totp(self, flow_id, owner, code, *, enabled=True):
        from ..security import totp_registered, verify_totp_code, set_totp_secret
        from core.secretbox import decrypt
        error = None
        version = None
        def confirm(rows):
            nonlocal error, version
            row = self._find(rows, flow_id, "auth")
            self._browser(row, owner)
            self._live(row)
            if row.get("purpose") != "totp_setup" or row["state"] != "pending" or (totp_registered() and not row.get("replace")):
                raise HTTPException(409, "TOTP уже зарегистрирован или запрос завершён")
            if row.get("device_id"):
                device_id = row["device_id"]
                if not any(item.get("kind") == "device" and item.get("id") == device_id for item in rows):
                    raise HTTPException(403, "Телефон уже отвязан")
                if not row.get("enable_flow_id"):
                    from .device_access.access import MobileAccess
                    if not MobileAccess(self.store.path).totp_setup_allowed(device_id):
                        raise HTTPException(403, "Телефон больше не выбран для настройки TOTP")
            if row["attempts"] >= 5:
                raise HTTPException(429, "Попытки исчерпаны")
            enable = None
            if row.get("enable_flow_id"):
                enable = self._find(rows, row["enable_flow_id"], "auth")
                self._live(enable)
                if enable.get("purpose") not in ("two_factor_enable", "primary_transfer") or enable.get("device_id") != row.get("device_id") or enable.get("state") != "confirming":
                    raise HTTPException(409, "Запрос включения 2FA отменён")
                if enable.get("purpose") == "primary_transfer":
                    from .device_access.primary import current
                    if current(rows) != enable.get("primary_before"):
                        raise HTTPException(409, "Основной телефон уже изменился")
                else:
                    from .device_access.primary import require_factor_authority
                    require_factor_authority(rows, row.get("device_id"), enable)
            secret = decrypt(row["secret"])
            if not verify_totp_code(code, secret):
                row["attempts"] += 1
                error = HTTPException(400, "Неверный код")
            else:
                version, generation = set_totp_secret(secret, enabled=row["enabled_after"] if row.get("replace") else enabled,
                                expected_version=row["version"], device_id=row.get("device_id"))
                row["totp_generation"] = generation
                row.pop("secret", None)
                row["state"] = "used"
                if enable is None and row.get("device_id") and not row.get("replace"):
                    device = next(item for item in rows if item.get("kind") == "device" and item["id"] == row["device_id"])
                    binding = device.get("first_pairing_web") or {}
                    if binding.get("version") == row["version"] and binding.get("expires", 0) > self.clock():
                        device["pairing_auth_continuity"] = {**binding, "approved_version": version}
                if enable is not None:
                    enable.update(state="approved", version=version, completed=True)
            return rows
        self._mutate(confirm)
        if error:
            raise error
        return version

    def mobile_totp_setup_status(self, device_id, flow_id):
        """Recover a lost confirmation response without exposing a TOTP secret."""
        from core.config import get_web_config
        row = self._find(self.store.read(), flow_id, "auth")
        self._browser(row, "phone:" + device_id)
        if row.get("purpose") != "totp_setup" or row.get("device_id") != device_id:
            raise HTTPException(404, "Не найдено")
        stored = get_web_config().get("totp_secret")
        generation = fingerprint(stored)[:24] if isinstance(stored, str) and stored else None
        registered = row.get("state") == "used" and generation is not None and row.get("totp_generation") == generation
        from ..security import second_factor_enabled
        return {"registered": registered, "two_factor_enabled": second_factor_enabled(), "totp_generation": generation if registered else None}

    def issue_cli_access(self):
        from .cli_recovery import require_cli_recovery_enabled
        require_cli_recovery_enabled()
        from core import audit
        token = secrets.token_urlsafe(32)
        row = {"kind": "cli_access", "hash": fingerprint(token), "version": auth_version(),
               "expires": self.clock() + OTP_TTL}
        self._mutate(lambda rows: self._prune([r for r in rows if r.get("kind") != "cli_access"]) + [row])
        audit.record("web.recovery_issue", result="ok", actor=Actor.cli())
        return token

    def use_cli_access(self, token):
        from .cli_recovery import require_cli_recovery_enabled
        require_cli_recovery_enabled()
        version = None
        def consume(rows):
            nonlocal version
            row = next((r for r in rows if r.get("kind") == "cli_access" and
                        secrets.compare_digest(r.get("hash", ""), fingerprint(token))), None)
            if row is None or row["expires"] <= self.clock() or row["version"] != auth_version():
                raise HTTPException(403, "Код восстановления недействителен или истёк")
            version = row["version"]
            return [r for r in rows if r is not row]
        self._mutate(consume)
        return version


async def unlink_worker():
    import asyncio
    while True:
        try:
            await asyncio.to_thread(AuthFlows().reconcile)
        except Exception as exc:
            print(f"[AUTH] Не удалось проверить сроки отвязки: {type(exc).__name__}", flush=True)
        await asyncio.sleep(2)
