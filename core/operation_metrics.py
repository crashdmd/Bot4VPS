"""Фактический пик метрик во время разрешённых операций."""
from __future__ import annotations

import contextvars
import math
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from core import state_db
from core.audit_actions import AuditAction, AuditResult


OPERATION_METRIC_INTERVAL_SECONDS = 10.0


@dataclass(frozen=True)
class OperationSpec:
    scope: str
    owner: str


@dataclass(frozen=True)
class OperationIdentity:
    operation_id: str
    server_id: str
    server_name: Optional[str]
    scope: str


@dataclass(frozen=True)
class DirectOperationSpec(OperationSpec):
    audit_action: AuditAction


_SERVICE_TASK_ACTIONS = frozenset({
    "install",
    "remove",
    "update",
    "daemon_start",
    "daemon_stop",
    "daemon_restart",
})

_QUICK_SETUP_ACTIONS = frozenset({
    AuditAction.SYSTEM_UPGRADE,
    AuditAction.PACKAGES_INSTALL,
    AuditAction.FIREWALL_ENABLE,
    AuditAction.FIREWALL_DISABLE,
    AuditAction.FIREWALL_PORT_OPEN,
    AuditAction.FIREWALL_PORT_CLOSE,
    AuditAction.FIREWALL_BACKEND_SWITCH,
    AuditAction.FIREWALL_BACKEND_INSTALL,
    AuditAction.FIREWALL_BACKEND_REMOVE,
    AuditAction.FAIL2BAN_INSTALL,
    AuditAction.FAIL2BAN_UNINSTALL,
    AuditAction.FAIL2BAN_SETTINGS,
    AuditAction.FAIL2BAN_JAIL_TOGGLE,
    AuditAction.FAIL2BAN_WHITELIST_ADD,
    AuditAction.FAIL2BAN_WHITELIST_REMOVE,
    AuditAction.FAIL2BAN_CONFIG_WRITE,
    AuditAction.FAIL2BAN_CONFIG_DELETE,
    AuditAction.SSH_ACCESS_PORT_CHANGE,
    AuditAction.SSH_ACCESS_ROOT_LOGIN,
    AuditAction.SSH_ACCESS_PASSWORD_AUTH,
    AuditAction.SSH_USER_CREATE,
    AuditAction.SSH_USER_DELETE,
    AuditAction.SSH_USER_GRANT_SUDO,
    AuditAction.SSH_USER_REVOKE_SUDO,
    AuditAction.SSH_KEY_ADD,
    AuditAction.SSH_KEY_REMOVE,
    AuditAction.SSH_ACCESS_USER_PASSWORD,
})

_DIRECT_SERVICE_SPECS: dict[tuple[str, str], DirectOperationSpec] = {
    ("wireguard", "do_add_profile"): DirectOperationSpec(
        "service.wireguard.profile_add", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("wireguard", "do_remove_profile"): DirectOperationSpec(
        "service.wireguard.profile_remove", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("wireguard", "do_toggle_profile"): DirectOperationSpec(
        "service.wireguard.profile_toggle", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("wireguard", "do_rename_profile"): DirectOperationSpec(
        "service.wireguard.profile_rename", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("wireguard", "do_reissue_profile"): DirectOperationSpec(
        "service.wireguard.profile_reissue", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("wireguard", "do_migrate"): DirectOperationSpec(
        "service.wireguard.migrate", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("wireguard", "do_reissue_all"): DirectOperationSpec(
        "service.wireguard.profile_reissue_all", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("wireguard", "set_endpoint"): DirectOperationSpec(
        "service.wireguard.endpoint_update", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("wireguard", "update_config"): DirectOperationSpec(
        "service.wireguard.config_update", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("docker", "save_stack_remote_file"): DirectOperationSpec(
        "service.docker.remote_file_write", "direct", AuditAction.SERVICE_FILE_WRITE,
    ),
    ("docker", "delete_stack_remote_file"): DirectOperationSpec(
        "service.docker.remote_file_delete", "direct", AuditAction.SERVICE_FILE_DELETE,
    ),
    ("3x-ui", "card_set_autostart"): DirectOperationSpec(
        "service.3x_ui.autostart_update", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("3x-ui", "card_change_username"): DirectOperationSpec(
        "service.3x_ui.username_update", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("3x-ui", "card_change_password"): DirectOperationSpec(
        "service.3x_ui.password_update", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("3x-ui", "card_change_port"): DirectOperationSpec(
        "service.3x_ui.port_update", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("3x-ui", "card_change_path"): DirectOperationSpec(
        "service.3x_ui.path_update", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("3x-ui", "card_reset_settings"): DirectOperationSpec(
        "service.3x_ui.settings_reset", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("3x-ui", "card_set_bbr"): DirectOperationSpec(
        "service.3x_ui.bbr_update", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
    ("3x-ui", "card_update_geo"): DirectOperationSpec(
        "service.3x_ui.geo_update", "direct", AuditAction.SERVICE_CONFIG_UPDATE,
    ),
}

_UNIT_ACTION_SPECS = {
    "start": DirectOperationSpec("service.3x_ui.start", "direct", AuditAction.SERVICE_START),
    "stop": DirectOperationSpec("service.3x_ui.stop", "direct", AuditAction.SERVICE_STOP),
    "restart": DirectOperationSpec("service.3x_ui.restart", "direct", AuditAction.SERVICE_RESTART),
    "restart_xray": DirectOperationSpec("service.3x_ui.restart", "direct", AuditAction.SERVICE_RESTART),
}

_active_operation_ids: contextvars.ContextVar[frozenset[str]] = contextvars.ContextVar(
    "operation_metric_ids", default=frozenset()
)
_active_direct_operation: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "direct_operation", default=None
)


def new_operation_id() -> str:
    return f"op-{uuid.uuid4().hex}"


def task_identity(task: Any) -> OperationIdentity | None:
    """Вернуть descriptor только для проверенных service-задач."""
    if str(getattr(task, "kind", "")) != "svc":
        return None
    payload = getattr(task, "payload", {}) or {}
    action = str(payload.get("action") or "")
    if action not in _SERVICE_TASK_ACTIONS:
        return None
    server_id = str(getattr(task, "server_id", "") or "")
    if not server_id:
        return None
    return OperationIdentity(
        operation_id=f"task-{task.id}",
        server_id=server_id,
        server_name=getattr(task, "server_name", None),
        scope=f"service.{action}",
    )


def quick_setup_identity(
    action: AuditAction,
    *,
    operation_id: str,
    server_id: Optional[str],
    server_name: Optional[str],
) -> OperationIdentity | None:
    """Разрешить только прочитанные QS facade-операции target-сервера."""
    if action not in _QUICK_SETUP_ACTIONS or not server_id:
        return None
    return OperationIdentity(
        operation_id=operation_id,
        server_id=str(server_id),
        server_name=server_name,
        scope=f"quick_setup.{action.value}",
    )


def reboot_identity(
    operation_id: str,
    *,
    server_id: Optional[str],
    server_name: Optional[str],
) -> OperationIdentity | None:
    if not operation_id or not server_id:
        return None
    return OperationIdentity(
        operation_id=str(operation_id),
        server_id=str(server_id),
        server_name=server_name,
        scope="server.reboot",
    )


def backup_identity(
    operation_id: str,
    *,
    server_id: Optional[str],
    server_name: Optional[str],
    scope: str,
) -> OperationIdentity | None:
    """Identity только для уже проверенной managed-server boundary."""
    if not operation_id or not server_id or scope not in {"backup.create", "backup.restore"}:
        return None
    return OperationIdentity(
        operation_id=str(operation_id),
        server_id=str(server_id),
        server_name=server_name,
        scope=scope,
    )


def direct_operation_spec(
    service_id: str,
    method: str,
    args: tuple[Any, ...],
) -> DirectOperationSpec | None:
    """Вернуть только вручную разрешённую direct remote-мутацию."""
    key = (str(service_id), str(method))
    if key == ("3x-ui", "card_unit_action"):
        params = args[0] if args else None
        action = str(params.get("action") or "") if isinstance(params, dict) else ""
        return _UNIT_ACTION_SPECS.get(action)
    spec = _DIRECT_SERVICE_SPECS.get(key)
    if spec is None:
        return None
    if key == ("wireguard", "set_endpoint"):
        endpoint = args[0] if args else None
        return spec if isinstance(endpoint, str) and bool(endpoint.strip()) else None
    if key == ("wireguard", "update_config"):
        endpoint = args[0] if len(args) > 0 else None
        port = args[1] if len(args) > 1 else None
        address = args[2] if len(args) > 2 else None
        dns = args[3] if len(args) > 3 else None
        changes_target = (
            port is not None
            or address is not None
            or dns is not None
            or (isinstance(endpoint, str) and bool(endpoint.strip()))
        )
        return spec if changes_target else None
    return spec


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _peak_score(metrics: dict) -> float | None:
    pressures: list[float] = []
    load1 = _finite(metrics.get("load1"))
    cpu_count = _finite(metrics.get("cpu_count"))
    if load1 is not None and cpu_count is not None and load1 >= 0 and cpu_count > 0:
        pressures.append(load1 / cpu_count)

    ram_used = _finite(metrics.get("ram_used_kb"))
    ram_total = _finite(metrics.get("ram_total_kb"))
    if ram_used is not None and ram_total is not None and ram_used >= 0 and ram_total > 0:
        pressures.append(100.0 * ram_used / ram_total)

    for disk in metrics.get("mounts") or ():
        used_pct = _finite((disk or {}).get("used_pct"))
        if used_pct is not None and used_pct >= 0:
            pressures.append(used_pct)
            continue
        used_kb = _finite((disk or {}).get("used_kb"))
        total_kb = _finite((disk or {}).get("total_kb"))
        if used_kb is not None and total_kb is not None and used_kb >= 0 and total_kb > 0:
            pressures.append(100.0 * used_kb / total_kb)

    return max(pressures) if pressures else None


class OperationMetricSession:
    """Sampler одного operation id; сохраняет новый реальный максимум сразу."""

    def __init__(
        self,
        identity: OperationIdentity,
        *,
        active: bool,
        token: contextvars.Token[frozenset[str]] | None,
    ) -> None:
        self.identity = identity
        self._active = active
        self._token = token
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._started = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> None:
        if not self._active:
            return
        with self._state_lock:
            if self._started or self._stop.is_set():
                return
            self._started = True
            self._thread = threading.Thread(
                target=self._sample_until_stopped,
                name=f"operation-metrics-{self.identity.operation_id[:24]}",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        if not self._active:
            return
        with self._state_lock:
            self._stop.set()

    def close(self) -> None:
        self.stop()
        if self._token is not None:
            _active_operation_ids.reset(self._token)
            self._token = None

    def _sample_until_stopped(self) -> None:
        while not self._stop.is_set():
            self._capture()
            if self._stop.wait(OPERATION_METRIC_INTERVAL_SECONDS):
                return

    def _capture(self) -> None:
        try:
            from core.servers import collect_server_metrics
            from core.storage import find_server

            server = find_server(self.identity.server_id)
            if not server:
                return
            outcome = collect_server_metrics(server)
            if str(outcome.get("status") or "") != "captured":
                return
            metrics = outcome.get("metrics") or {}
            severity = _peak_score(metrics)
            if severity is None:
                return
            captured_ts = int(time.time())
            peak = {
                "operation_id": self.identity.operation_id,
                "server_id": self.identity.server_id,
                "server_name": self.identity.server_name,
                "scope": self.identity.scope,
                "captured_ts": captured_ts,
                "severity": severity,
                "load1": metrics.get("load1"),
                "load5": metrics.get("load5"),
                "load15": metrics.get("load15"),
                "cpu_count": metrics.get("cpu_count"),
                "ram_used_kb": metrics.get("ram_used_kb"),
                "ram_total_kb": metrics.get("ram_total_kb"),
                "swap_used_kb": metrics.get("swap_used_kb"),
                "swap_total_kb": metrics.get("swap_total_kb"),
                "uptime_sec": metrics.get("uptime_sec"),
            }
            with self._state_lock:
                if self._stop.is_set():
                    return
                state_db.insert_operation_metric_peak(peak, disks=metrics.get("mounts") or ())
        except Exception:
            print("[OPERATION METRICS] peak collection failed", flush=True)


def begin(identity: OperationIdentity | None) -> OperationMetricSession | None:
    """Начать ownership; вложенный владелец того же op_id ничего не собирает."""
    if identity is None:
        return None
    active_ids = _active_operation_ids.get()
    if identity.operation_id in active_ids:
        return OperationMetricSession(identity, active=False, token=None)
    token = _active_operation_ids.set(active_ids | {identity.operation_id})
    return OperationMetricSession(identity, active=True, token=token)


class DirectOperationSession:
    """Лёгкий lifecycle direct mutation, активируемый только target marker-ом."""

    def __init__(self, identity: OperationIdentity, spec: DirectOperationSpec) -> None:
        self.identity = identity
        self.spec = spec
        self._metrics = begin(identity)
        self._started = False
        self._finished = False

    @property
    def started(self) -> bool:
        return self._started

    def mark_started(self) -> None:
        if self._started:
            return
        try:
            from core import audit

            audit.record(
                self.spec.audit_action,
                result=AuditResult.STARTED,
                server_id=self.identity.server_id,
                server_name=self.identity.server_name,
                op_id=self.identity.operation_id,
                params={"scope": self.spec.scope},
            )
        except Exception:
            pass
        self._started = True
        if self._metrics is not None:
            self._metrics.start()

    def finish(self, succeeded: bool) -> None:
        if not self._started or self._finished:
            return
        if self._metrics is not None:
            self._metrics.stop()
        try:
            from core import audit

            audit.record(
                self.spec.audit_action,
                result=AuditResult.OK if succeeded else AuditResult.FAILED,
                server_id=self.identity.server_id,
                server_name=self.identity.server_name,
                op_id=self.identity.operation_id,
                params={"scope": self.spec.scope},
            )
        except Exception:
            pass
        self._finished = True

    def close(self) -> None:
        if self._metrics is not None:
            self._metrics.close()


def create_direct_operation(
    spec: DirectOperationSpec | None,
    *,
    server_id: str,
) -> DirectOperationSession | None:
    if spec is None or not server_id:
        return None
    server_name = None
    try:
        from core.storage import find_server

        server = find_server(server_id)
        if server:
            server_name = server.get("name")
    except Exception:
        pass
    identity = OperationIdentity(
        operation_id=new_operation_id(),
        server_id=str(server_id),
        server_name=server_name,
        scope=spec.scope,
    )
    return DirectOperationSession(identity, spec)


def activate_direct_operation(
    operation: DirectOperationSession | None,
) -> contextvars.Token[Any]:
    return _active_direct_operation.set(operation)


def reset_direct_operation(token: contextvars.Token[Any]) -> None:
    _active_direct_operation.reset(token)


def mark_direct_mutation_started() -> None:
    operation = _active_direct_operation.get()
    if operation is not None:
        operation.mark_started()
