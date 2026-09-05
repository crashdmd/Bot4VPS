# -*- coding: utf-8 -*-
"""Fail2ban: статус, установка, настройки SSH jail через конфиг, ban list, restart.

Настройки пишутся в /etc/fail2ban/jail.d/bot4vps-sshd.local — не одной shell-командой.
"""
from __future__ import annotations

import ipaddress
import re
import shlex
from typing import Any, Callable, Optional

from core.ssh import create_ssh_client, exec_sudo

from .models import Fail2banStatus, OpResult
from .package_manager import detect as detect_package_manager
from .remote_files import (
    RemoteFileSnapshot,
    atomic_write,
    restore_file,
    snapshot_file,
)

_JAIL_ROOT = "/etc/fail2ban"
_JAIL_DIR = f"{_JAIL_ROOT}/jail.d"
_FILTER_DIR = f"{_JAIL_ROOT}/filter.d"
_JAIL_LOCAL = f"{_JAIL_DIR}/bot4vps-sshd.local"
_WHITELIST_LOCAL = f"{_JAIL_DIR}/bot4vps-whitelist.local"
_JAILS_LOCAL = f"{_JAIL_DIR}/bot4vps-jails.local"
_JAIL_NAME = "sshd"
_PACKAGE_NAME = "fail2ban"
_MAX_DETAIL = 2000
_MAX_ITEMS = 200
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(?:conf|local)$")


def _parse_time_token(raw: str) -> Optional[str]:
    s = (raw or "").strip()
    if not s or s == "-":
        return None
    return s


def _close(ssh) -> None:
    if ssh:
        try:
            ssh.close()
        except Exception:
            pass




def _bounded(value: Any, limit: int = _MAX_DETAIL) -> str:
    text = str(value or "")
    return "".join(ch if ch >= " " or ch == "\t" else " " for ch in text)[:limit]


def _exec(ssh, server: dict, command: str, timeout: int = 30) -> tuple[int, str, str]:
    code, out, err = exec_sudo(ssh, server, command, timeout=timeout)
    return int(code), _bounded(out, 6000), _bounded(err)


def _failure(code: int, out: str, err: str) -> str:
    return _bounded(err or out or f"exit {code}")


def _detail(code: int, out: str, err: str) -> str:
    """Совместимый bounded detail для lifecycle-команд."""
    return _failure(code, _bounded(out, 6000), _bounded(err))


def _status_dict(status: Fail2banStatus) -> dict:
    return {
        "installed": status.installed,
        "running": status.running,
        "autostart": status.autostart,
        "state": status.state,
        "ssh_jail_enabled": status.ssh_jail_enabled,
        "ban_time": status.ban_time,
        "find_time": status.find_time,
        "max_retry": status.max_retry,
        "banned_count": status.banned_count,
        "jail_count": status.jail_count,
        "config_present": status.config_present,
        "label": status.label,
        "error": status.error,
    }


def _effective(ssh, server: dict, jail: str, key: str) -> Optional[str]:
    jail = _valid_name(jail, "имя jail")
    if key not in {"bantime", "findtime", "maxretry"}:
        raise ValueError("Некорректный параметр jail")
    code, out, _ = _exec(
        ssh,
        server,
        f"fail2ban-client get {shlex.quote(jail)} {key} 2>/dev/null",
        15,
    )
    if code != 0:
        return None
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    return lines[-1] if lines else None


def _jail_info(ssh, server: dict, jail: str) -> tuple[bool, str, dict]:
    jail = _valid_name(jail, "имя jail")
    code, out, err = _exec(
        ssh,
        server,
        f"fail2ban-client status {shlex.quote(jail)} 2>/dev/null",
        20,
    )
    if code != 0:
        return False, _failure(code, out, err), {"banned": 0, "ips": []}
    count_match = re.search(r"Currently banned:\s*(\d+)", out, re.I)
    list_match = re.search(r"Banned IP list\s*:\s*(.*)", out, re.I)
    ips: list[str] = []
    if list_match:
        for raw in list_match.group(1).split():
            try:
                value = str(ipaddress.ip_address(raw.strip()))
            except ValueError:
                continue
            if value not in ips:
                ips.append(value)
            if len(ips) >= _MAX_ITEMS:
                break
    banned = int(count_match.group(1)) if count_match else len(ips)
    return True, "", {"banned": min(banned, 1000000), "ips": ips}


def _valid_name(value: str, label: str = "имя") -> str:
    name = str(value or "").strip()
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"Некорректное {label}")
    return name


def _valid_filename(value: str) -> str:
    name = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name):
        raise ValueError("Некорректное имя файла")
    if not (name.endswith(".conf") or name.endswith(".local")):
        raise ValueError("Разрешены только файлы .conf и .local")
    return name


def _duration(value: Optional[str], label: str) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    if not re.fullmatch(r"[1-9][0-9]{0,8}(?:s|m|h|d|w)?", value, re.I):
        raise ValueError(f"Некорректный {label}")
    return value


def _retry(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Max retries должен быть от 1 до 100") from exc
    if not 1 <= value <= 100:
        raise ValueError("Max retries должен быть от 1 до 100")
    return value


def _normalize_ip(value: str) -> str:
    value = str(value or "").strip()
    try:
        if "/" in value:
            return str(ipaddress.ip_network(value, strict=False))
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise ValueError("Некорректный IP-адрес или CIDR") from exc


def _normalize_address(value: str) -> str:
    value = str(value or "").strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise ValueError("Некорректный IP-адрес") from exc


def _parse_ip_tokens(value: str) -> list[str]:
    result: list[str] = []
    for raw in re.split(r"[\s,]+", str(value or "")):
        candidate = raw.strip("[](){}|'\";`")
        if not candidate:
            continue
        try:
            normalized = _normalize_ip(candidate)
        except ValueError:
            continue
        if normalized not in result:
            result.append(normalized)
        if len(result) >= _MAX_ITEMS:
            break
    return result


def _managed_whitelist_entries(content: bytes | str) -> list[str]:
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="replace")
    else:
        text = str(content or "")
    section = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        section_match = re.fullmatch(r"\[([^\]]+)\]", line)
        if section_match:
            section = section_match.group(1).strip().lower()
            continue
        if section != "default":
            continue
        value_match = re.match(r"ignoreip\s*=\s*(.*)$", line, re.I)
        if value_match:
            return _parse_ip_tokens(value_match.group(1).split("#", 1)[0])
    return []


def _effective_whitelist(
    ssh,
    server: dict,
    *,
    strict: bool = False,
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    jails = _active_jails(ssh, server)
    if strict and not jails:
        raise RuntimeError("Нет активных Правила блокировки для проверки эффективного Whitelist")
    for jail in jails:
        code, out, err = _exec(
            ssh,
            server,
            f"fail2ban-client get {shlex.quote(jail)} ignoreip 2>/dev/null",
            20,
        )
        if code != 0:
            if strict:
                raise RuntimeError(
                    f"Не удалось проверить Whitelist jail {jail}: "
                    f"{_failure(code, out, err)}"
                )
            continue
        for value in _parse_ip_tokens(out):
            result.setdefault(value, []).append(jail)
            if len(result) >= _MAX_ITEMS:
                return result
    return result


def _duration_seconds(value: Any) -> Optional[int]:
    match = re.fullmatch(r"([1-9][0-9]{0,8})([smhdw]?)", str(value or "").strip(), re.I)
    if not match:
        return None
    multipliers = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    return int(match.group(1)) * multipliers[match.group(2).lower()]


def _effective_matches(key: str, wanted: Any, actual: Any) -> bool:
    if key in {"bantime", "findtime"}:
        wanted_seconds = _duration_seconds(wanted)
        actual_seconds = _duration_seconds(actual)
        return wanted_seconds is not None and wanted_seconds == actual_seconds
    if key == "maxretry":
        try:
            return int(wanted) == int(str(actual).strip())
        except (TypeError, ValueError):
            return False
    return str(wanted).strip() == str(actual).strip()


def _validate_reload(ssh, server: dict) -> tuple[bool, str]:
    code, out, err = _exec(ssh, server, "fail2ban-client -t", 30)
    if code != 0:
        return False, _failure(code, out, err)
    code, out, err = _exec(ssh, server, "fail2ban-client reload", 45)
    if code != 0:
        return False, _failure(code, out, err)
    running, _, detail = _service_state(ssh, server)
    if not running:
        return False, detail or "Fail2ban не подтвердил active/ping после reload"
    return True, ""


class _NoMutationError(RuntimeError):
    """Операция остановлена до изменения управляемого файла."""


def _snapshot_matches(left, right) -> bool:
    if left.path != right.path or left.existed != right.existed:
        return False
    if not left.existed:
        return True
    return (
        left.content == right.content
        and left.mode == right.mode
        and left.uid == right.uid
        and left.gid == right.gid
    )


def _file_transaction(
    ssh,
    server: dict,
    snapshot,
    apply: Callable[[], None],
    *,
    verify: Optional[Callable[[], None]] = None,
) -> tuple[bool, str, dict]:
    details: dict[str, Any] = {
        "path": snapshot.path,
        "rollback": False,
        "stage": "apply",
    }
    try:
        apply()
        details["stage"] = "validate_reload"
        ok, detail = _validate_reload(ssh, server)
        if not ok:
            raise RuntimeError(detail)
        details["stage"] = "verify"
        if verify is not None:
            verify()
        details["stage"] = "verified"
        return True, "", details
    except _NoMutationError as exc:
        details["no_change"] = True
        return False, _bounded(exc), details
    except Exception as exc:
        failed_stage = details["stage"]
        rollback_error = ""
        try:
            restore_file(ssh, server, snapshot)
            restored = snapshot_file(ssh, server, snapshot.path)
            if not _snapshot_matches(snapshot, restored):
                raise RuntimeError("Точное восстановление файла не подтверждено")
            rollback_ok, rollback_detail = _validate_reload(ssh, server)
            if not rollback_ok:
                rollback_error = rollback_detail
        except Exception as rollback_exc:
            rollback_error = _bounded(rollback_exc)
        details["stage"] = failed_stage
        details["rollback"] = not rollback_error
        if rollback_error:
            details["rollback_error"] = rollback_error
        return False, _bounded(exc), details


def _package_state(ssh, server: dict):
    """Вернуть (installed, package_manager, error) через общий gateway."""
    try:
        package_manager = detect_package_manager(ssh, server)
        return (
            package_manager.is_installed(ssh, server, _PACKAGE_NAME),
            package_manager,
            None,
        )
    except Exception as exc:
        # Старые/минимальные системы могут иметь рабочий binary без доступного
        # package manager. Это подтверждает наличие, но не позволяет install/remove.
        code, _, _ = exec_sudo(
            ssh,
            server,
            "command -v fail2ban-client >/dev/null 2>&1",
            timeout=15,
        )
        return code == 0, None, str(exc)[:800]


def _service_state(ssh, server: dict) -> tuple[bool, bool, str]:
    code_active, out_active, err_active = exec_sudo(
        ssh,
        server,
        "systemctl is-active fail2ban 2>/dev/null",
        timeout=15,
    )
    active_line = (out_active or "").strip().splitlines()
    running = code_active == 0 and bool(active_line) and active_line[0].strip() == "active"

    code_enabled, out_enabled, _ = exec_sudo(
        ssh,
        server,
        "systemctl is-enabled fail2ban 2>/dev/null",
        timeout=15,
    )
    enabled_line = (out_enabled or "").strip().splitlines()
    autostart = (
        code_enabled == 0
        and bool(enabled_line)
        and enabled_line[0].strip() == "enabled"
    )

    ping_ok = False
    ping_error = ""
    if running:
        code_ping, out_ping, err_ping = exec_sudo(
            ssh,
            server,
            "fail2ban-client ping 2>/dev/null",
            timeout=15,
        )
        ping_ok = code_ping == 0 and "pong" in (out_ping or "").lower()
        if not ping_ok:
            ping_error = _detail(code_ping, out_ping, err_ping)
    error = ping_error
    if code_active not in (0, 3) and not error:
        error = _detail(code_active, out_active, err_active)
    return running and ping_ok, autostart, error


def _active_jails(ssh, server: dict) -> list[str]:
    code, out, _ = exec_sudo(
        ssh,
        server,
        "fail2ban-client status 2>/dev/null",
        timeout=20,
    )
    if code != 0:
        return []
    match = re.search(r"Jail list\s*:\s*(.*)", out or "", re.I)
    if not match:
        return []
    names: list[str] = []
    for name in re.split(r"[,\s]+", match.group(1).strip()):
        if _NAME_RE.fullmatch(name or "") and name not in names:
            names.append(name)
    return names[:_MAX_ITEMS]


def _jail_sections(content: bytes | str) -> list[str]:
    """Извлечь только безопасные имена jail из ограниченного config snapshot."""
    text = (
        content.decode("utf-8", errors="replace")
        if isinstance(content, bytes)
        else str(content or "")
    )
    names: list[str] = []
    for raw_line in text.splitlines():
        match = re.match(r"^\s*\[([^\]]+)]\s*(?:[#;].*)?$", raw_line)
        if not match:
            continue
        name = match.group(1).strip()
        if name.upper() in {"DEFAULT", "INCLUDES"}:
            continue
        if _NAME_RE.fullmatch(name) and name not in names:
            names.append(name)
        if len(names) >= _MAX_ITEMS:
            break
    return names


# Managed-файл для включения/выключения правил, кроме sshd (sshd живёт в
# bot4vps-sshd.local и управляется настройками защиты). jail.d/*.local читается
# fail2ban последним и переопределяет jail.conf/jail.local — это штатный
# механизм включения, сам jail.conf не редактируется.
_MANAGED_HEADER = "# Managed by Bot4VPS Quick Setup"

# jail -> (кандидаты бинарников сервиса, кандидаты путей логов).
# Только реальные имена стоковых jail fail2ban; остальное — unknown (ручная
# настройка). sendmail-* намеренно отсутствует: бинарник sendmail входит в
# postfix/exim и даёт ложную доступность.
_JAIL_SERVICE_PROBES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "nginx-bad-request": (("nginx",), ("/var/log/nginx/error.log", "/var/log/nginx/access.log")),
    "nginx-botsearch": (("nginx",), ("/var/log/nginx/error.log", "/var/log/nginx/access.log")),
    "nginx-http-auth": (("nginx",), ("/var/log/nginx/error.log", "/var/log/nginx/access.log")),
    "nginx-limit-req": (("nginx",), ("/var/log/nginx/error.log", "/var/log/nginx/access.log")),
    "apache-auth": (("apache2", "httpd"), ("/var/log/apache2/error.log", "/var/log/httpd/error_log")),
    "apache-badbots": (("apache2", "httpd"), ("/var/log/apache2/access.log", "/var/log/httpd/access_log")),
    "apache-botsearch": (("apache2", "httpd"), ("/var/log/apache2/error.log", "/var/log/httpd/error_log", "/var/log/apache2/access.log", "/var/log/httpd/access_log")),
    "apache-fakegooglebot": (("apache2", "httpd"), ("/var/log/apache2/access.log", "/var/log/httpd/access_log")),
    "apache-modsecurity": (("apache2", "httpd"), ("/var/log/apache2/error.log", "/var/log/httpd/error_log")),
    "apache-nohome": (("apache2", "httpd"), ("/var/log/apache2/access.log", "/var/log/httpd/access_log")),
    "apache-noscript": (("apache2", "httpd"), ("/var/log/apache2/access.log", "/var/log/httpd/access_log")),
    "apache-overflows": (("apache2", "httpd"), ("/var/log/apache2/access.log", "/var/log/httpd/access_log")),
    "apache-shellshock": (("apache2", "httpd"), ("/var/log/apache2/access.log", "/var/log/httpd/access_log")),
    "lighttpd-auth": (("lighttpd",), ("/var/log/lighttpd/error.log", "/var/log/lighttpd/errorlog")),
    "postfix": (("postfix",), ("/var/log/mail.log", "/var/log/maillog")),
    "postfix-rbl": (("postfix",), ("/var/log/mail.log", "/var/log/maillog")),
    "postfix-sasl": (("postfix",), ("/var/log/mail.log", "/var/log/maillog")),
    "dovecot": (("dovecot",), ("/var/log/mail.log", "/var/log/maillog", "/var/log/dovecot.log")),
    "dropbear": (("dropbear",), ("/var/log/auth.log", "/var/log/syslog")),
    "proftpd": (("proftpd",), ("/var/log/proftpd/proftpd.log", "/var/log/auth.log")),
    "pure-ftpd": (("pure-ftpd",), ("/var/log/messages", "/var/log/auth.log", "/var/log/syslog")),
    "vsftpd": (("vsftpd",), ("/var/log/vsftpd.log", "/var/log/messages")),
    "named-refused": (("named",), ("/var/log/named/security.log", "/var/log/messages")),
    "mysqld-auth": (("mysqld", "mariadbd"), ("/var/log/mysql/error.log", "/var/log/mysqld.log")),
    # recidive читает собственный журнал Fail2ban — доступность по logtarget.
}


def _jails_runtime_facts(ssh, server: dict) -> tuple[set[str], set[str], Optional[str]]:
    """Одной командой собрать: существующие бинарники, существующие логи, logtarget.

    Fail2ban не стартует jail без хотя бы одного существующего logpath, поэтому
    доступность определяем по связке «бинарник сервиса + живой лог».
    """
    binaries = sorted({name for pair in _JAIL_SERVICE_PROBES.values() for name in pair[0]})
    logs = sorted({path for pair in _JAIL_SERVICE_PROBES.values() for path in pair[1]})
    script = (
        "for b in " + " ".join(binaries) + "; do command -v \"$b\" >/dev/null 2>&1 && printf 'B %s\\n' \"$b\"; done; "
        "for p in " + " ".join(logs) + "; do [ -f \"$p\" ] && printf 'L %s\\n' \"$p\"; done; "
        "t=$(fail2ban-client get logtarget 2>/dev/null); "
        "target=$(printf '%s\\n' \"$t\" | sed -nE 's#.*(/[^[:space:]`]+).*#\\1#p' | tail -n 1); "
        "printf 'T %s\\n' \"$target\"; "
        "[ -n \"$target\" ] && [ -f \"$target\" ] && printf 'L %s\\n' \"$target\""
    )
    code, out, _ = _exec(ssh, server, script, 20)
    found_binaries: set[str] = set()
    found_logs: set[str] = set()
    logtarget: Optional[str] = None
    for raw_line in (out or "").splitlines():
        line = raw_line.strip()
        if line.startswith("B ") and len(line) > 2:
            found_binaries.add(line[2:].strip())
        elif line.startswith("L ") and len(line) > 2:
            found_logs.add(line[2:].strip())
        elif line.startswith("T "):
            value = line[2:].strip()
            path_match = re.search(r"(/[^\s`]+)", value)
            logtarget = path_match.group(1).rstrip("`") if path_match else (value or None)
    if code != 0 and not found_binaries and not found_logs:
        return set(), set(), logtarget
    return found_binaries, found_logs, logtarget


def _jail_availability(jail: str, found_binaries: set[str], found_logs: set[str], logtarget: Optional[str]) -> str:
    """ok | missing_service | missing_logs | unknown — можно ли включить автоматически."""
    if jail == "recidive":
        if logtarget and logtarget.startswith("/") and logtarget in found_logs:
            return "ok"
        return "missing_logs"
    probe = _JAIL_SERVICE_PROBES.get(jail)
    if probe is None:
        return "unknown"
    binaries, logs = probe
    if not any(name in found_binaries for name in binaries):
        return "missing_service"
    if not any(path in found_logs for path in logs):
        return "missing_logs"
    return "ok"


def _is_bot4vps_jail_source(source_label: str) -> bool:
    """jail.conf и только известные Bot4VPS overlay-файлы считаются нашими."""
    return source_label in {
        "jail.conf",
        "jail.d/bot4vps-sshd.local",
        "jail.d/bot4vps-whitelist.local",
        "jail.d/bot4vps-jails.local",
    }


def _jail_user_sources(sources: list[str]) -> list[str]:
    return [source for source in sources if not _is_bot4vps_jail_source(source)]


def _managed_jail_enabled(content: bytes | str) -> dict[str, bool]:
    """Прочитать карту jail -> enabled из нашего managed-файла правил."""
    text = (
        content.decode("utf-8", errors="replace")
        if isinstance(content, bytes)
        else str(content or "")
    )
    result: dict[str, bool] = {}
    section = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        section_match = re.fullmatch(r"\[([^\]]+)\]", line)
        if section_match:
            section = section_match.group(1).strip()
            continue
        value_match = re.match(r"enabled\s*=\s*(\S+)", line, re.I)
        if value_match and section and _NAME_RE.fullmatch(section) and section not in result:
            result[section] = value_match.group(1).lower() == "true"
    return result


def _render_managed_jails_file(managed: dict[str, bool]) -> str:
    """Детерминированная полная пересборка managed-файла правил."""
    lines = [_MANAGED_HEADER]
    for name in sorted(managed)[:_MAX_ITEMS]:
        lines.append(f"[{name}]")
        lines.append(f"enabled = {'true' if managed[name] else 'false'}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _configured_jails(ssh, server: dict) -> dict[str, list[str]]:
    """Обнаружить jail-секции только в allowlisted regular config files."""
    sources: list[tuple[str, str]] = [
        (f"{_JAIL_ROOT}/jail.conf", "jail.conf"),
        (f"{_JAIL_ROOT}/jail.local", "jail.local"),
    ]
    sources.extend(
        (f"{_JAIL_DIR}/{filename}", f"jail.d/{filename}")
        for filename in _config_files(
            ssh,
            server,
            _JAIL_DIR,
            "\\( -name '*.conf' -o -name '*.local' \\)",
        )
    )

    result: dict[str, list[str]] = {}
    for path, source in sources:
        snapshot = snapshot_file(ssh, server, path)
        if not snapshot.existed:
            continue
        for name in _jail_sections(snapshot.content):
            names = result.setdefault(name, [])
            if source not in names:
                names.append(source)
            if len(result) >= _MAX_ITEMS:
                break
        if len(result) >= _MAX_ITEMS:
            break
    return result


def _config_present(ssh, server: dict) -> bool:
    code, _, _ = exec_sudo(
        ssh,
        server,
        "test -d /etc/fail2ban && test ! -L /etc/fail2ban && "
        "find -P /etc/fail2ban -maxdepth 2 -type f -links 1 "
        "\\( -name '*.conf' -o -name '*.local' \\) -print -quit | grep -q .",
        timeout=15,
    )
    return code == 0


def _status_with_ssh(ssh, server: dict) -> Fail2banStatus:
    st = Fail2banStatus()
    installed, _, package_error = _package_state(ssh, server)
    st.installed = installed
    st.config_present = _config_present(ssh, server)
    if not installed:
        st.state = "absent"
        st.label = "Не установлен"
        return st

    st.running, st.autostart, service_error = _service_state(ssh, server)
    st.state = "running" if st.running else "stopped"
    st.label = "Запущен" if st.running else "Остановлен"
    if service_error:
        st.error = service_error[:_MAX_DETAIL]

    if not st.running:
        return st

    jails = _active_jails(ssh, server)
    st.jail_count = len(jails)
    st.ssh_jail_enabled = _JAIL_NAME in jails
    banned_total = 0
    for jail_name in jails:
        code_j, out_j, _ = exec_sudo(
            ssh,
            server,
            f"fail2ban-client status {shlex.quote(jail_name)} 2>/dev/null",
            timeout=20,
        )
        if code_j == 0:
            match = re.search(r"Currently banned:\s*(\d+)", out_j or "", re.I)
            if match:
                banned_total += int(match.group(1))
    st.banned_count = min(banned_total, 1000000)

    if st.ssh_jail_enabled:
        for key, attr in (
            ("bantime", "ban_time"),
            ("findtime", "find_time"),
            ("maxretry", "max_retry"),
        ):
            _, out, _ = exec_sudo(
                ssh,
                server,
                f"fail2ban-client get {_JAIL_NAME} {key} 2>/dev/null",
                timeout=15,
            )
            value = (out or "").strip().splitlines()
            value = value[-1].strip() if value else ""
            if attr == "max_retry":
                try:
                    st.max_retry = int(value)
                except ValueError:
                    st.max_retry = None
            else:
                setattr(st, attr, _parse_time_token(value))
    return st


def get_status(server: dict) -> Fail2banStatus:
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=12)
        return _status_with_ssh(ssh, server)
    except Exception as exc:
        st = Fail2banStatus(label="—", error=str(exc)[:_MAX_DETAIL])
        return st
    finally:
        _close(ssh)


def install(server: dict) -> OpResult:
    """Установить пакет, включить автозапуск и запустить сервис без изменения jails."""
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=20)
        installed, package_manager, package_error = _package_state(ssh, server)
        if not package_manager:
            try:
                package_manager = detect_package_manager(ssh, server)
            except Exception as exc:
                return OpResult(
                    ok=False,
                    message="Не удалось определить package manager",
                    error=str(exc)[:_MAX_DETAIL],
                )
        if not installed:
            ok, detail = package_manager.install(ssh, server, _PACKAGE_NAME)
            if not ok:
                return OpResult(
                    ok=False,
                    message="Не удалось установить Fail2ban",
                    error=detail[:_MAX_DETAIL],
                )
        installed_after = package_manager.is_installed(ssh, server, _PACKAGE_NAME)
        if not installed_after:
            return OpResult(
                ok=False,
                message="Пакет Fail2ban не подтверждён после установки",
                error="package_not_verified",
            )
        code, out, err = exec_sudo(
            ssh, server, "systemctl enable fail2ban", timeout=45
        )
        if code != 0:
            return OpResult(
                ok=False,
                message="Fail2ban установлен, но автозапуск не включён",
                error=_detail(code, out, err),
            )
        code, out, err = exec_sudo(
            ssh, server, "systemctl start fail2ban", timeout=60
        )
        if code != 0:
            return OpResult(
                ok=False,
                message="Fail2ban установлен, но сервис не запустился",
                error=_detail(code, out, err),
            )
        st = _status_with_ssh(ssh, server)
        if not st.running:
            return OpResult(
                ok=False,
                message="Fail2ban установлен, но проверка active/ping не пройдена",
                error=st.error or "service_not_verified",
                data={"status": _status_dict(st)},
            )
        return OpResult(
            ok=True,
            message="Fail2ban установлен и запущен. Правила блокировки не изменялись автоматически",
            data=_status_dict(st),
        )
    except Exception as exc:
        return OpResult(ok=False, message="Ошибка установки Fail2ban", error=str(exc)[:_MAX_DETAIL])
    finally:
        _close(ssh)


def start(server: dict) -> OpResult:
    return _service_action(server, "start")


def stop(server: dict) -> OpResult:
    return _service_action(server, "stop")


def restart(server: dict) -> OpResult:
    return _service_action(server, "restart")


def _service_action(server: dict, action: str) -> OpResult:
    if action not in {"start", "stop", "restart"}:
        raise ValueError("Недопустимое действие Fail2ban")
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=15)
        installed, _, _ = _package_state(ssh, server)
        if not installed:
            return OpResult(ok=False, message="Fail2ban не установлен", error="not_installed")
        code, out, err = exec_sudo(
            ssh, server, f"systemctl {action} fail2ban", timeout=60
        )
        if code != 0:
            return OpResult(
                ok=False,
                message=f"Не удалось выполнить операцию {action} Fail2ban",
                error=_detail(code, out, err),
            )
        if action == "stop":
            code_a, out_a, err_a = exec_sudo(
                ssh, server, "systemctl is-active fail2ban 2>/dev/null", timeout=15
            )
            if code_a == 0 and (out_a or "").strip().splitlines()[:1] == ["active"]:
                return OpResult(ok=False, message="Fail2ban не подтвердил остановку", error="still_active")
            return OpResult(ok=True, message="Fail2ban остановлен", data=_status_dict(_status_with_ssh(ssh, server)))
        st = _status_with_ssh(ssh, server)
        if not st.running:
            return OpResult(
                ok=False,
                message=f"Fail2ban не подтвердил операцию {action}",
                error=st.error or "service_not_verified",
                data={"status": _status_dict(st)},
            )
        return OpResult(
            ok=True,
            message="Fail2ban запущен" if action == "start" else "Fail2ban перезапущен",
            data=_status_dict(st),
        )
    except Exception as exc:
        return OpResult(ok=False, message=f"Ошибка операции {action} Fail2ban", error=str(exc)[:_MAX_DETAIL])
    finally:
        _close(ssh)


def uninstall(server: dict, *, remove_config: bool = False) -> OpResult:
    """Удалить пакет; конфигурацию удалять только по явному флагу."""
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=20)
        installed, package_manager, _ = _package_state(ssh, server)
        if not installed:
            return OpResult(
                ok=True,
                message="Fail2ban уже удалён",
                data={"removed": False, "config_removed": False},
            )
        if package_manager is None:
            return OpResult(ok=False, message="Не удалось определить package manager", error="package_manager_unknown")
        running, _, _ = _service_state(ssh, server)
        if running:
            code, out, err = exec_sudo(ssh, server, "systemctl stop fail2ban", timeout=60)
            if code != 0:
                return OpResult(ok=False, message="Не удалось остановить Fail2ban перед удалением", error=_detail(code, out, err))
        ok, detail = package_manager.remove(ssh, server, _PACKAGE_NAME, purge=remove_config)
        if not ok:
            return OpResult(ok=False, message="Не удалось удалить Fail2ban", error=detail[:_MAX_DETAIL])
        if remove_config:
            code, out, err = exec_sudo(
                ssh,
                server,
                "for f in /etc/fail2ban/jail.conf /etc/fail2ban/jail.local; do "
                "[ -f \"$f\" ] && [ ! -L \"$f\" ] && [ \"$(stat -c %h \"$f\" 2>/dev/null)\" = 1 ] && rm -f -- \"$f\" || true; done; "
                "for d in /etc/fail2ban/jail.d /etc/fail2ban/filter.d; do "
                "if [ -d \"$d\" ] && [ ! -L \"$d\" ]; then find -P \"$d\" -maxdepth 1 -type f -links 1 "
                "\\( -name '*.conf' -o -name '*.local' \\) -delete; fi; done",
                timeout=45,
            )
            if code != 0:
                return OpResult(ok=False, message="Пакет удалён, но конфигурация не удалена", error=_detail(code, out, err), details={"partial": True})
        if package_manager.is_installed(ssh, server, _PACKAGE_NAME):
            return OpResult(ok=False, message="После удаления пакет всё ещё обнаружен", error="package_still_present")
        return OpResult(
            ok=True,
            message="Fail2ban удалён" + (" вместе с конфигурацией" if remove_config else ". Конфигурация сохранена"),
            data={"removed": True, "config_removed": bool(remove_config)},
        )
    except Exception as exc:
        return OpResult(ok=False, message="Ошибка удаления Fail2ban", error=str(exc)[:_MAX_DETAIL])
    finally:
        _close(ssh)



def _write_jail_local(
    ssh,
    server,
    *,
    enabled: Optional[bool] = None,
    ban_time: Optional[str] = None,
    find_time: Optional[str] = None,
    max_retry: Optional[int] = None,
) -> None:
    """Атомарно записать управляемый overlay SSH jail."""
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("Некорректное состояние SSH jail")
    ban_time = _duration(ban_time, "Ban time")
    find_time = _duration(find_time, "Find time")
    max_retry = _retry(max_retry)
    lines = ["# Managed by Bot4VPS Quick Setup", "[sshd]"]
    if enabled is not None:
        lines.append(f"enabled = {'true' if enabled else 'false'}")
    lines.extend([
        f"port = {int(server.get('port') or 22)}",
        "filter = sshd",
        "logpath = %(sshd_log)s",
        "backend = %(sshd_backend)s",
    ])
    if ban_time is not None:
        lines.append(f"bantime = {ban_time}")
    if find_time is not None:
        lines.append(f"findtime = {find_time}")
    if max_retry is not None:
        lines.append(f"maxretry = {max_retry}")
    code, out, err = _exec(
        ssh,
        server,
        "[ ! -L /etc/fail2ban ] && mkdir -p /etc/fail2ban/jail.d && "
        "[ ! -L /etc/fail2ban/jail.d ]",
        20,
    )
    if code != 0:
        raise RuntimeError(_failure(code, out, err))
    atomic_write(ssh, server, _JAIL_LOCAL, "\n".join(lines) + "\n", mode=0o644)


def _ensure_running(ssh, server) -> tuple[bool, str]:
    code, out, err = _exec(ssh, server, "fail2ban-client reload", 30)
    if code != 0:
        return False, _failure(code, out, err)
    running, _, detail = _service_state(ssh, server)
    return running, "active" if running else (detail or "Fail2ban не active")


def _transactional_overlay(ssh, server, content: str, expected: dict) -> tuple[bool, str, dict]:
    snapshot = snapshot_file(ssh, server, _JAIL_LOCAL)

    def apply() -> None:
        atomic_write(ssh, server, _JAIL_LOCAL, content, mode=0o644)

    def verify() -> None:
        current = snapshot_file(ssh, server, _JAIL_LOCAL)
        if not current.existed or current.content != content.encode("utf-8"):
            raise RuntimeError("Содержимое управляемого SSH jail не подтверждено")
        active_jails = _active_jails(ssh, server)
        if expected.get("enabled") is True and _JAIL_NAME not in active_jails:
            raise RuntimeError("Jail sshd не стал активным")
        if expected.get("enabled") is False and _JAIL_NAME in active_jails:
            raise RuntimeError("Jail sshd остался активным")
        if _JAIL_NAME not in active_jails:
            return
        for key in ("bantime", "findtime", "maxretry"):
            wanted = expected.get(key)
            if wanted is None:
                continue
            actual = _effective(ssh, server, _JAIL_NAME, key)
            if actual is None or not _effective_matches(key, wanted, actual):
                raise RuntimeError(f"Не подтверждено значение {key}")

    return _file_transaction(ssh, server, snapshot, apply, verify=verify)


def apply_settings(
    server: dict,
    *,
    ssh_jail_enabled: Optional[bool] = None,
    ban_time: Optional[str] = None,
    find_time: Optional[str] = None,
    max_retry: Optional[int] = None,
) -> OpResult:
    try:
        ban_time = _duration(ban_time, "Ban time")
        find_time = _duration(find_time, "Find time")
        max_retry = _retry(max_retry)
    except ValueError as exc:
        return OpResult(False, "Некорректные параметры Fail2ban", error=str(exc))
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=15)
        installed, _, _ = _package_state(ssh, server)
        if not installed:
            return OpResult(False, "Fail2ban не установлен", error="not_installed")
        active_jails = _active_jails(ssh, server)
        sshd_active = _JAIL_NAME in active_jails
        if not sshd_active and ssh_jail_enabled is None:
            return OpResult(
                False,
                "Jail sshd неактивен. Сначала явно включите его",
                error="jail_not_active",
            )
        current = (
            {
                key: _effective(ssh, server, _JAIL_NAME, key)
                for key in ("bantime", "findtime", "maxretry")
            }
            if sshd_active
            else {"bantime": None, "findtime": None, "maxretry": None}
        )
        values = {
            "enabled": ssh_jail_enabled,
            "bantime": ban_time if ban_time is not None else current["bantime"],
            "findtime": find_time if find_time is not None else current["findtime"],
            "maxretry": str(max_retry) if max_retry is not None else current["maxretry"],
        }
        lines = ["# Managed by Bot4VPS Quick Setup", "[sshd]"]
        if values["enabled"] is not None:
            lines.append(f"enabled = {'true' if values['enabled'] else 'false'}")
        lines.extend([
            f"port = {int(server.get('port') or 22)}",
            "filter = sshd",
            "logpath = %(sshd_log)s",
            "backend = %(sshd_backend)s",
        ])
        for key in ("bantime", "findtime", "maxretry"):
            if values[key] is not None:
                lines.append(f"{key} = {values[key]}")
        ok, detail, tx = _transactional_overlay(ssh, server, "\n".join(lines) + "\n", values)
        if not ok:
            return OpResult(False, "Настройки Fail2ban не применены; выполнен rollback", error=detail, details=tx)
        warning = ". Предупреждение: Max retries = 1 — блокировки срабатывают очень быстро" if max_retry == 1 else ""
        return OpResult(True, "Настройки Fail2ban применены" + warning, data=_status_dict(_status_with_ssh(ssh, server)), details=tx)
    except Exception as exc:
        return OpResult(False, "Ошибка применения настроек Fail2ban", error=_bounded(exc))
    finally:
        _close(ssh)


def _jail_classification(
    name: str,
    *,
    is_active: bool,
    configured: dict,
    availability: str,
) -> dict:
    """Категория и переключаемость правила — один предикат для list и toggle.

    user_managed = правило описано в файле пользователя (jail.local или чужой
    jail.d/*): наш overlay читается позже и молча перекрыл бы его, поэтому
    такие правила не переключаем автоматически.
    """
    in_config = name in configured
    user_managed = bool(_jail_user_sources(configured.get(name, [])))
    if name == _JAIL_NAME:
        # sshd управляется настройками защиты (bot4vps-sshd.local) — своя ветка UI.
        return {
            "user_managed": False,
            "availability": "ok",
            "toggleable": False,
            "category": "enabled" if is_active else "available",
            "reason": None,
        }
    if is_active:
        toggleable = in_config and not user_managed
        reason = None if toggleable else ("user_managed" if user_managed else "unknown_source")
        return {
            "user_managed": user_managed,
            "availability": availability,
            "toggleable": toggleable,
            "category": "enabled",
            "reason": reason,
        }
    toggleable = in_config and not user_managed and availability == "ok"
    if toggleable:
        reason = None
    elif user_managed:
        reason = "user_managed"
    elif not in_config:
        reason = "unknown_source"
    else:
        reason = availability
    return {
        "user_managed": user_managed,
        "availability": availability,
        "toggleable": toggleable,
        "category": "available" if toggleable else "manual",
        "reason": reason,
    }


def list_jails(server: dict) -> OpResult:
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=15)
        configured = _configured_jails(ssh, server)
        active_names = _active_jails(ssh, server)
        active = set(active_names)
        found_binaries, found_logs, logtarget = _jails_runtime_facts(ssh, server)
        ordered_names = list(configured)
        ordered_names.extend(name for name in active_names if name not in configured)
        result = []
        for name in ordered_names[:_MAX_ITEMS]:
            is_active = name in active
            detail = ""
            info = {"banned": 0}
            if is_active:
                ok, detail, info = _jail_info(ssh, server, name)
                is_active = ok
            source = ", ".join(configured.get(name, [])[:8])
            availability = (
                "ok" if name == _JAIL_NAME
                else _jail_availability(name, found_binaries, found_logs, logtarget)
            )
            classification = _jail_classification(
                name,
                is_active=is_active,
                configured=configured,
                availability=availability,
            )
            entry = {
                "name": name,
                "active": is_active,
                "enabled": True if is_active else None,
                "configured": name in configured,
                "source": source or "активная конфигурация",
                "banned": info.get("banned", 0),
                "error": detail or None,
            }
            entry.update(classification)
            result.append(entry)
        return OpResult(
            True,
            "Правила блокировки получены" if result else "Правила блокировки не найдены",
            data={"jails": result},
        )
    except Exception as exc:
        return OpResult(False, "Не удалось получить Правила блокировки", error=_bounded(exc))
    finally:
        _close(ssh)


def set_jail_enabled(server: dict, jail: str, *, enabled: bool) -> OpResult:
    """Включить/выключить стоковое правило через managed overlay jail.d/bot4vps-jails.local.

    jail.conf не редактируется; пользовательские jail.local/jail.d не трогаются:
    правило с пользовательским описанием отвергается. Транзакция как у whitelist:
    snapshot → полная пересборка файла → fail2ban-client -t → reload → проверка
    фактического состояния правила → точный rollback при любой ошибке.
    """
    try:
        jail = _valid_name(jail, "имя правила блокировки")
    except ValueError as exc:
        return OpResult(False, "Некорректное имя правила блокировки", error=str(exc))
    if not isinstance(enabled, bool):
        return OpResult(False, "Некорректное состояние правила блокировки", error="invalid_enabled")
    if jail == _JAIL_NAME:
        return OpResult(
            False,
            "Правило sshd управляется настройками защиты Fail2ban",
            error="jail_sshd_managed_separately",
        )
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=15)
        installed, _, _ = _package_state(ssh, server)
        if not installed:
            return OpResult(False, "Fail2ban не установлен", error="not_installed")
        configured = _configured_jails(ssh, server)
        sources = configured.get(jail, [])
        if not sources:
            return OpResult(
                False,
                f"Правило блокировки {jail} не найдено в конфигурации Fail2ban",
                error="jail_unknown",
            )
        user_sources = _jail_user_sources(sources)
        if user_sources:
            return OpResult(
                False,
                "Правило задано в вашей конфигурации ("
                + ", ".join(user_sources[:4])
                + "). Измените файл-источник в разделе «Конфигурация»",
                error="jail_user_managed",
                data={"jail": jail, "sources": user_sources[:8]},
            )
        running, _, service_error = _service_state(ssh, server)
        if not running:
            return OpResult(False, "Сначала запустите Fail2ban", error="service_not_running")
        availability_hint = {
            "missing_service": "не найден сервис",
            "missing_logs": "сервис есть, но его логи недоступны Fail2ban",
            "unknown": "недостаточно данных для автоматического включения",
        }
        if enabled:
            found_binaries, found_logs, logtarget = _jails_runtime_facts(ssh, server)
            availability = _jail_availability(jail, found_binaries, found_logs, logtarget)
            if availability != "ok":
                hint = availability_hint.get(availability, availability)
                return OpResult(
                    False,
                    f"Правило блокировки {jail} нельзя включить автоматически: {hint}",
                    error="jail_unavailable",
                    data={"jail": jail, "availability": availability},
                )
        active_now = set(_active_jails(ssh, server))
        snapshot = snapshot_file(ssh, server, _JAILS_LOCAL)
        managed = _managed_jail_enabled(snapshot.content) if snapshot.existed else {}
        managed.pop(_JAIL_NAME, None)
        # Прунинг: не держим секции правил, которые перестали быть нашими,
        # чтобы устаревший enabled не перекрывал будущую пользовательскую
        # конфигурацию (наш jail.d/*.local читается последним).
        pruned = _JAIL_NAME in _managed_jail_enabled(snapshot.content) if snapshot.existed else False
        for name in list(managed):
            if name == jail:
                continue
            if name not in configured or _jail_user_sources(configured.get(name, [])):
                del managed[name]
                pruned = True
        already = (
            not pruned
            and enabled == (jail in active_now)
            and managed.get(jail) == enabled
        )
        if already:
            return OpResult(
                True,
                f"Правило блокировки {jail} уже {'включено' if enabled else 'выключено'}",
                data={"jail": jail, "enabled": enabled, "changed": False},
            )
        managed[jail] = bool(enabled)
        content = _render_managed_jails_file(managed)
        code, out, err = _exec(
            ssh,
            server,
            "[ ! -L /etc/fail2ban ] && mkdir -p /etc/fail2ban/jail.d && "
            "[ ! -L /etc/fail2ban/jail.d ]",
            20,
        )
        if code != 0:
            return OpResult(False, "Каталог конфигурации недоступен", error=_failure(code, out, err))

        def apply() -> None:
            atomic_write(ssh, server, _JAILS_LOCAL, content, mode=0o644)

        def verify() -> None:
            current = snapshot_file(ssh, server, _JAILS_LOCAL)
            if not current.existed or current.content != content.encode("utf-8"):
                raise RuntimeError("Содержимое управляемого файла правил не подтверждено")
            active_after = _active_jails(ssh, server)
            if enabled and jail not in active_after:
                raise RuntimeError(f"Правило блокировки {jail} не стало активным")
            if not enabled and jail in active_after:
                raise RuntimeError(f"Правило блокировки {jail} осталось активным")

        ok, detail, tx = _file_transaction(ssh, server, snapshot, apply, verify=verify)
        if not ok:
            return OpResult(
                False,
                "Правило блокировки не изменено; выполнен rollback",
                error=detail,
                details=tx,
            )
        return OpResult(
            True,
            f"Правило блокировки {jail} {'включено' if enabled else 'выключено'}",
            data={"jail": jail, "enabled": enabled},
            details=tx,
        )
    except Exception as exc:
        return OpResult(False, "Ошибка изменения правила блокировки", error=_bounded(exc))
    finally:
        _close(ssh)


def list_banned(server: dict) -> OpResult:
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=12)
        bans = []
        for jail in _active_jails(ssh, server):
            ok, _, info = _jail_info(ssh, server, jail)
            if ok:
                bans.extend({"jail": jail, "ip": ip} for ip in info["ips"][:_MAX_ITEMS])
        bans = bans[:_MAX_ITEMS]
        return OpResult(True, "Заблокированные IP получены" if bans else "Заблокированных IP нет.", data={"bans": bans, "ips": bans})
    except Exception as exc:
        return OpResult(False, "Ошибка списка банов", error=_bounded(exc))
    finally:
        _close(ssh)


def unban(server: dict, jail: str, ip: str) -> OpResult:
    try:
        jail = _valid_name(jail, "имя jail")
        ip = _normalize_ip(ip)
    except ValueError as exc:
        return OpResult(False, "Некорректные данные для разблокировки", error=str(exc))
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=15)
        if jail not in _active_jails(ssh, server):
            return OpResult(False, "Jail не обнаружен среди активных", error="jail_not_discovered")
        code, out, err = _exec(ssh, server, f"fail2ban-client set {shlex.quote(jail)} unbanip {shlex.quote(ip)}", 30)
        if code != 0:
            return OpResult(False, "Не удалось разблокировать IP", error=_failure(code, out, err))
        ok, _, info = _jail_info(ssh, server, jail)
        if ok and ip in info["ips"]:
            return OpResult(False, "Fail2ban не подтвердил разблокировку", error="unban_not_verified")
        return OpResult(True, f"IP {ip} разблокирован", data={"jail": jail, "ip": ip})
    except Exception as exc:
        return OpResult(False, "Ошибка разблокировки IP", error=_bounded(exc))
    finally:
        _close(ssh)


def _safe_config_path(kind: str, filename: str) -> tuple[str, str]:
    filename = _valid_filename(filename)
    kind = str(kind or "").strip().lower()
    if kind == "jail":
        if filename in {"jail.conf", "jail.local"}:
            return f"{_JAIL_ROOT}/{filename}", kind
        return f"{_JAIL_DIR}/{filename}", kind
    if kind == "filter" and filename.endswith(".conf"):
        return f"{_FILTER_DIR}/{filename}", kind
    raise ValueError("Разрешены только типы jail и filter")


def _config_files(ssh, server, directory: str, pattern: str) -> list[str]:
    qdir = shlex.quote(directory)
    code, out, _ = _exec(ssh, server, f"[ -d {qdir} ] && [ ! -L {qdir} ] && find -P {qdir} -maxdepth 1 -type f -links 1 {pattern} -printf '%f\\n' | head -n 200", 20)
    if code != 0:
        return []
    return sorted({name.strip() for name in out.splitlines() if _FILE_RE.fullmatch(name.strip())})[:_MAX_ITEMS]


def list_filters(server: dict) -> OpResult:
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=15)
        names = [name for name in _config_files(ssh, server, _FILTER_DIR, "-name '*.conf'") if name.endswith('.conf')]
        return OpResult(True, "Фильтры получены", data={"filters": [{"name": name[:-5], "filename": name} for name in names]})
    except Exception as exc:
        return OpResult(False, "Не удалось получить Фильтры", error=_bounded(exc))
    finally:
        _close(ssh)


def list_whitelist(server: dict) -> OpResult:
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=15)
        snapshot = snapshot_file(ssh, server, _WHITELIST_LOCAL)
        managed = _managed_whitelist_entries(snapshot.content) if snapshot.existed else []
        effective = _effective_whitelist(ssh, server)
        entries = []
        for value in managed:
            entries.append({
                "ip": value,
                "source": "Bot4VPS overlay",
                "managed": True,
                "jails": effective.get(value, [])[:_MAX_ITEMS],
            })
        for value, jails in effective.items():
            if value in managed:
                continue
            entries.append({
                "ip": value,
                "source": "Эффективная конфигурация Fail2ban; файл-источник не определён",
                "managed": False,
                "jails": jails[:_MAX_ITEMS],
            })
        entries.sort(key=lambda item: (not item["managed"], item["ip"]))
        return OpResult(True, "Whitelist получен", data={"entries": entries[:_MAX_ITEMS]})
    except Exception as exc:
        return OpResult(False, "Не удалось получить Whitelist", error=_bounded(exc))
    finally:
        _close(ssh)


def _mutate_whitelist(server: dict, ip: str, remove: bool) -> OpResult:
    try:
        ip = _normalize_ip(ip)
    except ValueError as exc:
        return OpResult(False, "Некорректный IP-адрес или CIDR", error=str(exc))
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=15)
        running, _, service_error = _service_state(ssh, server)
        if not running:
            return OpResult(
                False,
                "Сначала запустите Fail2ban",
                error=service_error or "service_not_running",
            )
        snapshot = snapshot_file(ssh, server, _WHITELIST_LOCAL)
        values = _managed_whitelist_entries(snapshot.content) if snapshot.existed else []
        effective_before = _effective_whitelist(ssh, server)
        if remove and ip not in values:
            if ip in effective_before:
                return OpResult(
                    False,
                    "Запись Whitelist задана не управляемым overlay. Измените файл-источник через редактор конфигурации",
                    error="unmanaged_entry",
                    data={"ip": ip, "managed": False},
                )
            return OpResult(True, "IP уже отсутствует в управляемом Whitelist", data={"ip": ip, "removed": False})
        if not remove and ip in effective_before and ip not in values:
            return OpResult(
                True,
                "IP уже присутствует в эффективном Whitelist",
                data={"ip": ip, "added": False, "managed": False},
            )
        values = [value for value in values if value != ip]
        if not remove:
            values.append(ip)
        values = sorted(set(values))[:_MAX_ITEMS]
        code, out, err = _exec(
            ssh,
            server,
            "[ ! -L /etc/fail2ban ] && mkdir -p /etc/fail2ban/jail.d && "
            "[ ! -L /etc/fail2ban/jail.d ]",
            20,
        )
        if code != 0:
            return OpResult(False, "Каталог конфигурации недоступен", error=_failure(code, out, err))

        content = (
            "# Managed by Bot4VPS Quick Setup\n"
            "[DEFAULT]\n"
            f"ignoreip = {' '.join(values)}\n"
        )

        def apply() -> None:
            atomic_write(ssh, server, _WHITELIST_LOCAL, content, mode=0o644)

        def verify() -> None:
            effective_after = _effective_whitelist(ssh, server, strict=True)
            present = ip in effective_after
            if remove and present:
                raise RuntimeError("Удаление IP из эффективного Whitelist не подтверждено")
            if not remove and not present:
                raise RuntimeError("Добавление IP в эффективный Whitelist не подтверждено")
            current = snapshot_file(ssh, server, _WHITELIST_LOCAL)
            managed_after = _managed_whitelist_entries(current.content) if current.existed else []
            if (ip in managed_after) == remove:
                raise RuntimeError("Изменение управляемого Whitelist не подтверждено")

        ok, detail, tx = _file_transaction(ssh, server, snapshot, apply, verify=verify)
        if not ok:
            return OpResult(
                False,
                "Whitelist не изменён; выполнен rollback",
                error=detail,
                details=tx,
            )
        return OpResult(
            True,
            "Whitelist обновлён",
            data={"ip": ip, "removed": remove, "managed": True},
            details=tx,
        )
    except Exception as exc:
        return OpResult(False, "Ошибка изменения Whitelist", error=_bounded(exc))
    finally:
        _close(ssh)


def add_whitelist(server: dict, ip: str) -> OpResult:
    return _mutate_whitelist(server, ip, False)


def remove_whitelist(server: dict, ip: str) -> OpResult:
    return _mutate_whitelist(server, ip, True)


def list_configuration(server: dict) -> OpResult:
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=15)
        files = []
        for path in (f"{_JAIL_ROOT}/jail.conf", f"{_JAIL_ROOT}/jail.local"):
            snapshot = snapshot_file(ssh, server, path)
            if snapshot.existed:
                files.append({"kind": "jail", "filename": path.rsplit('/', 1)[-1], "path": path, "standard": True})
        for name in _config_files(ssh, server, _JAIL_DIR, "\\( -name '*.conf' -o -name '*.local' \\)"):
            files.append({"kind": "jail", "filename": name, "path": f"{_JAIL_DIR}/{name}", "standard": False})
        for name in _config_files(ssh, server, _FILTER_DIR, "-name '*.conf'"):
            files.append({"kind": "filter", "filename": name, "path": f"{_FILTER_DIR}/{name}", "standard": False})
        return OpResult(True, "Конфигурация получена", data={"files": files[:_MAX_ITEMS]})
    except Exception as exc:
        return OpResult(False, "Не удалось получить конфигурацию", error=_bounded(exc))
    finally:
        _close(ssh)


def read_configuration(server: dict, kind: str, filename: str) -> OpResult:
    try:
        path, kind = _safe_config_path(kind, filename)
    except ValueError as exc:
        return OpResult(False, "Некорректный путь конфигурации", error=str(exc))
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=15)
        snapshot = snapshot_file(ssh, server, path)
        if not snapshot.existed:
            return OpResult(False, "Файл конфигурации не найден", error="not_found")
        content = snapshot.content.decode("utf-8", errors="replace")
        return OpResult(
            True,
            "Конфигурация прочитана",
            data={
                "kind": kind,
                "filename": filename,
                "path": path,
                "content": content,
            },
            # Редактор поддерживает конфигурации до 512 КиБ. Это отдельный
            # ограниченный payload, а не произвольный command output.
            _data_text_limit=512 * 1024,
        )
    except Exception as exc:
        return OpResult(False, "Не удалось прочитать конфигурацию", error=_bounded(exc))
    finally:
        _close(ssh)


def write_configuration(
    server: dict,
    kind: str,
    filename: str,
    content: str,
    *,
    create_only: bool = False,
) -> OpResult:
    try:
        path, kind = _safe_config_path(kind, filename)
        content = str(content or "")
        if len(content.encode("utf-8")) > 512 * 1024 or "\x00" in content or "\r" in content:
            raise ValueError("Конфигурация превышает лимит или содержит недопустимые символы")
        if not isinstance(create_only, bool):
            raise ValueError("Некорректный режим записи конфигурации")
        if create_only and filename in {"jail.conf", "jail.local"}:
            raise ValueError("Стандартные файлы нельзя создавать через Quick Setup")
    except ValueError as exc:
        return OpResult(False, "Некорректная конфигурация", error=str(exc))
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=15)
        running, _, service_error = _service_state(ssh, server)
        if not running:
            return OpResult(
                False,
                "Сначала запустите Fail2ban",
                error=service_error or "service_not_running",
            )
        snapshot = snapshot_file(ssh, server, path)
        if create_only and snapshot.existed:
            return OpResult(
                False,
                "Файл уже существует. Откройте его для изменения",
                error="already_exists",
            )
        if not create_only and not snapshot.existed:
            return OpResult(
                False,
                "Файл конфигурации не найден",
                error="not_found",
            )
        parent = (
            _JAIL_DIR
            if kind == "jail" and filename not in {"jail.conf", "jail.local"}
            else (_FILTER_DIR if kind == "filter" else _JAIL_ROOT)
        )
        code, out, err = _exec(
            ssh,
            server,
            f"[ ! -L {shlex.quote(_JAIL_ROOT)} ] && "
            f"[ ! -L {shlex.quote(parent)} ] && "
            f"mkdir -p -- {shlex.quote(parent)}",
            20,
        )
        if code != 0:
            return OpResult(False, "Каталог конфигурации недоступен", error=_failure(code, out, err))

        raw_content = content.encode("utf-8")

        def apply() -> None:
            current = snapshot_file(ssh, server, path)
            if not _snapshot_matches(snapshot, current):
                raise _NoMutationError("Файл изменился параллельно. Обновите конфигурацию и повторите попытку")
            try:
                atomic_write(
                    ssh,
                    server,
                    path,
                    raw_content,
                    mode=snapshot.mode if snapshot.existed else 0o644,
                    uid=snapshot.uid if snapshot.existed else None,
                    gid=snapshot.gid if snapshot.existed else None,
                    create_only=create_only,
                )
            except FileExistsError as exc:
                raise _NoMutationError("Файл уже существует. Обновите конфигурацию") from exc

        def verify() -> None:
            current = snapshot_file(ssh, server, path)
            if not current.existed or current.content != raw_content:
                raise RuntimeError("Сохранённое содержимое конфигурации не подтверждено")

        ok, detail, tx = _file_transaction(ssh, server, snapshot, apply, verify=verify)
        if not ok:
            if tx.get("no_change"):
                return OpResult(False, "Конфигурация не изменена", error=detail, details=tx)
            return OpResult(
                False,
                "Конфигурация не сохранена; выполнен rollback",
                error=detail,
                details=tx,
            )
        return OpResult(
            True,
            "Конфигурация создана" if create_only else "Конфигурация сохранена",
            data={"kind": kind, "filename": filename, "created": create_only},
            details=tx,
        )
    except Exception as exc:
        return OpResult(False, "Ошибка записи конфигурации", error=_bounded(exc))
    finally:
        _close(ssh)


def delete_configuration(server: dict, kind: str, filename: str) -> OpResult:
    try:
        path, kind = _safe_config_path(kind, filename)
        if filename in {"jail.conf", "jail.local"}:
            return OpResult(False, "Стандартные файлы jail нельзя удалить через Quick Setup", error="protected_file")
    except ValueError as exc:
        return OpResult(False, "Некорректный путь конфигурации", error=str(exc))
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=15)
        running, _, service_error = _service_state(ssh, server)
        if not running:
            return OpResult(
                False,
                "Сначала запустите Fail2ban",
                error=service_error or "service_not_running",
            )
        snapshot = snapshot_file(ssh, server, path)
        if not snapshot.existed:
            return OpResult(False, "Файл конфигурации не найден", error="not_found")

        def apply() -> None:
            current = snapshot_file(ssh, server, path)
            if not _snapshot_matches(snapshot, current):
                raise _NoMutationError(
                    "Файл изменился параллельно. Обновите конфигурацию и повторите попытку"
                )
            restore_file(
                ssh,
                server,
                RemoteFileSnapshot(path=path, existed=False),
            )

        def verify() -> None:
            current = snapshot_file(ssh, server, path)
            if current.existed:
                raise RuntimeError("Удаление файла конфигурации не подтверждено")

        ok, detail, tx = _file_transaction(ssh, server, snapshot, apply, verify=verify)
        if not ok:
            if tx.get("no_change"):
                return OpResult(False, "Файл конфигурации не изменён", error=detail, details=tx)
            return OpResult(
                False,
                "Файл конфигурации не удалён; выполнен rollback",
                error=detail,
                details=tx,
            )
        return OpResult(
            True,
            "Файл конфигурации удалён",
            data={"kind": kind, "filename": filename},
            details=tx,
        )
    except Exception as exc:
        return OpResult(False, "Ошибка удаления конфигурации", error=_bounded(exc))
    finally:
        _close(ssh)


get_jails = list_jails
get_filters = list_filters
get_configuration = list_configuration
read_config = read_configuration
write_config = write_configuration
delete_config = delete_configuration
unban_ip = unban
add_whitelist_ip = add_whitelist
remove_whitelist_ip = remove_whitelist
