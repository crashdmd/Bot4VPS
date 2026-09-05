# -*- coding: utf-8 -*-
"""SSH / Доступ: чтение состояния и безопасные изменения.

Принцип: изменить на VPS → проверить SSH новым параметром → успех?
  да → обновить servers.json
  нет → откат / не трогать servers.json
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Optional

from core.ssh import create_ssh_client, exec_plain, exec_sudo
from core.storage import (
    ConnectionStateConflictError,
    compare_and_set_server_connection,
    get_server_connection_snapshot,
    load_servers,
    server_connection_snapshot,
)

from . import key_registry
from .models import OpResult, SshAccessStatus
from .package_manager import detect as detect_package_manager
from .remote_files import (
    RemoteFileSnapshot,
    atomic_write,
    restore_file,
    snapshot_file,
)

# Drop-in конфиг, чтобы не ломать весь sshd_config
_SSHD_DROPIN = "/etc/ssh/sshd_config.d/99-bot4vps.conf"
_SSHD_MAIN = "/etc/ssh/sshd_config"


def _keys_dir() -> Path:
    # В проде /opt/bot4vps/keys; в dev — рядом с установкой
    for candidate in (Path("/opt/bot4vps/keys"), Path(__file__).resolve().parents[2] / "keys"):
        if candidate.is_dir():
            return candidate
    return Path("/opt/bot4vps/keys")


def _read_sshd_setting(ssh, server: dict, key: str, exec_fn=None) -> Optional[str]:
    """Эффективное значение директивы sshd (drop-in + main)."""
    if exec_fn is None:
        exec_fn = exec_sudo
    # sshd -T даёт effective config (если доступен)
    code, out, _ = exec_fn(
        ssh,
        server,
        f"sshd -T 2>/dev/null | awk 'tolower($1)==tolower(\"{key}\"){{print $2; exit}}'",
        timeout=15,
    )
    val = (out or "").strip().splitlines()
    if code == 0 and val and val[0]:
        return val[0].strip()
    # fallback grep: побеждает первое вхождение (drop-in идёт раньше
    # основного конфига при стандартном Include в начале sshd_config)
    code2, out2, _ = exec_fn(
        ssh,
        server,
        f"grep -Ehi '^\\s*{re.escape(key)}\\s' {_SSHD_DROPIN} {_SSHD_MAIN} 2>/dev/null | head -1",
        timeout=10,
    )
    line = (out2 or "").strip().splitlines()
    if not line:
        return None
    parts = line[0].split(None, 1)
    return parts[1].strip() if len(parts) > 1 else None


def get_status(server: dict) -> SshAccessStatus:
    st = SshAccessStatus(
        user=server.get("user") or "—",
        port=int(server.get("port") or 22),
        # key_configured = прописан ли key_path текущего пользователя
        # в servers.json (маршрут Bot4VPS), а не наличие ключей у пользователя.
        key_configured=bool(server.get("key_path")),
        auth_type="key" if server.get("auth_type") == "key" else "password",
    )
    # Реестр ключей: записанный ключ маршрута используется на сервере ещё
    # кем-то (один ключ — один пользователь) — сообщаем, кем. Локальная
    # сверка по реестру, работает и при недоступном SSH.
    recorded_fp = _local_key_fingerprint(str(server.get("key_path") or ""))
    if recorded_fp:
        shared_owner = key_registry.find_owner(
            str(server.get("id") or ""),
            recorded_fp,
            exclude_user=str(server.get("user") or ""),
        )
        if shared_owner:
            st.key_shared_with = shared_owner
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=12)
        # sshd_config читается всем — при недоступном sudo работаем без него.
        exec_fn, _sudo_ok = _resolve_exec(ssh, server)
        st.sudo_capable = _sudo_ok
        port_s = _read_sshd_setting(ssh, server, "port", exec_fn=exec_fn)
        if port_s and port_s.isdigit():
            st.port = int(port_s)
        root = _read_sshd_setting(ssh, server, "permitrootlogin", exec_fn=exec_fn)
        if root:
            rl = root.lower()
            if rl in ("no", "prohibit-password", "without-password"):
                st.root_login = "Запрещён" if rl == "no" else "Только ключ"
            elif rl == "yes":
                st.root_login = "Разрешён"
            else:
                st.root_login = root
        else:
            st.root_login = "—"

        pwd = _read_sshd_setting(ssh, server, "passwordauthentication", exec_fn=exec_fn)
        if pwd:
            st.password_auth = "Разрешена" if pwd.lower() == "yes" else "Запрещена"
        else:
            st.password_auth = "—"

        # Честность key_path-статуса: при key-auth бот только что вошёл
        # этим ключом (он существует); при password-роуте проверяем наличие
        # публичной части в authorized_keys текущего пользователя (команды
        # идут в эту же сессию, без дополнительных подключений).
        if st.key_configured:
            if str(server.get("auth_type") or "") == "key":
                st.key_present = True
            else:
                st.key_present = _recorded_key_present_on_server(
                    ssh, server, exec_fn=exec_fn
                )

        return st
    except Exception as e:
        st.error = str(e)[:400]
        return st
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def _sshd_reload(ssh, server: dict) -> tuple[bool, str]:
    # /run/sshd может отсутствовать (контейнеры/LXC) — без него sshd -t
    # падает "missing privilege separation directory"; создаём идемпотентно.
    code, out, err = exec_sudo(
        ssh,
        server,
        "[ -d /run/sshd ] || install -d -m 755 /run/sshd; sshd -t",
        timeout=15,
    )
    if code != 0:
        return False, (err or out or "sshd -t failed")[:500]
    # Socket-activated sshd (Debian/Ubuntu по умолчанию с systemd.io socket
    # activation): systemd передаёт sshd уже открытый listener, директивы Port
    # из sshd_config при этом игнорируются, а SIGHUP- reload падает
    # "Cannot bind any address" (порт занят ssh.socket). Для применяемых
    # sshd_config-изменений достаточно reload/распространения сессий:
    # слушающие порты при socket activation задаёт ssh.socket, и port-change
    # flow синхронизирует его отдельно (_socket_listen_ports).
    code2, out2, err2 = exec_sudo(
        ssh,
        server,
        "systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || "
        "service ssh reload 2>/dev/null || service sshd reload 2>/dev/null",
        timeout=20,
    )
    if code2 != 0 and not _socket_activated(ssh, server):
        return False, (err2 or out2 or "reload failed")[:500]
    time.sleep(1.0)
    return True, "sshd reloaded"


def _socket_activated(ssh, server: dict) -> bool:
    """Активен ли systemd socket activation для sshd."""
    code, out, _ = exec_sudo(
        ssh,
        server,
        "systemctl is-active ssh.socket 2>/dev/null || "
        "systemctl is-active sshd.socket 2>/dev/null",
        timeout=10,
    )
    return code == 0


_SSHD_SOCKET = "/etc/systemd/system/ssh.socket.d/99-bot4vps-port.conf"


def _socket_listen_ports(ssh, server: dict, ports: list[int]) -> None:
    """Синхронизировать ListenStream ssh.socket с целевыми портами.

    Первый пустой ``ListenStream=`` сбрасывает port из базового unit; далее
    перечисляются все нужные. Порт из sshd_config при socket activation
    игнорируется, поэтому слушающие порты задаёт только этот drop-in.
    """
    lines = ["# Managed by Bot4VPS Quick Setup", "[Socket]", "ListenStream="]
    lines.extend(f"ListenStream={int(port)}" for port in ports)
    body = "\n".join(lines) + "\n"
    payload = base64.b64encode(body.encode("utf-8")).decode("ascii")
    q_dir = shlex.quote("/etc/systemd/system/ssh.socket.d")
    q_path = shlex.quote(_SSHD_SOCKET)
    command = (
        f"install -d -m 755 {q_dir} && "
        f"printf %s {shlex.quote(payload)} | base64 -d > {q_path} && "
        "systemctl daemon-reload && "
        "systemctl stop ssh.service 2>/dev/null || true; "
        "systemctl restart ssh.socket 2>/dev/null || "
        "systemctl restart sshd.socket 2>/dev/null"
    )
    code, out, err = exec_sudo(ssh, server, command, timeout=30)
    if code != 0:
        raise RuntimeError((err or out or f"ssh.socket restart exit {code}")[:500])
    time.sleep(1.0)


def _socket_clear_listen_ports(ssh, server: dict) -> None:
    """Удалить managed drop-in ssh.socket и вернуть базовый ListenStream."""
    q_path = shlex.quote(_SSHD_SOCKET)
    command = (
        f"rm -f -- {q_path} && "
        "systemctl daemon-reload && "
        "systemctl stop ssh.service 2>/dev/null || true; "
        "systemctl restart ssh.socket 2>/dev/null || "
        "systemctl restart sshd.socket 2>/dev/null"
    )
    code, out, err = exec_sudo(ssh, server, command, timeout=30)
    if code != 0:
        raise RuntimeError((err or out or f"ssh.socket restore exit {code}")[:500])
    time.sleep(1.0)



def _dropin_with_ports(snapshot: RemoteFileSnapshot, ports: list[int]) -> str:
    """Сохранить drop-in, заменив только глобальные директивы Port."""
    try:
        text = snapshot.content.decode("utf-8") if snapshot.existed else ""
    except UnicodeDecodeError as exc:
        raise RuntimeError("SSH drop-in имеет неподдерживаемую кодировку") from exc

    before_match: list[str] = []
    match_and_after: list[str] = []
    in_match = False
    for raw in text.splitlines():
        effective = raw.split("#", 1)[0].strip()
        parts = effective.split(None, 1)
        directive = parts[0].lower() if parts else ""
        if directive == "match":
            in_match = True
        if not in_match and directive == "port":
            continue
        (match_and_after if in_match else before_match).append(raw)

    if not before_match and not match_and_after:
        before_match = ["# Managed by Bot4VPS Quick Setup"]
    while before_match and not before_match[-1].strip():
        before_match.pop()
    before_match.extend(["", *(f"Port {int(port)}" for port in ports)])
    lines = before_match + ([""] if match_and_after else []) + match_and_after
    return "\n".join(lines).rstrip() + "\n"


def _write_ports(
    ssh,
    server: dict,
    snapshot: RemoteFileSnapshot,
    ports: list[int],
) -> None:
    atomic_write(
        ssh,
        server,
        snapshot.path,
        _dropin_with_ports(snapshot, ports),
        mode=snapshot.mode if snapshot.existed else 0o644,
        uid=snapshot.uid if snapshot.existed else None,
        gid=snapshot.gid if snapshot.existed else None,
    )


def _verify_candidate(server: dict, port: int, *, attempts: int = 3) -> tuple[bool, str]:
    """Подтвердить настоящий SSH login и рабочий privileged-контекст."""
    candidate = {**server, "port": int(port)}
    last_error = ""
    for attempt in range(attempts):
        if attempt:
            time.sleep(1.5)
        ssh = None
        try:
            ssh = create_ssh_client(candidate, timeout=15)
            code, out, err = exec_sudo(ssh, candidate, "true", timeout=15)
            if code == 0:
                return True, "SSH login и sudo подтверждены"
            last_error = (err or out or f"sudo exit {code}")[:500]
        except Exception as exc:
            last_error = str(exc)[:500]
        finally:
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass
    return False, last_error or "SSH login не подтверждён"


def _port_listening(ssh, server: dict, port: int) -> tuple[Optional[bool], str]:
    """Проверить TCP listener; None означает, что проверка недоступна."""
    command = (
        "if command -v ss >/dev/null 2>&1; then ss -H -ltn; "
        "elif command -v netstat >/dev/null 2>&1; then netstat -ltn; "
        "else exit 3; fi | "
        f"awk '{{a=$4; sub(/^.*:/, \"\", a); if (a==\"{int(port)}\") found=1}} "
        "END {exit found ? 0 : 1}'"
    )
    code, out, err = exec_sudo(ssh, server, command, timeout=15)
    if code == 0:
        return True, "порт слушается"
    if code == 1:
        return False, "порт не слушается"
    return None, (err or out or "ss/netstat недоступен")[:500]


def _restore_original_sshd(
    control_ssh,
    server: dict,
    snapshot: RemoteFileSnapshot,
    old_port: int,
    new_port: int,
) -> dict:
    """Вернуть exact snapshot и доказать рабочий старый доступ."""
    restored = False
    restore_error = ""
    fallback_ssh = None
    sessions = [control_ssh] if control_ssh is not None else []
    try:
        fallback_ssh = create_ssh_client({**server, "port": old_port}, timeout=15)
        if fallback_ssh is not control_ssh:
            sessions.append(fallback_ssh)
    except Exception as exc:
        restore_error = str(exc)[:500]

    for session in sessions:
        try:
            restore_file(session, server, snapshot)
            if _socket_activated(session, server):
                _socket_clear_listen_ports(session, server)
            ok, detail = _sshd_reload(session, server)
            if not ok:
                raise RuntimeError(detail)
            restored = True
            restore_error = ""
            break
        except Exception as exc:
            restore_error = str(exc)[:500]

    old_login, old_error = _verify_candidate(server, old_port)
    listening: Optional[bool] = None
    listening_detail = "Проверка listener не выполнена"
    for session in sessions:
        try:
            listening, listening_detail = _port_listening(session, server, new_port)
            if listening is not None:
                break
        except Exception as exc:
            listening_detail = str(exc)[:500]

    if fallback_ssh:
        try:
            fallback_ssh.close()
        except Exception:
            pass
    return {
        "restored": restored,
        "restore_error": restore_error or None,
        "old_login_verified": old_login,
        "old_login_error": None if old_login else old_error,
        "new_port_listening": listening,
        "listener_detail": listening_detail,
        "complete": restored and old_login and listening is False,
    }


def _firewall_cleanup_after_rollback(
    firewall_mod,
    control_ssh,
    server: dict,
    mutation,
    rollback: dict,
) -> dict:
    """Убрать только новое exact allow после доказанного полного отката."""
    if mutation is None:
        return {"attempted": False, "ok": True, "reason": "firewall_noop"}
    children = list(getattr(mutation, "mutations", []) or [])
    if children:
        results = [
            _firewall_cleanup_after_rollback(
                firewall_mod,
                control_ssh,
                server,
                child,
                rollback,
            )
            for child in children
        ]
        return {
            "attempted": any(item.get("attempted") for item in results),
            "ok": all(item.get("ok") for item in results),
            "rule_retained": any(item.get("rule_retained") for item in results),
            "backends": results,
        }
    if not mutation.changed or mutation.existed_before:
        return {
            "attempted": False,
            "ok": True,
            "reason": "preexisting_or_unchanged",
            "rule_retained": bool(mutation.existed_before),
        }
    if not rollback.get("complete"):
        return {
            "attempted": False,
            "ok": False,
            "reason": "rollback_not_fully_verified",
            "rule_retained": True,
        }

    cleanup_ssh = control_ssh
    close_after = False
    try:
        if cleanup_ssh is None:
            cleanup_ssh = create_ssh_client(server, timeout=15)
            close_after = True
        result = firewall_mod.cleanup_mutation_on_ssh(
            cleanup_ssh,
            server,
            mutation,
        )
        cleaned = bool(result.ok and result.verified)
        return {
            "attempted": True,
            "ok": cleaned,
            "rule_retained": not cleaned,
            "mutation": result.to_dict(),
        }
    except Exception as exc:
        return {
            "attempted": True,
            "ok": False,
            "rule_retained": True,
            "error": str(exc)[:500],
        }
    finally:
        if close_after and cleanup_ssh:
            try:
                cleanup_ssh.close()
            except Exception:
                pass


def _port_failure(
    *,
    message: str,
    error: str,
    old_port: int,
    new_port: int,
    firewall_open,
    rollback: Optional[dict] = None,
    cleanup: Optional[dict] = None,
    extra: Optional[dict] = None,
) -> OpResult:
    mutations = list(getattr(firewall_open, "mutations", []) or [])
    new_rule_retained = bool(
        (
            firewall_open is not None
            and firewall_open.changed
            and not firewall_open.existed_before
        )
        or any(item.changed and not item.existed_before for item in mutations)
    ) and (cleanup is None or cleanup.get("rule_retained", True))
    if new_rule_retained:
        message = f"{message}. Новый порт {new_port} оставлен открытым для повторной попытки"
    data = {
        "old_port": old_port,
        "new_port": new_port,
        "rollback": rollback,
        "firewall": {
            "open": firewall_open.to_dict() if firewall_open is not None else None,
            "cleanup": cleanup,
            "new_rule_retained": new_rule_retained,
        },
    }
    if extra:
        data.update(extra)
    return OpResult(
        ok=False,
        message=message,
        error=str(error or "")[:1000] or None,
        data=data,
    )


def change_port(
    server: dict,
    new_port: int,
    *,
    acknowledge_firewall_conflict: bool = False,
) -> OpResult:
    """Мигрировать SSH-порт с проверяемым firewall и CAS-персистентностью."""
    try:
        new_port = int(new_port)
    except (TypeError, ValueError):
        return OpResult(ok=False, message="Порт 1–65535", error="bad_port")
    if not 1 <= new_port <= 65535:
        return OpResult(ok=False, message="Порт 1–65535", error="bad_port")

    server_id = str(server.get("id") or "")
    if not server_id:
        return OpResult(ok=False, message="Сервер не найден", error="missing_server_id")
    try:
        local = get_server_connection_snapshot(server_id)
    except Exception as exc:
        return OpResult(ok=False, message="Сервер не найден", error=str(exc)[:500])
    working_server = local["server"]
    expected_connection = local["connection"]
    old_port = int(working_server.get("port") or 22)
    if new_port == old_port:
        return OpResult(
            ok=True,
            message="Порт уже установлен",
            data={"port": new_port, "old_port": old_port, "new_port": new_port},
        )

    from . import firewall as firewall_mod

    control_ssh = None
    snapshot = None
    firewall_open = None
    firewall_info = None
    committed = None
    old_close_preflight = None
    old_close = None
    old_close_attempted = False
    stage = "connect"
    try:
        # Управляющая сессия на старом порту живёт до финальной проверки.
        control_ssh = create_ssh_client(working_server, timeout=15)

        stage = "firewall_preflight"
        try:
            active_firewalls, _ = firewall_mod.active_backends_on_ssh(
                control_ssh, working_server
            )
        except firewall_mod.FirewallDetectionError as exc:
            return _port_failure(
                message="Смена SSH-порта остановлена: состояние firewall не определено",
                error=str(exc),
                old_port=old_port,
                new_port=new_port,
                firewall_open=None,
            )
        if len(active_firewalls) > 1 and not acknowledge_firewall_conflict:
            return _port_failure(
                message=(
                    "Смена SSH-порта остановлена: обнаружено несколько активных "
                    "firewall; требуется явное подтверждение"
                ),
                error="ambiguous_active_firewalls",
                old_port=old_port,
                new_port=new_port,
                firewall_open=None,
                extra={
                    "backends": [backend.name for backend, _ in active_firewalls]
                },
            )
        firewall_info = firewall_mod.detect_on_ssh(control_ssh, working_server)
        if active_firewalls:
            old_close_preflight = firewall_mod.preflight_close_port_on_ssh(
                control_ssh,
                working_server,
                old_port,
                "tcp",
                protect_current_ssh=False,
                acknowledge_firewall_conflict=acknowledge_firewall_conflict,
            )
            if not old_close_preflight.ok or not old_close_preflight.verified:
                return _port_failure(
                    message="Старый SSH-порт нельзя закрыть отдельным безопасным правилом",
                    error=old_close_preflight.error or old_close_preflight.message,
                    old_port=old_port,
                    new_port=new_port,
                    firewall_open=None,
                    extra={"old_close_preflight": old_close_preflight.to_dict()},
                )
            firewall_open = firewall_mod.open_port_on_ssh(
                control_ssh,
                working_server,
                new_port,
                "tcp",
                acknowledge_firewall_conflict=acknowledge_firewall_conflict,
            )
            if not firewall_open.ok or not firewall_open.verified:
                old_login, old_login_error = _verify_candidate(working_server, old_port)
                new_listener, listener_detail = _port_listening(
                    control_ssh, working_server, new_port
                )
                rollback = {
                    "restored": True,
                    "old_login_verified": old_login,
                    "old_login_error": None if old_login else old_login_error,
                    "new_port_listening": new_listener,
                    "listener_detail": listener_detail,
                    "complete": old_login and new_listener is False,
                }
                cleanup = _firewall_cleanup_after_rollback(
                    firewall_mod,
                    control_ssh,
                    working_server,
                    firewall_open,
                    rollback,
                )
                return _port_failure(
                    message="Не удалось открыть и проверить новый порт во всех firewall",
                    error=firewall_open.error or firewall_open.message,
                    old_port=old_port,
                    new_port=new_port,
                    firewall_open=firewall_open,
                    rollback=rollback,
                    cleanup=cleanup,
                )

        stage = "snapshot_sshd"
        code, out, err = exec_sudo(
            control_ssh,
            working_server,
            "[ ! -L /etc/ssh/sshd_config.d ] && "
            "install -d -m 755 /etc/ssh/sshd_config.d",
            timeout=15,
        )
        if code != 0:
            raise RuntimeError(err or out or "Не удалось подготовить sshd_config.d")
        snapshot = snapshot_file(control_ssh, working_server, _SSHD_DROPIN)

        stage = "dual_port"
        _write_ports(control_ssh, working_server, snapshot, [old_port, new_port])
        socket_ports = [old_port, new_port] if _socket_activated(
            control_ssh, working_server
        ) else None
        if socket_ports is not None:
            _socket_listen_ports(control_ssh, working_server, socket_ports)
        ok, detail = _sshd_reload(control_ssh, working_server)
        if not ok:
            raise RuntimeError(detail)
        old_listening, old_listener_detail = _port_listening(
            control_ssh, working_server, old_port
        )
        new_listening, new_listener_detail = _port_listening(
            control_ssh, working_server, new_port
        )
        if old_listening is not True or new_listening is not True:
            raise RuntimeError(
                "Не подтверждено одновременное прослушивание старого и нового "
                f"портов: old={old_listener_detail}; new={new_listener_detail}"
            )

        stage = "verify_dual_port"
        new_login, new_error = _verify_candidate(working_server, new_port)
        if not new_login:
            rollback = _restore_original_sshd(
                control_ssh, working_server, snapshot, old_port, new_port
            )
            cleanup = _firewall_cleanup_after_rollback(
                firewall_mod,
                control_ssh,
                working_server,
                firewall_open,
                rollback,
            )
            return _port_failure(
                message=(
                    "SSH на новом порту не подтверждён — выполнен полный откат"
                    if rollback["complete"]
                    else "SSH на новом порту не подтверждён; откат подтверждён не полностью"
                ),
                error=new_error,
                old_port=old_port,
                new_port=new_port,
                firewall_open=firewall_open,
                rollback=rollback,
                cleanup=cleanup,
            )

        stage = "new_port_only"
        _write_ports(control_ssh, working_server, snapshot, [new_port])
        if socket_ports is not None:
            _socket_listen_ports(control_ssh, working_server, [new_port])
        ok, detail = _sshd_reload(control_ssh, working_server)
        if not ok:
            raise RuntimeError(detail)
        old_listening, old_listener_detail = _port_listening(
            control_ssh, working_server, old_port
        )
        new_listening, new_listener_detail = _port_listening(
            control_ssh, working_server, new_port
        )
        if old_listening is not False or new_listening is not True:
            raise RuntimeError(
                "Не подтверждена конфигурация только нового SSH-порта; "
                "проверьте другие директивы Port: "
                f"old={old_listener_detail}; new={new_listener_detail}"
            )

        stage = "verify_new_only"
        new_login, new_error = _verify_candidate(working_server, new_port)
        if not new_login:
            rollback = _restore_original_sshd(
                control_ssh, working_server, snapshot, old_port, new_port
            )
            cleanup = _firewall_cleanup_after_rollback(
                firewall_mod,
                control_ssh,
                working_server,
                firewall_open,
                rollback,
            )
            return _port_failure(
                message=(
                    "Финальная конфигурация нового порта не подтверждена — выполнен полный откат"
                    if rollback["complete"]
                    else "Финальная конфигурация нового порта не подтверждена; нужен ручной контроль доступа"
                ),
                error=new_error,
                old_port=old_port,
                new_port=new_port,
                firewall_open=firewall_open,
                rollback=rollback,
                cleanup=cleanup,
            )

        stage = "commit_connection"
        committed = compare_and_set_server_connection(
            server_id,
            {"port": new_port},
            expected_connection=expected_connection,
        )
        committed_connection = server_connection_snapshot(committed)
        working_new = {**working_server, "port": new_port}

        def recover_after_commit(reason: str, technical_error: str) -> OpResult:
            old_reopen = None
            if active_firewalls and old_close_attempted:
                try:
                    old_reopen = firewall_mod.open_port_on_ssh(
                        control_ssh,
                        working_new,
                        old_port,
                        "tcp",
                        acknowledge_firewall_conflict=acknowledge_firewall_conflict,
                    )
                except Exception as exc:
                    old_reopen = {"error": str(exc)[:500]}
            rollback = _restore_original_sshd(
                control_ssh, working_server, snapshot, old_port, new_port
            )
            local_rollback = {"attempted": False, "ok": False}
            if rollback.get("restored") and rollback.get("old_login_verified"):
                local_rollback["attempted"] = True
                try:
                    reverted = compare_and_set_server_connection(
                        server_id,
                        {"port": old_port},
                        expected_connection=committed_connection,
                    )
                    local_rollback.update({
                        "ok": True,
                        "port": int(reverted.get("port") or 22),
                    })
                except Exception as exc:
                    local_rollback["error"] = str(exc)[:500]
            rollback["local_connection"] = local_rollback
            fully_recovered = rollback.get("complete") and local_rollback.get("ok")
            cleanup_basis = dict(rollback)
            cleanup_basis["complete"] = bool(fully_recovered)
            cleanup = _firewall_cleanup_after_rollback(
                firewall_mod,
                control_ssh,
                working_server,
                firewall_open,
                cleanup_basis,
            )
            reopen_data = (
                old_reopen.to_dict() if hasattr(old_reopen, "to_dict") else old_reopen
            )
            return _port_failure(
                message=(
                    f"{reason} — исходный порт восстановлен"
                    if fully_recovered
                    else f"{reason} — восстановление завершено не полностью"
                ),
                error=technical_error,
                old_port=old_port,
                new_port=new_port,
                firewall_open=firewall_open,
                rollback=rollback,
                cleanup=cleanup,
                extra={"old_firewall_reopen": reopen_data},
            )

        stage = "close_old_firewall"
        if active_firewalls:
            old_close_attempted = True
            try:
                old_close = firewall_mod.close_port_on_ssh(
                    control_ssh,
                    working_new,
                    old_port,
                    "tcp",
                    protect_current_ssh=False,
                    acknowledge_firewall_conflict=acknowledge_firewall_conflict,
                )
            except Exception as exc:
                return recover_after_commit(
                    "При закрытии старого firewall-правила произошла ошибка",
                    str(exc)[:1000],
                )
            if not old_close.ok or not old_close.verified:
                return recover_after_commit(
                    "Старое firewall-правило не удалось закрыть безопасно",
                    old_close.error or old_close.message,
                )

        stage = "final_login"
        final_login, final_error = _verify_candidate(working_new, new_port)
        if not final_login:
            return recover_after_commit(
                "Финальный SSH-вход после закрытия старого порта не подтверждён",
                final_error,
            )

        return OpResult(
            ok=True,
            message=f"SSH-порт изменён: {old_port} → {new_port}",
            data={
                "port": new_port,
                "old_port": old_port,
                "new_port": new_port,
                "server": {"id": committed.get("id"), "port": new_port},
                "login_verified": True,
                "firewall": {
                    "backend": (
                        firewall_info.backend
                        if firewall_info and len(active_firewalls) <= 1
                        else None
                    ),
                    "backends": [
                        backend.name for backend, _ in active_firewalls
                    ],
                    "open": firewall_open.to_dict() if firewall_open else None,
                    "old_close_preflight": (
                        old_close_preflight.to_dict() if old_close_preflight else None
                    ),
                    "old_close": old_close.to_dict() if old_close else None,
                    "new_rule_retained": False,
                },
            },
        )
    except ConnectionStateConflictError as exc:
        rollback = (
            _restore_original_sshd(
                control_ssh, working_server, snapshot, old_port, new_port
            )
            if control_ssh is not None and snapshot is not None
            else {"complete": False, "restore_error": "snapshot недоступен"}
        )
        cleanup = _firewall_cleanup_after_rollback(
            firewall_mod,
            control_ssh,
            working_server,
            firewall_open,
            rollback,
        )
        return _port_failure(
            message="SSH-настройки были параллельно изменены; операция отменена",
            error=str(exc),
            old_port=old_port,
            new_port=new_port,
            firewall_open=firewall_open,
            rollback=rollback,
            cleanup=cleanup,
            extra={"stage": stage},
        )
    except Exception as exc:
        rollback = None
        cleanup = None
        if control_ssh is not None and snapshot is not None and committed is None:
            if socket_ports is not None:
                try:
                    _socket_clear_listen_ports(control_ssh, working_server)
                except Exception as socket_exc:
                    raise RuntimeError(
                        f"Откат ssh.socket не выполнен: {socket_exc}"
                    ) from exc
            rollback = _restore_original_sshd(
                control_ssh, working_server, snapshot, old_port, new_port
            )
            cleanup = _firewall_cleanup_after_rollback(
                firewall_mod,
                control_ssh,
                working_server,
                firewall_open,
                rollback,
            )
        return _port_failure(
            message="Ошибка смены SSH-порта",
            error=str(exc),
            old_port=old_port,
            new_port=new_port,
            firewall_open=firewall_open,
            rollback=rollback,
            cleanup=cleanup,
            extra={"stage": stage},
        )
    finally:
        if control_ssh:
            try:
                control_ssh.close()
            except Exception:
                pass


def _valid_username(username: str) -> str:
    value = str(username or "").strip()
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", value):
        raise ValueError("Некорректное имя пользователя")
    return value


def _fresh_server(server: dict) -> tuple[dict, dict]:
    server_id = str(server.get("id") or "").strip()
    if not server_id:
        raise ValueError("Сервер не найден")
    local = get_server_connection_snapshot(server_id)
    return local["server"], local["connection"]


def _probe_login_and_sudo(candidate: dict) -> tuple[bool, bool, str]:
    """Реальный SSH-вход кандидатом через core.ssh и обязательный sudo после.

    Возвращает (login_ok, sudo_ok, error). Наличие соединения само по себе
    не считается успехом: sudo подтверждается отдельной командой.
    """
    ssh = None
    try:
        ssh = create_ssh_client(candidate, timeout=15)
    except Exception as exc:
        return False, False, str(exc)[:500]
    try:
        code, out, err = exec_sudo(ssh, candidate, "true", timeout=15)
        if code != 0:
            return True, False, (err or out or f"sudo exit {code}")[:500]
        return True, True, ""
    except Exception as exc:
        return True, False, str(exc)[:500]
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def _verify_login_and_sudo(candidate: dict) -> tuple[bool, str]:
    """Подтвердить настоящий SSH-вход и usable sudo для кандидата."""
    login_ok, sudo_ok, error = _probe_login_and_sudo(candidate)
    if login_ok and sudo_ok:
        return True, "SSH-вход и sudo подтверждены"
    return False, error


def _sudo_confirmed(ssh, server: dict) -> bool:
    """Работает ли sudo у текущего пользователя Bot4VPS (root — всегда)."""
    if (str(server.get("user") or "").lower()) == "root":
        return True
    try:
        code, _, _ = exec_sudo(ssh, server, "true", timeout=15)
    except Exception:
        return False
    return code == 0


def _target_id_info(ssh, candidate: dict) -> Optional[dict]:
    """uid/группы цели в уже открытом сеансе (exec_plain, без sudo).

    Возвращает ``{"sudo_capable": bool, "is_root": bool}`` или None —
    проверить не удалось (гейт не применяется, решение остаётся за общим
    подтверждением sudo_not_verified).
    """
    try:
        code, out, err = exec_plain(ssh, candidate, "id -u; echo ---; id -Gn", timeout=15)
        if code != 0:
            return None
    except Exception:
        return None
    lines = (out or "").splitlines()
    uid_line = next((ln.strip() for ln in lines[:1] if ln.strip()), "")
    groups = set(lines[2].split()) if len(lines) >= 3 and lines[1].strip() == "---" else set()
    is_root = uid_line == "0"
    return {
        "sudo_capable": is_root or "sudo" in groups or "wheel" in groups,
        "is_root": is_root,
    }


def _verify_target(
    candidate: dict,
    *,
    collect_info: bool = False,
) -> tuple[bool, bool, Optional[dict], Optional[str]]:
    """Проверка цели одним SSH-соединением: вход, sudo и uid/группы.

    Соединение к целевому пользователю устанавливается ОДИН раз и
    используется для всех проверок этой же авторизации (sudo-проба и,
    при ``collect_info``, чтение id для sudo-gate) — без повторного
    handshake/login к той же цели.

    Возвращает (login_ok, sudo_ok, target_info, error). Наличие
    соединения само по себе не считается успехом: sudo подтверждается
    отдельной командой. target_info — ``{"sudo_capable", "is_root"}``
    или None (не запрашивался / не удалось прочитать). Пароль root
    здесь не проверяется: sudo-проба root пароль не проверяет, поэтому
    switch_user проверяет его отдельным реальным password-входом.
    """
    ssh = None
    try:
        ssh = create_ssh_client(candidate, timeout=15)
    except Exception as exc:
        return False, False, None, str(exc)[:500]
    try:
        sudo_ok = False
        error = ""
        try:
            code, out, err = exec_sudo(ssh, candidate, "true", timeout=15)
            if code == 0:
                sudo_ok = True
            else:
                error = (err or out or f"sudo exit {code}")[:500]
        except Exception as exc:
            error = str(exc)[:500]
        target_info = _target_id_info(ssh, candidate) if collect_info else None
        return True, sudo_ok, target_info, error
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def _resolve_exec(ssh, server: dict) -> tuple[Callable[..., tuple], bool]:
    """Команды через sudo, если sudo подтверждён; иначе — без sudo.

    Возвращает (исполнитель, sudo_ok). sudo_ok также управляет chown:
    без sudo менять владельца файлов нельзя (и не нужно — свои файлы уже
    принадлежат пользователю). Привилегированные операции (sshd, чужие
    домашние каталоги) при sudo_ok=False честно падают с отказом доступа.
    """
    if _sudo_confirmed(ssh, server):
        return exec_sudo, True
    return exec_plain, False


def _verify_login_and_optional_sudo(candidate: dict, require_sudo: bool) -> tuple[bool, str]:
    """Реальный SSH-вход; sudo обязателен, только если был доступен до этого."""
    if require_sudo:
        return _verify_login_and_sudo(candidate)
    login_ok, _, error = _probe_login_and_sudo(candidate)
    return (login_ok, "SSH-вход подтверждён" if login_ok else error)


def _account(ssh, server: dict, username: str, exec_fn=None) -> Optional[dict]:
    if exec_fn is None:
        exec_fn = exec_sudo
    username = _valid_username(username)
    code, out, err = exec_fn(
        ssh,
        server,
        f"getent passwd -- {shlex.quote(username)} | head -n 1 | cut -c1-2048",
        timeout=15,
    )
    line = (out or "").strip().splitlines()
    if code != 0:
        # Команда не выполнилась (например, sudo недоступен текущему
        # пользователю) — это не то же самое, что отсутствие записи.
        raise RuntimeError((err or out or f"exit {code}")[:500])
    if not line:
        return None
    parts = line[0].split(":")
    if len(parts) < 7 or parts[0] != username:
        return None
    try:
        uid = int(parts[2])
        gid = int(parts[3])
    except ValueError:
        return None
    home = parts[5][:512]
    shell = parts[6][:256]
    login_capable = bool(
        home.startswith("/")
        and shell.startswith("/")
        and not re.search(r"(?:nologin|false|sync|shutdown|halt)$", shell)
    )
    return {
        "username": username,
        "uid": uid,
        "gid": gid,
        "home": home,
        "shell": shell,
        "login_capable": login_capable,
    }


def list_users(server: dict) -> OpResult:
    """Вернуть bounded список реальных локальных аккаунтов без секретов."""
    ssh = None
    try:
        working, _ = _fresh_server(server)
        ssh = create_ssh_client(working, timeout=15)
        # getent/id читаются всем — при недоступном sudo работаем без него.
        exec_fn, _sudo_ok = _resolve_exec(ssh, working)
        code, out, err = exec_fn(
            ssh,
            working,
            "getent passwd | awk -F: '($3 == 0 || $3 >= 1000) "
            "{print substr($1,1,64) \"\\t\" $3 \"\\t\" $4 \"\\t\" "
            "substr($6,1,512) \"\\t\" substr($7,1,256)}' | head -n 200",
            timeout=20,
        )
        if code != 0:
            return OpResult(
                ok=False,
                message="Не удалось получить список пользователей",
                error=(err or out or f"exit {code}")[:800],
            )

        current = str(working.get("user") or "")
        users: list[dict] = []
        for raw in (out or "").splitlines()[:200]:
            parts = raw.split("\t")
            if len(parts) != 5:
                continue
            username, uid_raw, gid_raw, home, shell = parts
            try:
                username = _valid_username(username)
                uid = int(uid_raw)
                gid = int(gid_raw)
            except (ValueError, TypeError):
                continue
            # Отображение: nobody и подобные uid>=60000 (резервный диапазон,
            # 65534 nobody/nfsnobody) не показываем — туда всё равно не зайти.
            # Учётную запись на сервере это не трогает.
            if 60000 <= uid:
                continue
            login_capable = bool(
                home.startswith("/")
                and shell.startswith("/")
                and not re.search(r"(?:nologin|false|sync|shutdown|halt)$", shell)
            )
            code_g, groups_out, _ = exec_fn(
                ssh,
                working,
                f"id -nG -- {shlex.quote(username)} 2>/dev/null | cut -c1-1024",
                timeout=10,
            )
            groups = (groups_out or "").strip().split() if code_g == 0 else []
            sudo_group = uid == 0 or bool({"sudo", "wheel", "admin"} & set(groups))
            if uid == 0:
                sudo_capable: Optional[bool] = True
            else:
                sudo_capable = _sudo_privilege_listing_ok(ssh, working, username)
            protected_reason = None
            if username == "root" or uid == 0:
                protected_reason = "Системный суперпользователь"
            elif username == current:
                protected_reason = "Текущий пользователь Bot4VPS"
            elif uid < 1000:
                protected_reason = "Системная учётная запись"
            elif not login_capable:
                protected_reason = "Вход через SSH отключён shell-политикой"
            users.append({
                "username": username,
                "uid": uid,
                "gid": gid,
                "home": home[:512],
                "shell": shell[:256],
                "login_capable": login_capable,
                "sudo_group": sudo_group,
                "sudo_capable": sudo_capable,
                "current": username == current,
                "can_delete": protected_reason is None,
                "protected_reason": protected_reason,
            })
        # Смена пароля root (когда root не активный пользователь) возможна
        # только при рабочем root-парольном входе по SSH: старый пароль и
        # новый проверяются реальным логином.
        pwd_auth = (_read_sshd_setting(ssh, working, "passwordauthentication", exec_fn=exec_fn) or "")
        permit_root = (_read_sshd_setting(ssh, working, "permitrootlogin", exec_fn=exec_fn) or "")
        root_pw_change = pwd_auth.strip().lower() == "yes" and permit_root.strip().lower() == "yes"
        return OpResult(
            ok=True,
            message=f"Пользователей: {len(users)}",
            data={
                "users": users,
                "current_user": current,
                "root_password_change": root_pw_change,
            },
        )
    except Exception as exc:
        return OpResult(
            ok=False,
            message="Ошибка получения пользователей",
            error=str(exc)[:800],
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def _sudo_binary_available(ssh, server: dict) -> bool:
    code, _, _ = exec_sudo(ssh, server, "command -v sudo >/dev/null 2>&1", timeout=15)
    return code == 0


def _ensure_sudo_installed(ssh, server: dict) -> bool:
    """Установить пакет sudo, если binary отсутствует.

    Группа sudo при этом может существовать и без пакета — членство в ней
    ничего не даёт, поэтому установка идёт до выдачи прав.
    Возвращает True, если пакет был установлен этой операцией.
    """
    if _sudo_binary_available(ssh, server):
        return False
    manager = detect_package_manager(ssh, server)
    ok, message = manager.install(ssh, server, "sudo")
    if not ok:
        raise RuntimeError(f"Не удалось установить sudo: {str(message)[:500]}")
    if not _sudo_binary_available(ssh, server):
        raise RuntimeError("Пакет sudo установлен, но binary недоступен")
    return True


def _grant_sudo_group(ssh, server: dict, username: str) -> None:
    command = (
        "if getent group sudo >/dev/null 2>&1; then g=sudo; "
        "elif getent group wheel >/dev/null 2>&1; then g=wheel; "
        "else exit 45; fi; "
        f"usermod -aG \"$g\" -- {shlex.quote(username)} && "
        f"id -nG -- {shlex.quote(username)} | tr ' ' '\\n' | grep -qx \"$g\""
    )
    code, out, err = exec_sudo(ssh, server, command, timeout=20)
    if code != 0:
        raise RuntimeError(err or out or "Группа sudo/wheel не найдена")


def _sudo_privilege_listing_ok(ssh, server: dict, username: str) -> bool:
    """Проверить sudoers-права пользователя (листинг от root, без пароля).

    sudo >=1.9 печатает «User … is not allowed to run sudo» в stdout и
    выходит с кодом 0 — недостаточно проверять только exit code, нужно
    убедиться в отсутствии отказа в выводе.
    """
    code, out, _ = exec_sudo(
        ssh,
        server,
        "command -v sudo >/dev/null 2>&1 && "
        f"sudo -l -U {shlex.quote(username)} 2>&1",
        timeout=15,
    )
    if code != 0:
        return False
    return "not allowed to run sudo" not in (out or "").lower()


def _sudo_real_execution_ok(ssh, server: dict, username: str, password: str) -> bool:
    """Подтвердить реальное выполнение sudo от имени пользователя.

    Пароль передаётся через stdin (base64-пайп, как в chpasswd), команда
    выполняется в контексте пользователя через runuser/su от root.
    """
    if any(char in password for char in ("\x00", "\r", "\n")):
        return False
    payload = base64.b64encode(f"{password}\n".encode("utf-8")).decode("ascii")
    quoted = shlex.quote(username)
    command = (
        f"printf %s {shlex.quote(payload)} | base64 -d | "
        f"if command -v runuser >/dev/null 2>&1; then "
        f"runuser -u {quoted} -- sudo -S -p '' true; "
        f"else su {quoted} -s /bin/sh -c \"sudo -S -p '' true\"; fi"
    )
    code, _, _ = exec_sudo(ssh, server, command, timeout=20)
    return code == 0


def _set_remote_password(ssh, server: dict, username: str, password: str) -> tuple[bool, str]:
    if any(char in password for char in ("\x00", "\r", "\n")):
        return False, "Пароль содержит недопустимые управляющие символы"
    payload = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    code, out, err = exec_sudo(
        ssh,
        server,
        f"printf %s {shlex.quote(payload)} | base64 -d | chpasswd",
        timeout=20,
    )
    return code == 0, (err or out or f"exit {code}")[:500]


_OWN_PASSWD_PY = (
    "import base64, os, pty, sys, time\n"
    "old = base64.b64decode(sys.argv[1]).decode()\n"
    "new = base64.b64decode(sys.argv[2]).decode()\n"
    "def read_until(fd, needle, timeout):\n"
    "    buf = b''\n"
    "    deadline = time.time() + timeout\n"
    "    while time.time() < deadline:\n"
    "        try:\n"
    "            chunk = os.read(fd, 256)\n"
    "        except OSError:\n"
    "            break\n"
    "        if not chunk:\n"
    "            break\n"
    "        buf += chunk\n"
    "        if needle in buf:\n"
    "            return True\n"
    "    return False\n"
    "pid, fd = pty.fork()\n"
    "if pid == 0:\n"
    "    os.environ['LC_ALL'] = 'C'\n"
    "    os.execvp('passwd', ['passwd'])\n"
    "try:\n"
    "    read_until(fd, b':', 10)\n"
    "    os.write(fd, old.encode() + b'\\n')\n"
    "    read_until(fd, b':', 10)\n"
    "    os.write(fd, new.encode() + b'\\n')\n"
    "    read_until(fd, b':', 10)\n"
    "    os.write(fd, new.encode() + b'\\n')\n"
    "    out = b''\n"
    "    while True:\n"
    "        try:\n"
    "            chunk = os.read(fd, 256)\n"
    "        except OSError:\n"
    "            break\n"
    "        if not chunk:\n"
    "            break\n"
    "        out += chunk\n"
    "finally:\n"
    "    try:\n"
    "        os.close(fd)\n"
    "    except OSError:\n"
    "        pass\n"
    "_, status = os.waitpid(pid, 0)\n"
    "code = os.waitstatus_to_exitcode(status)\n"
    "text = out.decode('utf-8', 'replace')\n"
    "if code == 0 and 'success' in text.lower():\n"
    "    print('OK')\n"
    "else:\n"
    "    sys.stderr.write(text[:400])\n"
    "    sys.exit(1)\n"
)


def _set_own_password_pty(
    ssh,
    server: dict,
    current_password: str,
    new_password: str,
    exec_fn=None,
) -> tuple[bool, str]:
    """Сменить собственный пароль через интерактивный passwd (pty), без sudo.

    chpasswd требует root; собственный пароль пользователь меняет сам через
    passwd, отвечая на три промпта (текущий → новый → повтор). Пароли
    передаются base64 в аргументах (та же модель раскрытия, что у chpasswd).
    """
    if exec_fn is None:
        exec_fn = exec_plain
    if any(char in current_password + new_password for char in ("\x00", "\r", "\n")):
        return False, "Пароль содержит недопустимые управляющие символы"
    old_b64 = base64.b64encode(current_password.encode("utf-8")).decode("ascii")
    new_b64 = base64.b64encode(new_password.encode("utf-8")).decode("ascii")
    command = (
        f"python3 -c {shlex.quote(_OWN_PASSWD_PY)} "
        f"{shlex.quote(old_b64)} {shlex.quote(new_b64)}"
    )
    code, out, err = exec_fn(ssh, server, command, timeout=40)
    return code == 0, (err or out or f"exit {code}")[:500]


def change_password(server: dict, new_password: str) -> OpResult:
    """Сменить пароль, проверить рабочий route и CAS-коммитить credential."""
    if not isinstance(new_password, str) or not 6 <= len(new_password) <= 256:
        return OpResult(ok=False, message="Пароль должен содержать 6–256 символов", error="weak_password")
    if any(char in new_password for char in ("\x00", "\r", "\n")):
        return OpResult(ok=False, message="Пароль содержит недопустимые символы", error="bad_password")

    ssh = None
    try:
        working, expected = _fresh_server(server)
        username = _valid_username(working.get("user") or "")
        old_password = expected.get("password")
        ssh = create_ssh_client(working, timeout=15)
        exec_fn, sudo_ok = _resolve_exec(ssh, working)
        if sudo_ok:
            changed, detail = _set_remote_password(ssh, working, username, new_password)
        else:
            # Без sudo chpasswd недоступен: собственный пароль меняем через
            # интерактивный passwd (pty) — нужен текущий пароль пользователя.
            if not isinstance(old_password, str) or not old_password:
                return OpResult(
                    ok=False,
                    message=(
                        "Без sudo смена пароля требует текущий пароль пользователя; "
                        "он не сохранён в Bot4VPS (подключение по ключу без пароля)"
                    ),
                    error="old_password_required",
                )
            changed, detail = _set_own_password_pty(
                ssh, working, old_password, new_password, exec_fn=exec_fn
            )
        if not changed:
            return OpResult(ok=False, message="Не удалось сменить пароль", error=detail)

        candidate = {**working, "password": new_password}
        if working.get("auth_type") != "key":
            candidate["auth_type"] = "password"
        # sudo обязателен, только если был доступен до смены пароля.
        verified, verify_error = _verify_login_and_optional_sudo(
            candidate, require_sudo=sudo_ok
        )
        if not verified:
            rollback = False
            rollback_error = None
            if isinstance(old_password, str) and old_password:
                if sudo_ok:
                    rollback, rollback_error = _set_remote_password(
                        ssh, {**working, "password": new_password}, username, old_password
                    )
                else:
                    rollback, rollback_error = _set_own_password_pty(
                        ssh, {**working, "password": new_password}, new_password, old_password,
                        exec_fn=exec_fn,
                    )
            return OpResult(
                ok=False,
                message=(
                    "Новый пароль не подтвердил SSH/sudo; прежний пароль восстановлен"
                    if rollback
                    else "Новый пароль не подтвердил SSH/sudo; требуется ручная проверка доступа"
                ),
                error=verify_error,
                data={"rollback": {"attempted": bool(old_password), "ok": rollback, "error": rollback_error}},
            )

        try:
            compare_and_set_server_connection(
                working["id"],
                {"password": new_password},
                expected_connection=expected,
            )
        except ConnectionStateConflictError as exc:
            rollback = False
            rollback_error = None
            if isinstance(old_password, str) and old_password:
                if sudo_ok:
                    rollback, rollback_error = _set_remote_password(
                        ssh, {**working, "password": new_password}, username, old_password
                    )
                else:
                    rollback, rollback_error = _set_own_password_pty(
                        ssh, {**working, "password": new_password}, new_password, old_password,
                        exec_fn=exec_fn,
                    )
            return OpResult(
                ok=False,
                message=(
                    "SSH-настройки были изменены параллельно; прежний пароль восстановлен"
                    if rollback
                    else "SSH-настройки были изменены параллельно; требуется ручная проверка пароля"
                ),
                error=str(exc)[:500],
                data={"rollback": {"attempted": bool(old_password), "ok": rollback, "error": rollback_error}},
            )

        key_auth = working.get("auth_type") == "key"
        return OpResult(
            ok=True,
            message=(
                "Пароль обновлён; вход по ключу и sudo с новым паролем подтверждены"
                if key_auth and sudo_ok
                else "Пароль обновлён, SSH-вход и sudo подтверждены"
                if sudo_ok
                else "Пароль обновлён, SSH-вход подтверждён"
            ),
            data={
                "user": username,
                "auth_type": "key" if key_auth else "password",
                "login_verified": True,
                "sudo_verified": sudo_ok,
            },
        )
    except Exception as exc:
        return OpResult(ok=False, message="Ошибка смены пароля", error=str(exc)[:800])
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def _dropin_with_setting(
    snapshot: RemoteFileSnapshot,
    directive: str,
    value: str,
) -> str:
    """Заменить одну global-директиву, не затрагивая Match-блоки."""
    try:
        text = snapshot.content.decode("utf-8") if snapshot.existed else ""
    except UnicodeDecodeError as exc:
        raise RuntimeError("SSH drop-in имеет неподдерживаемую кодировку") from exc
    wanted = directive.lower()
    before_match: list[str] = []
    match_and_after: list[str] = []
    in_match = False
    for raw in text.splitlines():
        effective = raw.split("#", 1)[0].strip()
        parts = effective.split(None, 1)
        key = parts[0].lower() if parts else ""
        if key == "match":
            in_match = True
        if not in_match and key == wanted:
            continue
        (match_and_after if in_match else before_match).append(raw)
    if not before_match and not match_and_after:
        before_match = ["# Managed by Bot4VPS Quick Setup"]
    while before_match and not before_match[-1].strip():
        before_match.pop()
    before_match.extend(["", f"{directive} {value}"])
    lines = before_match + ([""] if match_and_after else []) + match_and_after
    return "\n".join(lines).rstrip() + "\n"


def _mutate_sshd_setting(
    server: dict,
    directive: str,
    value: str,
    effective_key: str,
    expected_value: str,
) -> OpResult:
    ssh = None
    snapshot = None
    working = server
    try:
        working, _ = _fresh_server(server)
        ssh = create_ssh_client(working, timeout=15)
        code, out, err = exec_sudo(
            ssh,
            working,
            "[ ! -L /etc/ssh/sshd_config.d ] && install -d -m 755 /etc/ssh/sshd_config.d",
            timeout=15,
        )
        if code != 0:
            raise RuntimeError(err or out or "Не удалось подготовить sshd_config.d")
        snapshot = snapshot_file(ssh, working, _SSHD_DROPIN)
        atomic_write(
            ssh,
            working,
            _SSHD_DROPIN,
            _dropin_with_setting(snapshot, directive, value),
            mode=snapshot.mode if snapshot.existed else 0o644,
            uid=snapshot.uid if snapshot.existed else None,
            gid=snapshot.gid if snapshot.existed else None,
        )
        applied, detail = _sshd_reload(ssh, working)
        if not applied:
            raise RuntimeError(detail)
        effective = (_read_sshd_setting(ssh, working, effective_key) or "").lower()
        if effective != expected_value.lower():
            raise RuntimeError(
                f"sshd не применил {directive}: получено {effective or 'пусто'}"
            )
        verified, verify_error = _verify_login_and_sudo(working)
        if not verified:
            raise RuntimeError(f"Новый SSH-доступ не подтверждён: {verify_error}")
        return OpResult(
            ok=True,
            message="SSH-настройка применена и вход подтверждён",
            data={
                "directive": directive,
                "effective": effective,
                "login_verified": True,
                "sudo_verified": True,
            },
        )
    except Exception as exc:
        rollback = {"attempted": snapshot is not None, "ok": False}
        if ssh is not None and snapshot is not None:
            try:
                restore_file(ssh, working, snapshot)
                restored, detail = _sshd_reload(ssh, working)
                old_login, old_error = _verify_login_and_sudo(working) if restored else (False, detail)
                rollback.update({
                    "ok": bool(restored and old_login),
                    "login_verified": old_login,
                    "error": None if restored and old_login else (old_error or detail)[:500],
                })
            except Exception as rollback_exc:
                rollback["error"] = str(rollback_exc)[:500]
        return OpResult(
            ok=False,
            message=(
                "SSH-настройка не применена; исходная конфигурация восстановлена"
                if rollback.get("ok")
                else "SSH-настройка не применена; откат подтверждён не полностью"
            ),
            error=str(exc)[:800],
            data={"rollback": rollback},
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def set_root_login(server: dict, enabled: bool) -> OpResult:
    """Изменить PermitRootLogin только при сохранении проверенного route."""
    try:
        working, _ = _fresh_server(server)
    except Exception as exc:
        return OpResult(ok=False, message="Сервер не найден", error=str(exc)[:500])
    if not enabled and str(working.get("user") or "").lower() == "root":
        return OpResult(
            ok=False,
            message="Нельзя запретить root login, пока Bot4VPS подключается как root. Сначала переключитесь на проверенного sudo-пользователя.",
            error="current_route_is_root",
        )
    verified, verify_error = _verify_login_and_sudo(working)
    if not verified:
        return OpResult(
            ok=False,
            message=(
                "Текущий SSH/sudo-доступ не подтверждён — root login не меняем. "
                "Выдайте sudo текущему пользователю или переключитесь на пользователя с рабочим sudo."
            ),
            error=verify_error,
        )
    result = _mutate_sshd_setting(
        working,
        "PermitRootLogin",
        "yes" if enabled else "no",
        "permitrootlogin",
        "yes" if enabled else "no",
    )
    if result.ok:
        result.message = f"Вход root: {'разрешён' if enabled else 'запрещён'}, SSH-вход подтверждён"
        if result.data is not None:
            result.data["root_login"] = "Разрешён" if enabled else "Запрещён"
    return result


def set_password_auth(server: dict, enabled: bool) -> OpResult:
    """Изменить PasswordAuthentication без отключения единственного route.

    Отключение — многоступенчатая защита от lockout: записи key_path в
    servers.json самой по себе недостаточно.
    """
    try:
        working, expected = _fresh_server(server)
    except Exception as exc:
        return OpResult(ok=False, message="Сервер не найден", error=str(exc)[:500])
    if not enabled:
        checked = _prepare_verified_key_route(working, expected)
        if not checked.ok:
            return checked
        working = checked.data["working"]
    result = _mutate_sshd_setting(
        working,
        "PasswordAuthentication",
        "yes" if enabled else "no",
        "passwordauthentication",
        "yes" if enabled else "no",
    )
    if result.ok:
        result.message = f"Аутентификация по паролю: {'разрешена' if enabled else 'запрещена'}, SSH-вход подтверждён"
        if result.data is not None:
            result.data["password_auth"] = "Разрешена" if enabled else "Запрещена"
    return result


def _prepare_verified_key_route(working: dict, expected: dict) -> OpResult:
    """Готовит проверенный key-роут перед отключением password auth.

    Схема (каждый шаг — отказ с честным сообщением), без автоподбора:
    ключ должен быть явно прописан в servers.json («Выбрать ключ» /
    создание ключа):
    1. key_path задан? Нет — отказ (автоматически ничего не подставляем).
    2. Файл приватного ключа физически существует? Нет — отказ.
    3. Публичная часть соответствует ключу в authorized_keys на сервере
       (ключ не удалён)? Нет — отказ.
    4. Реальный SSH-вход этим ключом + sudo. Провал — отказ.
    5. Переключаем servers.json на key-роут (CAS).

    Финальная проверка SSH после мутации sshd — внутри
    _mutate_sshd_setting (с откатом конфига при провале).
    """
    ssh = None
    current_user = str(working.get("user") or "")
    try:
        key_path = str(working.get("key_path") or "")
        if not key_path:
            return OpResult(
                ok=False,
                message="Отключение password auth возможно только после настройки ключа для текущего пользователя Bot4VPS",
                error="no_verified_key_route",
            )
        ssh = create_ssh_client(working, timeout=15)
        # Чтение собственных authorized_keys доступно и без sudo; sudo нужен
        # только для самой мутации sshd — без неё она честно откажет.
        exec_fn, sudo_ok = _resolve_exec(ssh, working)
        # Шаг 2: файл ключа должен существовать.
        if not Path(key_path).is_file():
            return OpResult(
                ok=False,
                message="Указанный SSH-ключ не найден локально. Авторизация по паролю не отключена.",
                error="key_file_missing",
            )
        # Шаг 3: публичная часть должна соответствовать ключу на сервере.
        pub = Path(key_path + ".pub")
        try:
            pub_content = pub.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return OpResult(
                ok=False,
                message=f"Не удалось прочитать публичную часть ключа {key_path}. Авторизация по паролю не отключена.",
                error=f"key_pub_read_failed: {exc}"[:500],
            )
        local_fingerprint = _pubkey_fingerprint(pub_content)
        if not local_fingerprint:
            return OpResult(
                ok=False,
                message=f"Публичная часть ключа {key_path} повреждена. Авторизация по паролю не отключена.",
                error="key_pub_invalid",
            )
        fingerprints = _user_server_fingerprints(ssh, working, current_user, exec_fn=exec_fn)
        if fingerprints is None:
            return OpResult(
                ok=False,
                message=f"Пользователь {current_user} не найден на сервере",
                error="user_not_found",
            )
        if local_fingerprint not in fingerprints:
            return OpResult(
                ok=False,
                message=(
                    f"Ключ {key_path} отсутствует в authorized_keys пользователя "
                    f"{current_user} (удалён с сервера?). Авторизация по паролю не отключена."
                ),
                error="key_not_on_server",
            )
        # Шаг 4: реальный вход ключом (sudo — если он был доступен).
        candidate = {**working, "auth_type": "key", "key_path": key_path}
        verified, verify_error = _verify_login_and_optional_sudo(
            candidate, require_sudo=sudo_ok
        )
        if not verified:
            return OpResult(
                ok=False,
                message="Вход по ключу не подтверждён — password auth не отключаем"
                if not sudo_ok
                else "Вход по ключу и sudo не подтверждены — password auth не отключаем",
                error=verify_error,
            )
        # Шаг 5: переключаем servers.json на key-роут.
        if working.get("auth_type") != "key" or str(working.get("key_path")) != key_path:
            try:
                compare_and_set_server_connection(
                    working["id"],
                    {"auth_type": "key", "key_path": key_path},
                    expected_connection=expected,
                )
            except ConnectionStateConflictError as exc:
                return OpResult(
                    ok=False,
                    message="SSH-настройки были изменены параллельно; попробуйте снова",
                    error=str(exc)[:500],
                )
            working = {**working, "auth_type": "key", "key_path": key_path}
        return OpResult(
            ok=True,
            message="Key-роут проверен",
            data={"working": working, "key_path": key_path, "fingerprint": local_fingerprint},
        )
    except Exception as exc:
        return OpResult(ok=False, message="Не удалось подготовить key-роут", error=str(exc)[:800])
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def _validate_public_key(public_key: str) -> str:
    value = str(public_key or "").strip()
    if len(value) > 8192 or "\n" in value or "\r" in value or "\x00" in value:
        raise ValueError("Некорректный публичный ключ")
    match = re.fullmatch(
        r"(ssh-(?:ed25519|rsa)|ecdsa-sha2-nistp(?:256|384|521)|"
        r"sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com) "
        r"([A-Za-z0-9+/]+={0,3})(?: ([^\x00-\x1f]{0,256}))?",
        value,
    )
    if not match:
        raise ValueError("Некорректный формат публичного ключа")
    try:
        decoded = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Некорректные данные публичного ключа") from exc
    if not 16 <= len(decoded) <= 16384:
        raise ValueError("Некорректные данные публичного ключа")
    return value


def _validated_private_key_path(key_path: str) -> str:
    value = str(key_path or "").strip()
    if not value or any(char in value for char in ("\x00", "\r", "\n")):
        raise ValueError("Не выбран приватный ключ")
    source = Path(value)
    if source.is_symlink():
        raise ValueError("Символьные ссылки на приватные ключи не поддерживаются")
    try:
        resolved = source.resolve(strict=True)
        root = _keys_dir().resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("Приватный ключ должен находиться в каталоге ключей Bot4VPS") from exc
    if not resolved.is_file():
        raise ValueError("Файл приватного ключа не найден")
    return str(resolved)


def install_pubkey(
    server: dict,
    public_key: str,
    *,
    switch_to_key: bool = False,
    key_path: Optional[str] = None,
) -> OpResult:
    """Атомарно добавить public key и подтверждать key access только real login."""
    try:
        public_key = _validate_public_key(public_key)
        validated_key_path = _validated_private_key_path(key_path or "") if switch_to_key else None
    except ValueError as exc:
        return OpResult(ok=False, message=str(exc), error="bad_key")

    ssh = None
    snapshot = None
    sudo_ok = True
    working = server
    try:
        working, expected = _fresh_server(server)
        username = _valid_username(working.get("user") or "")
        ssh = create_ssh_client(working, timeout=15)
        # Ключ пишется в собственный ~/.ssh текущего пользователя: если sudo
        # не подтверждён — работаем без него (без chown, файлы и так его).
        exec_fn, sudo_ok = _resolve_exec(ssh, working)
        # Реестр ключей: сначала сверяемся с сервером (sudo), затем
        # проверяем занятость — один ключ не могут использовать
        # несколько аккаунтов одного сервера.
        _sync_key_registry(ssh, working, exec_fn, sudo_ok)
        fingerprint = _pubkey_fingerprint(public_key) or ""
        server_id = str(working.get("id") or "")
        key_owner = (
            key_registry.find_owner(server_id, fingerprint, exclude_user=username)
            if fingerprint
            else None
        )
        if key_owner:
            return OpResult(
                ok=False,
                message=(
                    f"Этот ключ уже использует пользователь {key_owner}. "
                    "Один ключ — один пользователь: создайте новый в менеджере ключей."
                ),
                error="key_in_use",
                data={"key_owner": key_owner, "fingerprint": fingerprint},
            )
        account = _account(ssh, working, username, exec_fn=exec_fn)
        if not account or not account["home"].startswith("/"):
            return OpResult(ok=False, message="Домашний каталог пользователя не найден", error="home_not_found")
        home = account["home"]
        ssh_dir = f"{home}/.ssh"
        auth_keys = f"{ssh_dir}/authorized_keys"
        owner = f"-o {account['uid']} -g {account['gid']} " if sudo_ok else ""
        code, out, err = exec_fn(
            ssh,
            working,
            f"[ -d {shlex.quote(home)} ] && [ ! -L {shlex.quote(home)} ] && "
            f"[ ! -L {shlex.quote(ssh_dir)} ] && "
            f"install -d -m 700 {owner}{shlex.quote(ssh_dir)}",
            timeout=20,
        )
        if code != 0:
            return OpResult(
                ok=False,
                message="Небезопасный или недоступный каталог .ssh",
                error=(err or out or f"exit {code}")[:500],
            )
        snapshot = snapshot_file(ssh, working, auth_keys, sudo=sudo_ok)
        current = snapshot.content
        lines = current.splitlines()
        key_bytes = public_key.encode("utf-8")
        if key_bytes not in lines:
            content = current
            if content and not content.endswith(b"\n"):
                content += b"\n"
            content += key_bytes + b"\n"
            atomic_write(
                ssh,
                working,
                auth_keys,
                content,
                mode=0o600,
                uid=account["uid"],
                gid=account["gid"],
                sudo=sudo_ok,
            )

        if not switch_to_key:
            if fingerprint:
                key_registry.record(server_id, username, fingerprint)
            return OpResult(
                ok=True,
                message="Публичный ключ добавлен; вход этим ключом не проверялся",
                data={
                    "key_added": key_bytes not in lines,
                    "key_verified": False,
                    "fingerprint": fingerprint,
                },
            )

        candidate = {
            **working,
            "auth_type": "key",
            "key_path": validated_key_path,
        }
        # sudo обязателен, только если он был доступен по паролю.
        verified, verify_error = _verify_login_and_optional_sudo(candidate, require_sudo=sudo_ok)
        if not verified:
            restore_file(ssh, working, snapshot, sudo=sudo_ok)
            return OpResult(
                ok=False,
                message="Ключ записан, но вход и sudo не подтверждены; authorized_keys восстановлен"
                if sudo_ok
                else "Ключ записан, но вход ключом не подтверждён; authorized_keys восстановлен",
                error=verify_error,
                data={"rollback": {"ok": True}, "key_verified": False},
            )
        try:
            compare_and_set_server_connection(
                working["id"],
                {"auth_type": "key", "key_path": validated_key_path},
                expected_connection=expected,
            )
        except ConnectionStateConflictError as exc:
            restore_file(ssh, working, snapshot, sudo=sudo_ok)
            return OpResult(
                ok=False,
                message="SSH-настройки были изменены параллельно; authorized_keys восстановлен",
                error=str(exc)[:500],
                data={"rollback": {"ok": True}, "key_verified": False},
            )
        if fingerprint:
            key_registry.record(server_id, username, fingerprint)
        return OpResult(
            ok=True,
            message=(
                "SSH-ключ установлен, вход и sudo подтверждены"
                if sudo_ok
                else "SSH-ключ установлен, вход ключом подтверждён"
            ),
            data={
                "auth_type": "key",
                "key_verified": True,
                "sudo_verified": sudo_ok,
                "fingerprint": fingerprint,
            },
        )
    except Exception as exc:
        rollback = None
        if ssh is not None and snapshot is not None:
            try:
                restore_file(ssh, working, snapshot, sudo=sudo_ok)
                rollback = {"ok": True}
            except Exception as rollback_exc:
                rollback = {"ok": False, "error": str(rollback_exc)[:500]}
        return OpResult(
            ok=False,
            message="Ошибка установки ключа",
            error=str(exc)[:800],
            data={"rollback": rollback} if rollback is not None else None,
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def create_user(
    server: dict,
    username: str,
    *,
    password: Optional[str] = None,
    sudo: bool = True,
    switch_to_user: bool = False,
) -> OpResult:
    """Создать аккаунт без неявного переключения connection context."""
    try:
        username = _valid_username(username)
    except ValueError as exc:
        return OpResult(ok=False, message=str(exc), error="bad_username")
    if password is not None:
        if not isinstance(password, str) or not 6 <= len(password) <= 256:
            return OpResult(ok=False, message="Пароль должен содержать 6–256 символов", error="weak_password")
        if any(char in password for char in ("\x00", "\r", "\n")):
            return OpResult(ok=False, message="Пароль содержит недопустимые символы", error="bad_password")
    if switch_to_user:
        return OpResult(
            ok=False,
            message="Создание и переключение разделены. Сначала создайте пользователя, затем используйте «Переключить».",
            error="implicit_switch_forbidden",
        )

    ssh = None
    created = False
    working = server
    try:
        working, _ = _fresh_server(server)
        ssh = create_ssh_client(working, timeout=15)
        if _account(ssh, working, username):
            return OpResult(ok=False, message="Пользователь уже существует", error="user_exists")
        code, out, err = exec_sudo(
            ssh,
            working,
            f"useradd -m -s /bin/bash -- {shlex.quote(username)}",
            timeout=30,
        )
        if code != 0:
            return OpResult(
                ok=False,
                message="Не удалось создать пользователя",
                error=(err or out or f"exit {code}")[:500],
            )
        created = True
        account = _account(ssh, working, username)
        if not account:
            raise RuntimeError("Созданный пользователь не обнаружен")
        if password is not None:
            changed, detail = _set_remote_password(ssh, working, username, password)
            if not changed:
                raise RuntimeError(f"Не удалось задать пароль: {detail}")
        sudo_package_installed = False
        sudo_verified = False
        if sudo:
            # Пакет sudo может отсутствовать, хотя группа sudo существует:
            # без binary членство в группе даёт неработающий sudo. Ставим
            # пакет, выдаём группу и подтверждаем фактическое выполнение sudo.
            sudo_package_installed = _ensure_sudo_installed(ssh, working)
            _grant_sudo_group(ssh, working, username)
            if password is not None:
                sudo_verified = _sudo_real_execution_ok(ssh, working, username, password)
            else:
                # Пароль не задан (key-only аккаунт): проверяем sudoers-права
                sudo_verified = _sudo_privilege_listing_ok(ssh, working, username)
            if not sudo_verified:
                raise RuntimeError("sudo не подтверждён для нового пользователя")

        # Ч8.3: authorized_keys от текущего пользователя НЕ копируем —
        # новый аккаунт создаётся без ключей; ключи выдаются менеджером
        # ключей (см. add_key_to_user) явным действием.

        return OpResult(
            ok=True,
            message=f"Пользователь {username} создан. Connection context не изменён.",
            data={
                "user": username,
                "sudo_group": bool(sudo),
                "sudo_package_installed": bool(sudo and sudo_package_installed),
                "sudo_verified": bool(sudo and sudo_verified),
                "password_configured": password is not None,
                "switched": False,
            },
        )
    except Exception as exc:
        cleanup = {"attempted": created, "ok": False}
        if created and ssh is not None:
            code, out, err = exec_sudo(
                ssh,
                working,
                f"userdel -r -- {shlex.quote(username)}",
                timeout=30,
            )
            cleanup.update({"ok": code == 0, "error": None if code == 0 else (err or out or f"exit {code}")[:500]})
        return OpResult(
            ok=False,
            message=(
                "Создание пользователя не завершено; созданная учётная запись удалена"
                if cleanup.get("ok")
                else "Создание пользователя не завершено; проверьте частично созданную учётную запись"
            ),
            error=str(exc)[:800],
            data={"cleanup": cleanup},
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def grant_sudo(server: dict, username: str) -> OpResult:
    """Выдать sudo существующему пользователю с установкой пакета и проверкой."""
    try:
        username = _valid_username(username)
    except ValueError as exc:
        return OpResult(ok=False, message=str(exc), error="bad_username")

    ssh = None
    try:
        working, _ = _fresh_server(server)
        ssh = create_ssh_client(working, timeout=15)
        account = _account(ssh, working, username)
        if not account:
            return OpResult(ok=False, message="Пользователь не существует", error="user_not_found")
        if account["uid"] == 0:
            return OpResult(
                ok=True,
                message="root уже обладает полными правами",
                data={"user": username, "sudo_verified": True},
            )

        sudo_package_installed = _ensure_sudo_installed(ssh, working)
        _grant_sudo_group(ssh, working, username)
        sudo_verified = _sudo_privilege_listing_ok(ssh, working, username)
        if not sudo_verified:
            return OpResult(
                ok=False,
                message="Группа выдана, но права sudo не подтверждены; проверьте /etc/sudoers",
                error="sudo_not_verified",
                data={"user": username, "sudo_package_installed": sudo_package_installed},
            )
        return OpResult(
            ok=True,
            message=f"sudo выдан пользователю {username}",
            data={
                "user": username,
                "sudo_package_installed": sudo_package_installed,
                "sudo_verified": True,
            },
        )
    except Exception as exc:
        return OpResult(ok=False, message="Не удалось выдать sudo", error=str(exc)[:800])
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def _revoke_sudo_group(ssh, server: dict, username: str) -> str:
    """Убрать пользователя из группы sudo/wheel/admin.

    Возвращает имя группы, из которой убрали. Молчит, если пользователя
    в группе нет (идемпотентно). exit 45 — группа не найдена.
    """
    command = (
        "if getent group sudo >/dev/null 2>&1; then g=sudo; "
        "elif getent group wheel >/dev/null 2>&1; then g=wheel; "
        "elif getent group admin >/dev/null 2>&1; then g=admin; "
        "else exit 45; fi; "
        f"gpasswd -d {shlex.quote(username)} \"$g\" >/dev/null; "
        f"id -nG -- {shlex.quote(username)} | tr ' ' '\\n' | grep -qx \"$g\" "
        f"&& exit 47 || exit 0"
    )
    code, out, err = exec_sudo(ssh, server, command, timeout=20)
    if code == 45:
        raise RuntimeError("Группа sudo/wheel/admin не найдена")
    if code == 47:
        # после удаления членство всё ещё подтверждено — не должны были попасть сюда
        raise RuntimeError(err or out or "Пользователь остался в группе sudo")
    if code not in (0, 1):
        raise RuntimeError(err or out or f"exit {code}")
    return "sudo/wheel"


def revoke_sudo(server: dict, username: str) -> OpResult:
    """Отозвать sudo у пользователя: удаление из группы sudo/wheel/admin
    с финальной проверкой, что привилегий больше нет.

    Защитные инварианты:
    - root не трогаем (у него sudo по определению);
    - текущий пользователь Bot4VPS не может отозвать sudo у себя — иначе
      следующая операция Quick Setup и SSH-сбор потеряют права.
    """
    try:
        username = _valid_username(username)
    except ValueError as exc:
        return OpResult(ok=False, message=str(exc), error="bad_username")

    ssh = None
    try:
        working, _ = _fresh_server(server)
        if username == (working.get("user") or ""):
            return OpResult(
                ok=False,
                message="Нельзя отозвать sudo у текущего пользователя Bot4VPS: "
                        "панель потеряет права для управления сервером",
                error="self_revoke_forbidden",
            )
        ssh = create_ssh_client(working, timeout=15)
        account = _account(ssh, working, username)
        if not account:
            return OpResult(ok=False, message="Пользователь не существует", error="user_not_found")
        if account["uid"] == 0:
            return OpResult(
                ok=False,
                message="root не нуждается в отзыве: суперпользователь и так полные права",
                error="root_revoke_forbidden",
            )
        if not _sudo_privilege_listing_ok(ssh, working, username):
            return OpResult(
                ok=True,
                message=f"У пользователя {username} sudo и так нет",
                data={"user": username, "sudo_verified": False},
            )

        group = _revoke_sudo_group(ssh, working, username)
        sudo_verified = not _sudo_privilege_listing_ok(ssh, working, username)
        if not sudo_verified:
            return OpResult(
                ok=False,
                message="Группа убрана, но права sudo всё ещё подтверждаются; "
                        "проверьте /etc/sudoers и /etc/sudoers.d",
                error="sudo_still_verified",
                data={"user": username, "group": group},
            )
        return OpResult(
            ok=True,
            message=f"sudo отозван у пользователя {username}",
            data={"user": username, "group": group, "sudo_verified": False},
        )
    except Exception as exc:
        return OpResult(ok=False, message="Не удалось отозвать sudo", error=str(exc)[:800])
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass
# Ключи принадлежат учётным записям на сервере (~/.ssh/authorized_keys).
# Права: менеджер доступен там, где текущий пользователь Bot4VPS имеет sudo.
# Инвариант: после любой операции у активного пользователя и root должен
# оставаться хотя бы один рабочий SSH-ключ, если password auth запрещён.

# --- SSH Key Manager (Ч8.2) -----------------------------------------------
# Ключи принадлежат учётным записям на сервере (~/.ssh/authorized_keys).
# Права: менеджер доступен там, где текущий пользователь Bot4VPS имеет sudo.
# Инвариант: после любой операции у активного пользователя и root должен
# оставаться хотя бы один рабочий SSH-ключ, если password auth запрещён.

_KEY_TYPE_RE = re.compile(
    r"^(ssh-(?:ed25519|rsa)|ecdsa-sha2-nistp(?:256|384|521)|"
    r"sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)$"
)


def _parse_pubkey_line(line: str) -> Optional[dict]:
    """Разобрать строку authorized_keys: тип, SHA256 fingerprint, comment.

    Строки с options-полем не поддерживаются при возврате кандидата —
    такой ключ считается нераспознанным (модификацию чужих options не делаем).
    """
    tokens = line.split()
    if not tokens:
        return None
    if not _KEY_TYPE_RE.match(tokens[0]) or len(tokens) < 2:
        return None
    try:
        decoded = base64.b64decode(tokens[1], validate=True)
    except (binascii.Error, ValueError):
        return None
    if not 16 <= len(decoded) <= 16384:
        return None
    digest = hashlib.sha256(decoded).digest()
    fingerprint = "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")
    comment = " ".join(tokens[2:])[:256]
    return {"type": tokens[0], "fingerprint": fingerprint, "comment": comment}


def _pubkey_fingerprint(public_key: str) -> Optional[str]:
    parsed = _parse_pubkey_line(str(public_key or "").strip())
    return parsed["fingerprint"] if parsed else None


def _password_auth_enabled(ssh, server: dict, exec_fn=None) -> Optional[bool]:
    """Эффективное значение PasswordAuthentication (None — не удалось прочитать)."""
    if exec_fn is None:
        exec_fn = exec_sudo
    value = _read_sshd_setting(ssh, server, "passwordauthentication", exec_fn=exec_fn)
    if value is None:
        return None
    return value.strip().lower() == "yes"


def _verify_root_password(server: dict, password: str) -> tuple[bool, str]:
    """Проверить пароль root реальным SSH-входом; пароль нигде не сохраняем."""
    if not isinstance(password, str) or not password or len(password) > 256:
        return False, "Пароль root не указан"
    candidate = {
        **server,
        "user": "root",
        "auth_type": "password",
        "password": password,
    }
    try:
        ssh = create_ssh_client(candidate, timeout=15)
    except Exception as exc:
        return False, f"Вход root по паролю не выполнен: {str(exc)[:400]}"
    try:
        ssh.close()
    except Exception:
        pass
    return True, ""


def _manager_rights_ok(ssh, server: dict) -> tuple[bool, str]:
    """Текущий пользователь Bot4VPS должен обладать sudo (root — всегда может)."""
    current = str(server.get("user") or "").lower()
    if current == "root":
        return True, ""
    if not _sudo_privilege_listing_ok(ssh, server, current):
        return False, "Текущий пользователь Bot4VPS не имеет sudo; управление ключами недоступно"
    return True, ""


def _root_mutation_gate(ssh, server: dict, username: str, root_password: str) -> tuple[bool, str]:
    """Подтверждение паролем root перед мутацией его ключей.

    Проверка нужна только НЕ-root менеджеру — как подтверждение эскалации
    (реальный SSH-вход root с этим паролем). Если Bot4VPS работает под
    самим root, никакое подтверждение не требуется: права уже есть.
    Возвращает (ok, error).
    """
    if str(server.get("user") or "").lower() == "root":
        return True, ""
    if username != "root":
        return True, ""
    return _verify_root_password(server, root_password)


def _user_authorized_keys_path(
    ssh,
    server: dict,
    account: dict,
    exec_fn=None,
) -> tuple[Optional[str], Optional[str]]:
    """Пути (.ssh каталог, authorized_keys) с проверкой на symlink-обход."""
    if exec_fn is None:
        exec_fn = exec_sudo
    home = account.get("home") or ""
    if not home.startswith("/"):
        return None, None
    ssh_dir = f"{home}/.ssh"
    auth_keys = f"{ssh_dir}/authorized_keys"
    code, out, err = exec_fn(
        ssh,
        server,
        f"[ ! -L {shlex.quote(home)} ] && [ ! -L {shlex.quote(ssh_dir)} ] && "
        f"[ ! -L {shlex.quote(auth_keys)} ]",
        timeout=15,
    )
    if code != 0:
        raise RuntimeError("Небезопасный путь authorized_keys (symlink?)")
    return ssh_dir, auth_keys


def _read_authorized_keys(ssh, server: dict, auth_keys: str, exec_fn=None) -> Optional[bytes]:
    """Прочитать authorized_keys (None — файла нет). Безопасно для размера."""
    if exec_fn is None:
        exec_fn = exec_sudo
    code, out, err = exec_fn(
        ssh,
        server,
        f"if [ -f {shlex.quote(auth_keys)} ]; then "
        f"head -c 524288 {shlex.quote(auth_keys)}; fi",
        timeout=15,
    )
    if code != 0:
        raise RuntimeError((err or out or f"exit {code}")[:500])
    return (out or "").encode("utf-8", errors="replace") if out else None


def _local_key_name(server: dict, username: str) -> str:
    """Имя ключа: {имя_сервера}_{пользователь}, безопасные символы.

    У пользователя может быть несколько ключей (бот + Termius + …):
    базовое имя занято → добавляем числовой суффикс _2, _3, …
    """
    raw = f"{server.get('name') or server.get('id') or 'server'}_{username}"
    safe = re.sub(r"[^\w.\-]", "_", raw, flags=re.UNICODE)[:64]
    safe = safe or f"server_{username}"
    if not _key_name_taken(safe):
        return safe
    for index in range(2, 100):
        candidate = f"{safe}_{index}"
        if not _key_name_taken(candidate):
            return candidate
    return safe  # практически недостижимо; ssh-keygen честно откажется


def _key_name_taken(name: str) -> bool:
    keys_dir = _keys_dir()
    return (keys_dir / name).exists() or (keys_dir / (name + ".pub")).exists()


def _create_local_key_pair(name: str) -> tuple[Path, str]:
    """Создать ed25519 пару во встроенном хранилище ключей Bot4VPS.

    Возвращает (путь приватного ключа, содержимое публичного).
    """
    keys_dir = _keys_dir()
    keys_dir.mkdir(parents=True, exist_ok=True)
    private = keys_dir / name
    public = keys_dir / f"{name}.pub"
    if private.exists() or public.exists():
        raise FileExistsError(f"Ключ «{name}» уже существует в хранилище Bot4VPS")
    result = subprocess.run(
        [
            "ssh-keygen", "-t", "ed25519", "-f", str(private),
            "-N", "", "-C", f"bot4vps-{name}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if not private.is_file() or not public.is_file():
        raise RuntimeError(result.stderr or "ssh-keygen не создал пару ключей")
    private.chmod(0o600)
    pub_content = public.read_text(encoding="utf-8", errors="replace").strip()
    if not pub_content:
        raise RuntimeError("Публичная часть ключа пуста")
    return private, pub_content


def _append_pubkey_to(
    ssh,
    server: dict,
    account: dict,
    public_key: str,
    *,
    exec_fn=None,
    sudo: bool = True,
) -> tuple[Optional[RemoteFileSnapshot], bool, str]:
    """Атомарно добавить pubkey в authorized_keys пользователя.

    Возвращает (snapshot, был ли ключ добавлен, ошибка). snapshot нужен
    вызывающему для отката через restore_file.
    """
    if exec_fn is None:
        exec_fn = exec_sudo
    ssh_dir, auth_keys = _user_authorized_keys_path(ssh, server, account, exec_fn=exec_fn)
    if not auth_keys:
        return None, False, "Домашний каталог пользователя не найден"
    # Без sudo chown владельца не менять (и не нужно — свой каталог).
    owner = f"-o {account['uid']} -g {account['gid']} " if sudo else ""
    code, out, err = exec_fn(
        ssh,
        server,
        f"install -d -m 700 {owner}{shlex.quote(ssh_dir)}",
        timeout=20,
    )
    if code != 0:
        return None, False, (err or out or f"exit {code}")[:500]
    snapshot = snapshot_file(ssh, server, auth_keys, sudo=sudo)
    current = snapshot.content or b""
    key_bytes = public_key.encode("utf-8")
    lines = current.splitlines()
    if key_bytes not in lines:
        content = current
        if content and not content.endswith(b"\n"):
            content += b"\n"
        content += key_bytes + b"\n"
        atomic_write(
            ssh,
            server,
            auth_keys,
            content,
            mode=0o600,
            uid=account["uid"],
            gid=account["gid"],
            sudo=sudo,
        )
        return snapshot, True, ""
    return snapshot, False, ""


def _remove_pubkey_line(
    ssh,
    server: dict,
    account: dict,
    fingerprint: str,
    *,
    exec_fn=None,
    sudo: bool = True,
) -> tuple[Optional[RemoteFileSnapshot], bool, str, int]:
    """Удалить строку ключа по fingerprint.

    Возвращает (snapshot, удалён ли, ошибка, сколько валидных ключей осталось).
    """
    if exec_fn is None:
        exec_fn = exec_sudo
    ssh_dir, auth_keys = _user_authorized_keys_path(ssh, server, account, exec_fn=exec_fn)
    if not auth_keys:
        return None, False, "Домашний каталог пользователя не найден", 0
    content = _read_authorized_keys(ssh, server, auth_keys, exec_fn=exec_fn)
    if content is None:
        return None, False, "authorized_keys не найден", 0
    kept_lines: list[bytes] = []
    removed = False
    remaining = 0
    for raw in content.splitlines():
        text = raw.decode("utf-8", errors="replace").strip()
        parsed = _parse_pubkey_line(text)
        if parsed and parsed["fingerprint"] == fingerprint:
            removed = True
            continue
        if parsed:
            remaining += 1
        kept_lines.append(raw)
    if not removed:
        return None, False, "Ключ с таким fingerprint не найден", remaining
    snapshot = snapshot_file(ssh, server, auth_keys, sudo=sudo)
    new_content = b"".join(line + b"\n" for line in kept_lines)
    atomic_write(
        ssh,
        server,
        auth_keys,
        new_content,
        mode=0o600,
        uid=account["uid"],
        gid=account["gid"],
        sudo=sudo,
    )
    return snapshot, True, "", remaining


def _active_route_uses_fingerprint(server: dict, fingerprint: str) -> bool:
    """Использует ли текущий key-auth route сервера этот ключ."""
    if str(server.get("auth_type") or "") != "key":
        return False
    key_path = str(server.get("key_path") or "")
    if not key_path:
        return False
    pub = Path(key_path + ".pub")
    if not pub.is_file():
        return False
    try:
        content = pub.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _pubkey_fingerprint(content) == fingerprint


def _recorded_key_present_on_server(ssh, server: dict, exec_fn=None) -> Optional[bool]:
    """Существует ли записанный key_path реально: локальный файл читается
    и его публичная часть есть в authorized_keys текущего пользователя.

    True/False — проверено (False = запись устарела: ключа нет ни локально,
    ни на сервере). None — проверить не удалось (не пугаем статусом).
    Дополнительных SSH-подключений не открывает: команды идут в переданную
    сессию.
    """
    key_path = str(server.get("key_path") or "")
    if not key_path:
        return None
    pub = Path(key_path + ".pub")
    if not pub.is_file():
        return False
    try:
        fingerprint = _pubkey_fingerprint(
            pub.read_text(encoding="utf-8", errors="replace")
        )
    except OSError:
        return False
    if not fingerprint:
        return False
    try:
        server_fingerprints = _user_server_fingerprints(
            ssh, server, str(server.get("user") or ""), exec_fn=exec_fn
        )
    except Exception:
        return None
    if server_fingerprints is None:
        return None
    return fingerprint in server_fingerprints


def _recorded_key_matches_fingerprint(server: dict, fingerprint: str) -> bool:
    """Совпадает ли записанный в servers.json key_path с этим fingerprint.

    В отличие от _active_route_uses_fingerprint, способ авторизации не важен:
    ключ мог быть записан «Выбрать ключ» при password-auth.
    """
    key_path = str(server.get("key_path") or "")
    if not key_path:
        return False
    pub = Path(key_path + ".pub")
    if not pub.is_file():
        return False
    try:
        content = pub.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _pubkey_fingerprint(content) == fingerprint


def list_local_keys() -> list[dict]:
    """Локальные ключи Bot4VPS с признаком «свободен».

    Ключ занят, если он (или его дубль по fingerprint) прописан key_path
    хоть в одном сервере servers.json. Публичные части читаются локально;
    приватные не раскрываются.
    """
    try:
        keys_dir = _keys_dir()
        local: list[dict] = []
        for pub in sorted(keys_dir.glob("*.pub")):
            try:
                content = pub.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            parsed = _parse_pubkey_line(content.strip())
            if not parsed:
                continue
            local.append({
                "name": pub.stem,
                "type": parsed["type"],
                "fingerprint": parsed["fingerprint"],
                "public_key": content.strip(),
                "private_exists": pub.with_suffix("").is_file(),
            })
        if not local:
            return []
        # Занятость через servers.json: собираем fingerprints записанных
        # key_path всех серверов (дубли по fingerprint тоже заняты).
        recorded: set = set()
        for server in (load_servers() or []):
            key_path = str(server.get("key_path") or "")
            if not key_path:
                continue
            pub = Path(key_path + ".pub")
            try:
                if pub.is_file():
                    fp = _pubkey_fingerprint(
                        pub.read_text(encoding="utf-8", errors="replace")
                    )
                    if fp:
                        recorded.add(fp)
            except OSError:
                continue
        for item in local:
            item["in_use"] = item["fingerprint"] in recorded
        return local
    except Exception:
        return []


def list_local_keys_with_public(server: Optional[dict] = None) -> list[dict]:
    """Свободные локальные ключи с публичной частью — для модалки
    «Добавить готовый ключ на сервер»: пользователь выбирает один из
    них, ключ уходит тем же путём, что вставленный вручную.

    «Свободный» = не используется нигде: не записан key_path ни в один
    сервер (маршруты Bot4VPS) и его fingerprint отсутствует в реестре
    занятости ``server`` (один ключ — один пользователь; иначе ключом
    смогут входить несколько аккаунтов). Реестр локальный — сверка
    проходит без SSH-подключения; актуальность ему обеспечивают
    синхронизации при ключевых операциях и часовой фоновый проход.
    """
    keys = list_local_keys()
    used_on_server: set = set()
    if server is not None:
        section = key_registry.server_users(str(server.get("id") or ""))
        for fingerprints in section.values():
            used_on_server.update(fingerprints)
    free = []
    for item in keys:
        if item.pop("in_use", False):
            continue
        if item.get("fingerprint") in used_on_server:
            continue
        pub_path = _keys_dir() / (item["name"] + ".pub")
        try:
            item["public_key"] = pub_path.read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except OSError:
            continue
        free.append(item)
    return free


def _server_users_key_map(
    ssh,
    working: dict,
    exec_fn: Callable[..., tuple],
) -> Optional[dict[str, list[str]]]:
    """authorized_keys всех real-account пользователей → {username: [fingerprints]}.

    Один SSH-сеанс (передаётся вызывающим): authorized_keys пользователей
    (uid 0 или >=1000, как в list_users) читаются на сервере, каждая
    строка маркируется именем владельца. Требует sudo: чужие
    authorized_keys недоступны для чтения — вызывающий это проверил.
    None — скан не удался.
    """
    script = (
        "getent passwd | awk -F: "
        "'($3 == 0 || $3 >= 1000) "
        "{print $1 \"\\t\" $3 \"\\t\" $6}' | sort -u | head -n 200"
    )
    code, out, err = exec_fn(ssh, working, script, timeout=20)
    if code != 0:
        return None
    # here-doc с переводом строки перед данными: в bash -c команда
    # приходит через shlex.quote, литеральный «\n» heredoc не примет.
    # IFS=$'\t': в двойных кавычках «\t» — литеральный backslash-t,
    # поля не разделялись бы (u съедал всю строку).
    command = (
        'while IFS=$\'\\t\' read -r u _uid home; do '
        'k="$home/.ssh/authorized_keys"; '
        'if [ -f "$k" ] && [ ! -L "$k" ]; then '
        'echo "===USER:$u"; cat "$k"; echo; fi; '
        "done <<'EOF'\n" + (out or "") + "\nEOF"
    )
    code2, out2, err2 = exec_fn(ssh, working, command, timeout=30)
    if code2 != 0:
        return None
    user_map: dict[str, list[str]] = {}
    current: Optional[str] = None
    for raw in (out2 or "").splitlines()[:4096]:
        line = raw.strip()
        if line.startswith("===USER:"):
            current = line[len("===USER:"):]
            if current and current not in user_map:
                user_map[current] = []
            continue
        if not current:
            continue
        parsed = _parse_pubkey_line(line)
        if parsed:
            user_map[current].append(parsed["fingerprint"])
    return {u: sorted(set(fps)) for u, fps in user_map.items() if fps}


def _sync_key_registry(ssh, working: dict, exec_fn: Callable[..., tuple], sudo_ok: bool) -> bool:
    """Синхронизировать секцию сервера в реестре с реальными authorized_keys.

    Реестр (keys/registry.json) — источник быстрых сверок без SSH; сервер —
    истина. Прогоняется при операциях с ключами на активном сервере
    (тем же SSH-сеансом, только с sudo — чужие authorized_keys нечитаемы)
    и фоновым проходом раз в час по всем серверам. Точечно: заменяется
    только секция этого сервера. False — скан не выполнен (не блокирует
    вызвавшую операцию).
    """
    if not sudo_ok:
        return False
    try:
        user_map = _server_users_key_map(ssh, working, exec_fn)
        if user_map is None:
            return False
        return key_registry.replace_server(
            str(working.get("id") or ""), user_map
        )
    except Exception:
        return False


def _local_key_fingerprint(key_path: str) -> Optional[str]:
    """SHA256 fingerprint публичной части локального ключа Bot4VPS."""
    try:
        pub = Path(str(key_path) + ".pub")
        return _pubkey_fingerprint(
            pub.read_text(encoding="utf-8", errors="replace")
        )
    except (OSError, ValueError):
        return None


def sync_server_key_registry(server: dict) -> bool:
    """Фоновая синхронизация реестра одного сервера (собственный сеанс).

    Для часового прохода по всем серверам: отдельное SSH-подключение,
    чтение authorized_keys всех пользователей (sudo) и точечная замена
    секции сервера в реестре. Ошибки глотаются — фоновый проход не
    должен ничего ломать.
    """
    ssh = None
    try:
        working, _ = _fresh_server(server)
        ssh = create_ssh_client(working, timeout=15)
        exec_fn, sudo_ok = _resolve_exec(ssh, working)
        return _sync_key_registry(ssh, working, exec_fn, sudo_ok)
    except Exception:
        return False
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def _find_local_key_by_fingerprint(fingerprint: str) -> Optional[Path]:
    """Локальный приватный ключ Bot4VPS с таким fingerprint публичной части.

    Сверяет все *.pub в каталоге ключей; возвращает путь к приватному
    ключу или None, если совпадения нет.
    """
    try:
        keys_dir = _keys_dir()
        if not keys_dir.is_dir():
            return None
        for pub in sorted(keys_dir.glob("*.pub")):
            try:
                content = pub.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _pubkey_fingerprint(content) == fingerprint:
                private = pub.with_suffix("")
                if private.is_file():
                    return private
        return None
    except Exception:
        return None


def _user_server_fingerprints(
    ssh,
    server: dict,
    username: str,
    exec_fn=None,
) -> Optional[set]:
    """SHA256 fingerprints ключей из authorized_keys пользователя на сервере.

    None — пользователя нет. Ошибки чтения поднимаются исключением
    (symlink-обход, недоступный sudo и т.п.).
    """
    if exec_fn is None:
        exec_fn = exec_sudo
    account = _account(ssh, server, username, exec_fn=exec_fn)
    if not account:
        return None
    _, auth_keys = _user_authorized_keys_path(ssh, server, account, exec_fn=exec_fn)
    if not auth_keys:
        return set()
    content = _read_authorized_keys(ssh, server, auth_keys, exec_fn=exec_fn)
    fingerprints: set = set()
    if content:
        for raw in content.splitlines()[:512]:
            parsed = _parse_pubkey_line(
                raw.decode("utf-8", errors="replace").strip()
            )
            if parsed:
                fingerprints.add(parsed["fingerprint"])
    return fingerprints


def list_user_keys(server: dict, username: str) -> OpResult:
    """Ключи пользователя без секретов: тип, SHA256 fingerprint, comment."""
    try:
        username = _valid_username(username)
    except ValueError as exc:
        return OpResult(ok=False, message=str(exc), error="bad_username")
    ssh = None
    try:
        working, _ = _fresh_server(server)
        ssh = create_ssh_client(working, timeout=15)
        exec_fn, sudo_ok = _resolve_exec(ssh, working)
        if username != str(working.get("user") or "") and not sudo_ok:
            return OpResult(
                ok=False,
                message="Пользователь без sudo может управлять только своими ключами",
                error="no_rights",
            )
        account = _account(ssh, working, username, exec_fn=exec_fn)
        if not account:
            return OpResult(ok=False, message="Пользователь не существует", error="user_not_found")
        ssh_dir, auth_keys = _user_authorized_keys_path(ssh, working, account, exec_fn=exec_fn)
        # Ключ, записанный в servers.json через «Выбрать ключ» (auth_type
        # при этом может оставаться password — это подготовка, не переключение).
        recorded_key_path = str(working.get("key_path") or "")
        recorded_fingerprint = None
        if recorded_key_path:
            recorded_pub = Path(recorded_key_path + ".pub")
            try:
                if recorded_pub.is_file():
                    recorded_fingerprint = _pubkey_fingerprint(
                        recorded_pub.read_text(encoding="utf-8", errors="replace")
                    )
            except OSError:
                recorded_fingerprint = None
        keys: list[dict] = []
        if auth_keys:
            content = _read_authorized_keys(ssh, working, auth_keys, exec_fn=exec_fn)
            if content:
                for raw in content.splitlines()[:512]:
                    parsed = _parse_pubkey_line(
                        raw.decode("utf-8", errors="replace").strip()
                    )
                    if parsed:
                        local_key = _find_local_key_by_fingerprint(
                            parsed["fingerprint"]
                        )
                        if local_key is not None:
                            parsed["local_match"] = True
                            parsed["key_name"] = local_key.name
                        else:
                            parsed["local_match"] = False
                        parsed["route_uses_key"] = _active_route_uses_fingerprint(
                            working, parsed["fingerprint"]
                        )
                        parsed["is_recorded"] = (
                            recorded_fingerprint is not None
                            and parsed["fingerprint"] == recorded_fingerprint
                        )
                        keys.append(parsed)
        password_auth = _password_auth_enabled(ssh, working, exec_fn=exec_fn)
        return OpResult(
            ok=True,
            message=f"Ключей у {username}: {len(keys)}",
            data={
                "user": username,
                "home": account["home"],
                "keys": keys,
                "has_keys": bool(keys),
                "password_auth": password_auth,
                "is_current_user": username == str(working.get("user") or ""),
                "is_root": account["uid"] == 0,
                # Root-менеджеру подтверждение паролем root не нужно —
                # поле «Пароль root» в UI рисуется только не-root.
                "is_current_root": str(working.get("user") or "").lower() == "root",
                "recorded_key_path": recorded_key_path or None,
            },
        )
    except Exception as exc:
        return OpResult(ok=False, message="Ошибка получения ключей", error=str(exc)[:800])
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def add_key_to_user(
    server: dict,
    username: str,
    *,
    root_password: Optional[str] = None,
) -> OpResult:
    """Создать ключ встроенным менеджером и добавить его пользователю.

    Ключ именуется {имя_сервера}_{пользователь}; публичная часть вставляется в
    authorized_keys. Для текущего пользователя — Вариант А: проверка реальным
    входом с ключом и CAS-коммит (пароль в servers.json сохраняется).
    """
    try:
        username = _valid_username(username)
    except ValueError as exc:
        return OpResult(ok=False, message=str(exc), error="bad_username")
    ssh = None
    snapshot = None
    created_private: Optional[Path] = None
    sudo_ok = True
    working = server
    try:
        working, expected = _fresh_server(server)
        ssh = create_ssh_client(working, timeout=15)
        exec_fn, sudo_ok = _resolve_exec(ssh, working)
        # Реестр ключей: сверка с сервером при операции с ключами
        # (активный сервер, тот же сеанс).
        _sync_key_registry(ssh, working, exec_fn, sudo_ok)
        # Свои ключи пользователь пишет и без sudo; чужие — только с sudo.
        if username != str(working.get("user") or ""):
            rights_ok, rights_error = _manager_rights_ok(ssh, working)
            if not rights_ok:
                return OpResult(ok=False, message=rights_error, error="no_rights")
        account = _account(ssh, working, username, exec_fn=exec_fn)
        if not account:
            return OpResult(ok=False, message="Пользователь не существует", error="user_not_found")
        if account["uid"] == 0:
            ok_root, root_error = _root_mutation_gate(ssh, working, username, root_password or "")
            if not ok_root:
                return OpResult(
                    ok=False,
                    message="Требуется подтверждение паролем root (реальный вход)",
                    error="root_password_required",
                    data={"root_password_verified": False, "detail": root_error},
                )

        key_name = _local_key_name(working, username)
        try:
            created_private, public_key = _create_local_key_pair(key_name)
        except FileExistsError as exc:
            return OpResult(
                ok=False,
                message=str(exc) + ". Удалите его в «Файлы → Ключи» или выберите другое имя.",
                error="key_exists",
            )
        try:
            public_key = _validate_public_key(public_key)
        except ValueError as exc:
            return OpResult(ok=False, message=str(exc), error="bad_key")

        snapshot, added, append_error = _append_pubkey_to(
            ssh, working, account, public_key, exec_fn=exec_fn, sudo=sudo_ok
        )
        if append_error:
            raise RuntimeError(append_error)
        fingerprint = _pubkey_fingerprint(public_key) or ""

        def _drop_local_pair() -> None:
            if created_private is None:
                return
            for path in (created_private, created_private.with_suffix(".pub")):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

        key_recorded = False
        if username == str(working.get("user") or ""):
            # Тип авторизации «Создать ключ» НЕ меняет: проверяем ключ
            # реальным входом (ловит PubkeyAuthentication=no и битые ключи),
            # но в servers.json прописываем только key_path. Единственное
            # место, где пользователь явно меняет auth_type — выбор
            # «Авторизоваться по» при переключении пользователя.
            candidate = {
                **working,
                "auth_type": "key",
                "key_path": str(created_private),
            }
            # sudo обязателен, только если он был доступен по паролю.
            verified, verify_error = _verify_login_and_optional_sudo(
                candidate, require_sudo=sudo_ok
            )
            if not verified:
                if snapshot is not None:
                    restore_file(ssh, working, snapshot, sudo=sudo_ok)
                _drop_local_pair()
                return OpResult(
                    ok=False,
                    message="Ключ записан, но вход и sudo не подтверждены; authorized_keys восстановлен"
                    if sudo_ok
                    else "Ключ записан, но вход ключом не подтверждён; authorized_keys восстановлен",
                    error=verify_error,
                    data={"rollback": {"ok": True}, "key_verified": False},
                )
            try:
                compare_and_set_server_connection(
                    working["id"],
                    {"key_path": str(created_private)},
                    expected_connection=expected,
                )
            except ConnectionStateConflictError as exc:
                if snapshot is not None:
                    restore_file(ssh, working, snapshot, sudo=sudo_ok)
                _drop_local_pair()
                return OpResult(
                    ok=False,
                    message="SSH-настройки были изменены параллельно; authorized_keys восстановлен",
                    error=str(exc)[:500],
                    data={"rollback": {"ok": True}, "key_verified": False},
                )
            key_recorded = True

        # Свежий ключ только что записан в authorized_keys пользователя —
        # фиксируем занятость в реестре.
        if fingerprint:
            key_registry.record(str(working.get("id") or ""), username, fingerprint)
        return OpResult(
            ok=True,
            message=(
                f"Ключ {key_name} создан и добавлен пользователю {username}; "
                "прописан в servers.json (способ авторизации не изменён)"
                if key_recorded
                else f"Ключ {key_name} создан и добавлен пользователю {username}"
            ),
            data={
                "user": username,
                "key_name": key_name,
                "key_path": str(created_private),
                "fingerprint": fingerprint,
                "added": added,
                "key_recorded": key_recorded,
                "auth_switched": False,
                "root_password_verified": account["uid"] == 0,
            },
        )
    except Exception as exc:
        rollback = None
        if ssh is not None and snapshot is not None:
            try:
                restore_file(ssh, working, snapshot, sudo=sudo_ok)
                rollback = {"ok": True}
            except Exception as rollback_exc:
                rollback = {"ok": False, "error": str(rollback_exc)[:500]}
        # Локальную пару удаляем, только если она не пригодилась servers.json.
        if created_private is not None and str(working.get("key_path")) != str(created_private):
            for path in (created_private, created_private.with_suffix(".pub")):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        return OpResult(
            ok=False,
            message="Ошибка добавления ключа",
            error=str(exc)[:800],
            data={"rollback": rollback} if rollback is not None else None,
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def select_user_key(server: dict, username: str, fingerprint: str) -> OpResult:
    """Прописать key_path совпадающего локального ключа в servers.json.

    Подготовительная операция, НЕ переключение авторизации:
    authorized_keys пользователя на сервере и локальный ключ Bot4VPS
    сверяются по SHA256 fingerprint; при совпадении key_path записывается
    в servers.json, а auth_type и пароль остаются как были. Позже при
    смене типа на key Bot4VPS уже знает, какой ключ использовать.
    """
    try:
        username = _valid_username(username)
    except ValueError as exc:
        return OpResult(ok=False, message=str(exc), error="bad_username")
    if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", str(fingerprint or "")):
        return OpResult(ok=False, message="Некорректный fingerprint", error="bad_fingerprint")
    ssh = None
    try:
        working, expected = _fresh_server(server)
        if username != str(working.get("user") or ""):
            return OpResult(
                ok=False,
                message="Ключ можно выбрать только для текущего пользователя Bot4VPS",
                error="not_current_user",
            )
        local_key = _find_local_key_by_fingerprint(fingerprint)
        if local_key is None:
            return OpResult(
                ok=False,
                message="Локальный ключ Bot4VPS с таким fingerprint не найден",
                error="local_key_not_found",
            )
        ssh = create_ssh_client(working, timeout=15)
        exec_fn, _sudo_ok = _resolve_exec(ssh, working)
        # Реестр ключей: сверка с сервером при операции с ключами.
        _sync_key_registry(ssh, working, exec_fn, _sudo_ok)
        fingerprints = _user_server_fingerprints(ssh, working, username, exec_fn=exec_fn)
        if fingerprints is None:
            return OpResult(ok=False, message="Пользователь не существует", error="user_not_found")
        if fingerprint not in fingerprints:
            return OpResult(
                ok=False,
                message="Ключа с таким fingerprint нет в authorized_keys пользователя",
                error="key_not_on_server",
            )
        if str(working.get("key_path") or "") == str(local_key):
            key_registry.record(str(working.get("id") or ""), username, fingerprint)
            return OpResult(
                ok=True,
                message="Этот ключ уже прописан в servers.json",
                data={
                    "user": username,
                    "fingerprint": fingerprint,
                    "key_name": local_key.name,
                    "key_path": str(local_key),
                    "auth_type": working.get("auth_type") or "password",
                    "already_set": True,
                },
            )
        compare_and_set_server_connection(
            working["id"],
            {"key_path": str(local_key)},
            expected_connection=expected,
        )
        # Ключ уже лежит в authorized_keys этого пользователя —
        # фиксируем занятость в реестре.
        key_registry.record(str(working.get("id") or ""), username, fingerprint)
        return OpResult(
            ok=True,
            message=(
                f"Ключ {local_key.name} прописан в servers.json "
                "(способ авторизации не изменён)"
            ),
            data={
                "user": username,
                "fingerprint": fingerprint,
                "key_name": local_key.name,
                "key_path": str(local_key),
                "auth_type": working.get("auth_type") or "password",
                "already_set": False,
            },
        )
    except ConnectionStateConflictError as exc:
        return OpResult(
            ok=False,
            message="SSH-настройки были изменены параллельно; попробуйте снова",
            error=str(exc)[:500],
        )
    except Exception as exc:
        return OpResult(ok=False, message="Ошибка выбора ключа", error=str(exc)[:800])
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def remove_key_from_user(
    server: dict,
    username: str,
    fingerprint: str,
    *,
    root_password: Optional[str] = None,
) -> OpResult:
    """Удалить ключ пользователя по fingerprint (только серверная часть).

    Инвариант: если password auth запрещён, у текущего пользователя Bot4VPS
    и root нельзя удалить последний ключ. Если удаляется ключ, который
    servers.json использует сейчас, сначала переключаемся на password-auth
    с реальной проверкой пароля — иначе ключ не удаляем.
    """
    try:
        username = _valid_username(username)
    except ValueError as exc:
        return OpResult(ok=False, message=str(exc), error="bad_username")
    fingerprint = str(fingerprint or "").strip()
    if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", fingerprint):
        return OpResult(ok=False, message="Некорректный fingerprint", error="bad_fingerprint")
    ssh = None
    snapshot = None
    sudo_ok = True
    working = server
    try:
        working, expected = _fresh_server(server)
        ssh = create_ssh_client(working, timeout=15)
        exec_fn, sudo_ok = _resolve_exec(ssh, working)
        # Реестр ключей: сверка с сервером при операции с ключами
        # (активный сервер, тот же сеанс).
        _sync_key_registry(ssh, working, exec_fn, sudo_ok)
        # Свои ключи пользователь пишет и без sudo; чужие — только с sudo.
        if username != str(working.get("user") or ""):
            rights_ok, rights_error = _manager_rights_ok(ssh, working)
            if not rights_ok:
                return OpResult(ok=False, message=rights_error, error="no_rights")
        account = _account(ssh, working, username, exec_fn=exec_fn)
        if not account:
            return OpResult(ok=False, message="Пользователь не существует", error="user_not_found")

        is_root = account["uid"] == 0
        is_current = username == str(working.get("user") or "")
        password_auth = _password_auth_enabled(ssh, working, exec_fn=exec_fn)

        if is_root:
            ok_root, root_error = _root_mutation_gate(ssh, working, username, root_password or "")
            if not ok_root:
                return OpResult(
                    ok=False,
                    message="Требуется подтверждение паролем root (реальный вход)",
                    error="root_password_required",
                    data={"root_password_verified": False, "detail": root_error},
                )

        # Ключи, которые останутся, считаем до мутации.
        ssh_dir, auth_keys = _user_authorized_keys_path(ssh, working, account, exec_fn=exec_fn)
        if not auth_keys:
            return OpResult(ok=False, message="Домашний каталог пользователя не найден", error="home_not_found")
        content = _read_authorized_keys(ssh, working, auth_keys, exec_fn=exec_fn)
        parsed_keys = []
        if content:
            for raw in content.splitlines():
                parsed = _parse_pubkey_line(raw.decode("utf-8", errors="replace").strip())
                if parsed:
                    parsed_keys.append(parsed)
        target = next((k for k in parsed_keys if k["fingerprint"] == fingerprint), None)
        if target is None:
            return OpResult(ok=False, message="Ключ с таким fingerprint не найден", error="key_not_found")
        remaining = len(parsed_keys) - 1

        route_uses_key = is_current and _active_route_uses_fingerprint(working, fingerprint)
        # Записанный «Выбрать ключ» key_path: при удалении этого ключа
        # запись затирается, чтобы статус не показывал «прописан»
        # для несуществующего на сервере ключа.
        recorded_key = is_current and _recorded_key_matches_fingerprint(
            working, fingerprint
        )

        if (is_root or is_current) and route_uses_key:
            # Удаляем ключ, которым подключается сам Bot4VPS.
            if not password_auth:
                return OpResult(
                    ok=False,
                    message=(
                        "Нельзя удалить ключ, по которому Bot4VPS подключается к серверу, "
                        "пока password auth запрещён: после удаления не останется рабочего route"
                    ),
                    error="active_route_key_protected",
                )
            password = working.get("password")
            if not isinstance(password, str) or not password:
                return OpResult(
                    ok=False,
                    message=(
                        "Пароль текущего пользователя не сохранён в Bot4VPS — "
                        "нельзя безопасно переключиться на password-auth перед удалением ключа"
                    ),
                    error="no_password_route",
                )
            candidate = {**working, "auth_type": "password", "password": password}
            # sudo обязателен, только если был доступен (восстановительный
            # password-роут валиден и без sudo — главное, что вход работает).
            verified, verify_error = _verify_login_and_optional_sudo(
                candidate, require_sudo=sudo_ok
            )
            if not verified:
                return OpResult(
                    ok=False,
                    message="Пароль не подтверждён реальным входом; ключ не удаляем",
                    error=verify_error,
                    data={"switch_verified": False},
                )
            try:
                compare_and_set_server_connection(
                    working["id"],
                    {"auth_type": "password", "key_path": None},
                    expected_connection=expected,
                )
            except ConnectionStateConflictError as exc:
                return OpResult(
                    ok=False,
                    message="SSH-настройки были изменены параллельно; ключ не удалён",
                    error=str(exc)[:500],
                )
        elif (is_root or is_current) and remaining == 0:
            # Последний ключ защищённого пользователя.
            if not password_auth:
                return OpResult(
                    ok=False,
                    message=(
                        "Это последний SSH-ключ пользователя, а password auth запрещён. "
                        "Удаление заблокировано: должен остаться хотя бы один рабочий способ входа."
                    ),
                    error="last_key_protected",
                )
            # password auth разрешён — восстановимый путь есть, разрешаем.
            # Для root пароль уже проверен реальным входом выше.
            if is_current and not route_uses_key and str(working.get("auth_type") or "") != "password":
                password = working.get("password")
                if not isinstance(password, str) or not password:
                    return OpResult(
                        ok=False,
                        message=(
                            "Пароль текущего пользователя не сохранён в Bot4VPS — "
                            "нельзя проверить password-путь перед удалением последнего ключа"
                        ),
                        error="no_password_route",
                    )
                candidate = {**working, "auth_type": "password", "password": password}
                verified, verify_error = _verify_login_and_optional_sudo(
                    candidate, require_sudo=sudo_ok
                )
                if not verified:
                    return OpResult(
                        ok=False,
                        message="Пароль не подтверждён реальным входом; ключ не удаляем",
                        error=verify_error,
                        data={"switch_verified": False},
                    )

        snapshot, removed, remove_error, remaining_after = _remove_pubkey_line(
            ssh, working, account, fingerprint, exec_fn=exec_fn, sudo=sudo_ok
        )
        if not removed:
            return OpResult(ok=False, message=remove_error or "Ключ не удалён", error="remove_failed")

        # Ключа на сервере у пользователя больше нет — вычёркиваем из реестра.
        key_registry.forget(str(working.get("id") or ""), username, fingerprint)

        # Записанный key_path указывал на удалённый ключ (роут при этом
        # password): запись затирается отдельным CAS-патчем. Ключ с сервера
        # уже удалён, поэтому конфликт CAS не отменяет операцию — устаревшая
        # запись (если survived) будет помечена статусом get_status.
        key_path_cleared = bool(route_uses_key and password_auth)
        if recorded_key and not route_uses_key:
            try:
                compare_and_set_server_connection(
                    working["id"], {"key_path": None}, expected_connection=expected
                )
                key_path_cleared = True
            except ConnectionStateConflictError:
                key_path_cleared = False

        return OpResult(
            ok=True,
            message=f"Ключ {fingerprint[:20]}… удалён у пользователя {username}",
            data={
                "user": username,
                "fingerprint": fingerprint,
                "remaining_keys": remaining_after,
                "switched_to_password": bool(route_uses_key and password_auth),
                "key_path_cleared": key_path_cleared,
            },
        )
    except Exception as exc:
        rollback = None
        if ssh is not None and snapshot is not None:
            try:
                restore_file(ssh, working, snapshot, sudo=sudo_ok)
                rollback = {"ok": True}
            except Exception as rollback_exc:
                rollback = {"ok": False, "error": str(rollback_exc)[:500]}
        return OpResult(
            ok=False,
            message="Ошибка удаления ключа",
            error=str(exc)[:800],
            data={"rollback": rollback} if rollback is not None else None,
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def set_user_password(
    server: dict,
    username: str,
    new_password: str,
    *,
    old_password: Optional[str] = None,
) -> OpResult:
    """Сменить пароль произвольного пользователя с проверкой реальным входом.

    Для текущего пользователя Bot4VPS делегирует change_password (полная
    транзакция с откатом; root-активный — без дополнительных вопросов).
    Для root (не активного) требуется старый пароль: он проверяется реальным
    SSH-входом до мутации; при неудачной проверке нового пароля — откат на
    старый.
    """
    try:
        username = _valid_username(username)
    except ValueError as exc:
        return OpResult(ok=False, message=str(exc), error="bad_username")
    if not isinstance(new_password, str) or not 6 <= len(new_password) <= 256:
        return OpResult(ok=False, message="Пароль должен содержать 6–256 символов", error="weak_password")
    if any(char in new_password for char in ("\x00", "\r", "\n")):
        return OpResult(ok=False, message="Пароль содержит недопустимые символы", error="bad_password")
    ssh = None
    try:
        # Для текущего пользователя — готовая полная транзакция с откатом.
        if username == str((server.get("user") or "").strip()):
            return change_password(server, new_password)
        working, _ = _fresh_server(server)
        ssh = create_ssh_client(working, timeout=15)
        rights_ok, rights_error = _manager_rights_ok(ssh, working)
        if not rights_ok:
            return OpResult(ok=False, message=rights_error, error="no_rights")
        account = _account(ssh, working, username)
        if not account:
            return OpResult(ok=False, message="Пользователь не существует", error="user_not_found")

        # root (не активный): старый пароль обязателен и проверяется реальным
        # входом до мутации — защита не только кнопкой в UI.
        is_root = account["uid"] == 0
        if is_root:
            if not isinstance(old_password, str) or not old_password:
                return OpResult(
                    ok=False,
                    message="Для смены пароля root требуется старый пароль (проверка реальным входом)",
                    error="old_password_required",
                )
            old_ok, old_error = _verify_root_password(working, old_password)
            if not old_ok:
                return OpResult(
                    ok=False,
                    message="Старый пароль root не подтвердился реальным входом; пароль не изменён",
                    error="old_password_invalid",
                    data={"detail": old_error},
                )

        changed, detail = _set_remote_password(ssh, working, username, new_password)
        if not changed:
            return OpResult(ok=False, message="Не удалось сменить пароль", error=detail)

        login_verified = False
        verify_note = ""
        password_auth = _password_auth_enabled(ssh, working)
        if not account["login_capable"]:
            verify_note = "вход отключён shell-политикой, пароль установлен без проверки входа"
        elif is_root:
            # Для root проверяем так же, как проверяли старый: реальным входом.
            new_ok, new_error = _verify_root_password(working, new_password)
            if not new_ok:
                rollback, rollback_error = _set_remote_password(
                    ssh, working, username, old_password
                )
                return OpResult(
                    ok=False,
                    message=(
                        "Новый пароль root не подтвердился входом; прежний пароль восстановлен"
                        if rollback
                        else "Новый пароль root не подтвердился входом; требуется ручная проверка"
                    ),
                    error=new_error,
                    data={"rollback": {"attempted": True, "ok": rollback, "error": rollback_error}},
                )
            login_verified = True
        elif password_auth:
            candidate = {
                **working,
                "user": username,
                "auth_type": "password",
                "password": new_password,
            }
            try:
                probe = create_ssh_client(candidate, timeout=15)
                probe.close()
                login_verified = True
            except Exception as exc:
                return OpResult(
                    ok=False,
                    message=(
                        "Пароль изменён, но SSH-вход новым паролем не подтвердился. "
                        "Старый пароль неизвестен Bot4VPS — откат невозможен, проверьте доступ вручную."
                    ),
                    error=str(exc)[:500],
                    data={"login_verified": False},
                )
        else:
            verify_note = "password auth запрещён на сервере, вход новым паролем не проверялся"

        message = f"Пароль пользователя {username} обновлён"
        if login_verified:
            message += ", SSH-вход подтверждён"
        elif verify_note:
            message += f" ({verify_note})"
        return OpResult(
            ok=True,
            message=message,
            data={"user": username, "login_verified": login_verified},
        )
    except Exception as exc:
        return OpResult(ok=False, message="Ошибка смены пароля", error=str(exc)[:800])
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def switch_user(
    server: dict,
    username: str,
    *,
    password: Optional[str] = None,
    key_path: Optional[str] = None,
    allow_without_sudo: bool = False,
) -> OpResult:
    """Проверить существующий аккаунт, SSH/sudo и только затем CAS-переключить.

    Маршрут входа выбирается только явно и меняет auth_type в servers.json:
    ``key_path`` → key-роут, ``password`` → password-роут. Записанный роут
    текущего пользователя на цель не распространяется. Пароль при key-роуте —
    sudo-credential цели (auth_type остаётся key).

    sudo обязателен по умолчанию. Если вход выполнен, а sudo — нет,
    переключение возможно только после явного подтверждения
    (``allow_without_sudo=True``): проверка всё равно выполняется, но
    неудачный sudo не блокирует сохранение.

    Исключение — sudo-gate: key-переключение с sudo-less текущего на
    sudo/root-аккаунт требует верный пароль цели (sudo_password_required /
    sudo_password_invalid), подтверждение ``allow_without_sudo`` гейт не
    обходит. Для root пароль дополнительно проверяется реальным
    password-входом (sudo-проба root пароль не проверяет)."""

    try:
        username = _valid_username(username)
    except ValueError as exc:
        return OpResult(ok=False, message=str(exc), error="bad_username")
    if password is not None:
        if not isinstance(password, str) or not 1 <= len(password) <= 256:
            return OpResult(ok=False, message="Пароль должен содержать 1–256 символов", error="bad_password")
        if any(char in password for char in ("\x00", "\r", "\n")):
            return OpResult(ok=False, message="Пароль содержит недопустимые символы", error="bad_password")

    ssh = None
    try:
        working, expected = _fresh_server(server)
        # Контрольное подключение текущим роутом. При password-роуте оно
        # работает всегда; при key-роуте ключ может быть мёртв на сервере —
        # тогда предпроверки пропускаются, всё решит проверка цели.
        try:
            ssh = create_ssh_client(working, timeout=15)
        except Exception:
            ssh = None
        # Сначала резолвим исполнитель контроля (для не-root — ОДНА
        # sudo-проба). getent привилегий не требует: при sudo-less он
        # пойдёт через exec_plain, без заведомо неудачной sudo-пробы
        # (каждый провал sudo = ~2 c PAM-задержки на сервере).
        # Предпроверка через контрольное подключение опциональна: без sudo
        # у текущего пользователя часть команд недоступна, но обязательная
        # проверка цели от неё не зависит — несуществующий пользователь
        # не пройдёт реальный SSH-вход отдельным подключением.
        account_precheck_skipped = ssh is None
        account = None
        ctrl_exec = None
        ctrl_sudo_ok = False
        if ssh is not None:
            try:
                ctrl_exec, ctrl_sudo = _resolve_exec(ssh, working)
                ctrl_sudo_ok = ctrl_sudo
                _sync_key_registry(ssh, working, ctrl_exec, ctrl_sudo)
            except Exception:
                ctrl_exec = None
        if ssh is not None:
            try:
                account = _account(
                    ssh, working, username, exec_fn=ctrl_exec or exec_sudo
                )
            except RuntimeError:
                account_precheck_skipped = True
                account = None
        if account is None and not account_precheck_skipped:
            return OpResult(ok=False, message="Пользователь не существует", error="user_not_found")
        if account and not account["login_capable"]:
            return OpResult(ok=False, message="Учётная запись не допускает SSH-вход", error="login_disabled")

        # Маршрут выбирается ТОЛЬКО явно: key_path → key-кандидат,
        # password → password-кандидат. Это единственное место, где
        # меняется auth_type в servers.json (выбор «Авторизоваться по»
        # в блоке переключения). Записанный роут текущего пользователя
        # на цель НЕ распространяется: его ключ принадлежит ему, а не
        # цели переключения. sshd-проверки — только верификация.
        current_auth = str(working.get("auth_type") or "password")

        if key_path is not None:
            try:
                validated_key_path = _validated_private_key_path(key_path)
            except ValueError as exc:
                return OpResult(
                    ok=False,
                    message=f"Выбранный локальный ключ недоступен: {exc}",
                    error="bad_key_path",
                )
            key_route = True
            candidate = {
                **working,
                "user": username,
                "auth_type": "key",
                "key_path": validated_key_path,
                "password": password or "",
            }
            # Пароль при key-роуте — sudo-credential цели (назначение
            # password в servers.json не меняется: sudo-cred при любом
            # auth_type, SSH-аутентификация — только при password).
            patch: dict[str, Any] = {
                "user": username,
                "auth_type": "key",
                "key_path": validated_key_path,
                "password": password or "",
            }
            auth_label = "выбранный локальный ключ Bot4VPS"
        elif password is not None:
            key_route = False
            candidate = {
                **working,
                "user": username,
                "auth_type": "password",
                "password": password,
                "key_path": None,
            }
            # key_path принадлежал прежнему пользователю: при password-роуте
            # он затирается, чтобы не вводить в заблуждение.
            patch: dict[str, Any] = {"user": username, "auth_type": "password", "password": password, "key_path": None}
            auth_label = "пароль целевого пользователя"
        else:
            return OpResult(
                ok=False,
                message="Укажите пароль целевого пользователя или выберите SSH-ключ",
                error="credentials_required",
            )

        # Проверка цели — ОДНО SSH-соединение: вход, sudo-проба и (для
        # sudo-gate) uid/группы читаются в одной сессии без повторного
        # handshake/login к той же цели.
        # collect_info: sudo-gate возможен только при ключ-роуте без sudo
        # у текущего пользователя — заранее готовим id-группы цели.
        need_target_info = key_route and not ctrl_sudo_ok
        login_ok, sudo_ok, target_info, verify_error = _verify_target(
            candidate, collect_info=need_target_info
        )
        if not login_ok:
            return OpResult(
                ok=False,
                message=f"SSH-вход как {username} не выполнен; servers.json не изменён",
                error=verify_error,
                data={"login_verified": False, "sudo_verified": False},
            )

        # sudo-gate: ключ-переключение на sudo/root-аккаунт с sudo-less
        # текущего — эскалация. Требуем верный пароль цели: он проверяется
        # (sudo-пробой / password-логином) и записывается как sudo-cred,
        # auth_type остаётся key. Неверный/пустой пароль — жёсткий отказ
        # (allow_without_sudo гейт не обходит). Не применяется, если цель
        # без sudo, текущий пользователь сам с sudo или проверить цель
        # не удалось. Для root гейт работает даже при успешной sudo-пробе:
        # root не вводит пароль для sudo, проба пароль не проверяет.
        if need_target_info:
            if target_info and target_info["sudo_capable"]:
                if target_info["is_root"]:
                    if not password:
                        return OpResult(
                            ok=False,
                            message=(
                                "Вы переподключаетесь на учётную запись суперпользователя "
                                "(root): введите пароль root"
                            ),
                            error="sudo_password_required",
                            data={
                                "login_verified": True,
                                "sudo_verified": sudo_ok,
                                "sudo_gate": True,
                            },
                        )
                    # sudo-проба root пароль не проверяет — проверяем
                    # реальным password-входом.
                    root_pw_ok, _, root_pw_error = _probe_login_and_sudo(
                        {**candidate, "auth_type": "password"}
                    )
                    if not root_pw_ok:
                        return OpResult(
                            ok=False,
                            message=(
                                "Пароль root не подтверждён (неверен или "
                                "password-авторизация на сервере выключена); "
                                "переключение запрещено"
                            ),
                            error="sudo_password_invalid",
                            data={
                                "login_verified": True,
                                "sudo_verified": sudo_ok,
                                "sudo_gate": True,
                                "detail": root_pw_error,
                            },
                        )
                elif not sudo_ok:
                    if not password:
                        return OpResult(
                            ok=False,
                            message=(
                                f"Вы переподключаетесь на учётную запись суперпользователя "
                                f"({username}): введите пароль этого пользователя"
                            ),
                            error="sudo_password_required",
                            data={
                                "login_verified": True,
                                "sudo_verified": False,
                                "sudo_gate": True,
                            },
                        )
                    # sudo-проба уже пробовала введённый пароль как sudo-cred
                    # и не прошла — пароль неверен (или sudoers не пускает).
                    return OpResult(
                        ok=False,
                        message=(
                            f"Пароль пользователя {username} не подошёл; "
                            "переключение на учётную запись суперпользователя запрещено"
                        ),
                        error="sudo_password_invalid",
                        data={
                            "login_verified": True,
                            "sudo_verified": False,
                            "sudo_gate": True,
                        },
                    )

        if not sudo_ok and not allow_without_sudo:
            sudo_reason = (
                "sudo недоступен — вероятно, неверный пароль целевого пользователя"
                if key_route
                else "sudo не подтверждён"
            )
            return OpResult(
                ok=False,
                message=(
                    f"SSH-вход как {username} выполнен, но {sudo_reason}; "
                    "переключение возможно только с явным подтверждением"
                ),
                error="sudo_not_verified",
                data={
                    "login_verified": True,
                    "sudo_verified": False,
                    "confirmation_required": True,
                },
            )
        try:
            compare_and_set_server_connection(
                working["id"], patch, expected_connection=expected
            )
        except ConnectionStateConflictError as exc:
            return OpResult(
                ok=False,
                message="SSH-настройки были изменены параллельно; переключение не сохранено",
                error=str(exc)[:500],
                data={"login_verified": True, "sudo_verified": sudo_ok},
            )
        # key-роут закоммичен: реальный вход этим ключом доказывает, что
        # ключ лежит в authorized_keys нового пользователя — фиксируем
        # занятость в реестре (password-роут реестр не меняет).
        if candidate.get("auth_type") == "key" and candidate.get("key_path"):
            switched_fp = _local_key_fingerprint(str(candidate["key_path"]))
            if switched_fp:
                key_registry.record(str(working.get("id") or ""), username, switched_fp)
        if sudo_ok:
            message = f"Bot4VPS переключён на {username}; SSH-вход и sudo подтверждены"
        else:
            message = (
                f"Bot4VPS переключён на {username}; SSH-вход подтверждён, "
                "sudo отсутствует — административные операции недоступны"
            )
        return OpResult(
            ok=True,
            message=message,
            data={
                "user": username,
                "auth_type": candidate.get("auth_type") or current_auth,
                "auth_context": auth_label,
                "login_verified": True,
                "sudo_verified": sudo_ok,
                "account_precheck_skipped": account_precheck_skipped,
            },
        )
    except Exception as exc:
        return OpResult(ok=False, message="Ошибка переключения пользователя", error=str(exc)[:800])
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def delete_user(server: dict, username: str, *, remove_home: bool = False) -> OpResult:
    """Удалить только отдельный непривилегированный login-account."""
    try:
        username = _valid_username(username)
    except ValueError as exc:
        return OpResult(ok=False, message=str(exc), error="bad_username")
    if username == "root":
        return OpResult(ok=False, message="Пользователя root удалить нельзя", error="root_protected")

    ssh = None
    try:
        working, _ = _fresh_server(server)
        current = str(working.get("user") or "")
        if username == current:
            return OpResult(
                ok=False,
                message="Нельзя удалить текущего пользователя Bot4VPS. Сначала переключитесь на другой проверенный аккаунт.",
                error="current_user_protected",
            )
        current_ok, current_error = _verify_login_and_sudo(working)
        if not current_ok:
            return OpResult(
                ok=False,
                message="Текущий SSH/sudo route не подтверждён — удаление заблокировано",
                error=current_error,
            )
        ssh = create_ssh_client(working, timeout=15)
        account = _account(ssh, working, username)
        if not account:
            return OpResult(ok=False, message="Пользователь не существует", error="user_not_found")
        if account["uid"] == 0 or account["uid"] < 1000:
            return OpResult(ok=False, message="Системную учётную запись удалить нельзя", error="system_user_protected")
        if not account["login_capable"]:
            return OpResult(ok=False, message="Удаление non-login аккаунтов через Quick Setup запрещено", error="non_login_protected")

        flag = "-r " if remove_home else ""
        code, out, err = exec_sudo(
            ssh,
            working,
            f"userdel {flag}-- {shlex.quote(username)}",
            timeout=40,
        )
        if code != 0:
            return OpResult(
                ok=False,
                message="Не удалось удалить пользователя",
                error=(err or out or f"exit {code}")[:800],
            )
        if _account(ssh, working, username) is not None:
            return OpResult(
                ok=False,
                message="Команда завершилась, но пользователь всё ещё существует",
                error="delete_not_verified",
            )
        # Пользователя на сервере больше нет — вычёркиваем его ключи из реестра.
        key_registry.forget_user(str(working.get("id") or ""), username)
        final_ok, final_error = _verify_login_and_sudo(working)
        if not final_ok:
            return OpResult(
                ok=False,
                message="Пользователь удалён, но текущий route требует ручной проверки",
                error=final_error,
                data={"deleted": True, "current_route_verified": False},
            )
        return OpResult(
            ok=True,
            message=f"Пользователь {username} удалён" + (" вместе с домашним каталогом" if remove_home else ""),
            data={
                "user": username,
                "deleted": True,
                "home_removed": bool(remove_home),
                "current_route_verified": True,
            },
        )
    except Exception as exc:
        return OpResult(ok=False, message="Ошибка удаления пользователя", error=str(exc)[:800])
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass
