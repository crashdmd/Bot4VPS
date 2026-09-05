# -*- coding: utf-8 -*-
"""Раздел «Диагностика»: актуальный снимок системы с VPS."""
from __future__ import annotations

from core.ssh import create_ssh_client, exec_sudo

from .models import DiagnosticsStatus

_SEP = "::BOT4VPS_QS::"

# Одна batched-команда — минимум round-trip'ов.
_DIAG_CMD = (
    "(. /etc/os-release 2>/dev/null; echo \"${PRETTY_NAME:-${NAME:-N/A}}\"); "
    f"echo '{_SEP}'; "
    "(. /etc/os-release 2>/dev/null; echo \"${VERSION_ID:-N/A}\"); "
    f"echo '{_SEP}'; "
    "uname -r 2>/dev/null || echo N/A; "
    f"echo '{_SEP}'; "
    "uname -m 2>/dev/null || echo N/A; "
    f"echo '{_SEP}'; "
    "hostname 2>/dev/null || cat /etc/hostname 2>/dev/null || echo N/A; "
    f"echo '{_SEP}'; "
    "(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2- | sed 's/^ *//') || echo N/A; "
    f"echo '{_SEP}'; "
    "nproc 2>/dev/null || grep -c ^processor /proc/cpuinfo 2>/dev/null || echo 0; "
    f"echo '{_SEP}'; "
    "free -m | awk '/Mem:/ {print $3\" MB / \"$2\" MB\"}'; "
    f"echo '{_SEP}'; "
    "df -h / | awk 'NR==2 {print $3\" / \"$2\" (\"$5\")\"}'; "
    f"echo '{_SEP}'; "
    "uptime -p 2>/dev/null || echo N/A; "
    f"echo '{_SEP}'; "
    "awk '{print $1}' /proc/uptime 2>/dev/null || echo; "
    f"echo '{_SEP}'; "
    # firewall detect (best-effort)
    "("
    "if command -v ufw >/dev/null 2>&1; then "
    "  st=$(ufw status 2>/dev/null | head -1); "
    "  echo \"UFW|$st\"; "
    "elif command -v firewall-cmd >/dev/null 2>&1; then "
    "  st=$(firewall-cmd --state 2>/dev/null || echo unknown); "
    "  echo \"firewalld|$st\"; "
    "elif command -v nft >/dev/null 2>&1; then "
    "  echo 'nftables|present'; "
    "else echo 'none|'; fi"
    "); "
    f"echo '{_SEP}'; "
    # fail2ban
    "("
    "if command -v fail2ban-client >/dev/null 2>&1 || "
    "   systemctl list-unit-files fail2ban.service 2>/dev/null | grep -q fail2ban; then "
    "  if systemctl is-active --quiet fail2ban 2>/dev/null || "
    "     fail2ban-client ping 2>/dev/null | grep -qi pong; then "
    "    echo 'running'; "
    "  else echo 'stopped'; fi; "
    "else echo 'missing'; fi"
    ")"
)


def _part(parts: list[str], i: int) -> str:
    if i < len(parts) and parts[i].strip():
        return parts[i].strip()
    return "—"


def collect(server: dict) -> DiagnosticsStatus:
    """Собрать диагностику с VPS. Не меняет состояние сервера."""
    st = DiagnosticsStatus(
        ssh_port=int(server.get("port") or 22),
    )
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=12)
        st.ssh_ok = True
        # Без sudo: чтение /proc, os-release, ufw status может потребовать
        # прав — пробуем сначала без, при необходимости exec_sudo для fw.
        _, stdout, stderr = ssh.exec_command(_DIAG_CMD, timeout=25)
        raw = stdout.read().decode("utf-8", errors="ignore")
        _ = stderr.read()
        parts = raw.split(_SEP)

        st.os = _part(parts, 0)
        st.os_version = _part(parts, 1)
        st.kernel = _part(parts, 2)
        st.arch = _part(parts, 3)
        st.hostname = _part(parts, 4)
        st.cpu_model = _part(parts, 5)
        try:
            st.cpu_cores = int(_part(parts, 6)) if _part(parts, 6) not in ("—", "N/A") else None
        except ValueError:
            st.cpu_cores = None
        st.ram = _part(parts, 7)
        st.disk = _part(parts, 8)
        st.uptime = _part(parts, 9)
        try:
            st.uptime_seconds = float(_part(parts, 10)) if _part(parts, 10) not in ("—", "") else None
        except ValueError:
            st.uptime_seconds = None

        fw_raw = _part(parts, 11)
        if "|" in fw_raw:
            name, rest = fw_raw.split("|", 1)
            name = name.strip()
            rest_l = rest.lower()
            if name == "none" or not name:
                st.firewall = "Не обнаружен"
            elif name == "UFW":
                if "inactive" in rest_l:
                    st.firewall = "UFW (неактивен)"
                else:
                    st.firewall = "UFW"
            elif name == "firewalld":
                if "running" in rest_l:
                    st.firewall = "firewalld"
                else:
                    st.firewall = f"firewalld ({rest.strip() or 'stopped'})"
            elif name == "nftables":
                st.firewall = "nftables"
            else:
                st.firewall = name
        else:
            st.firewall = "Не обнаружен"

        fb = _part(parts, 12).lower()
        if fb == "running":
            st.fail2ban = "● Работает"
        elif fb == "stopped":
            st.fail2ban = "● Остановлен"
        else:
            st.fail2ban = "Не установлен"

        return st
    except Exception as e:
        st.ssh_ok = False
        st.ssh_error = str(e)[:400]
        st.error = st.ssh_error
        return st
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def refresh_firewall_label(server: dict) -> str:
    """Точечная проверка firewall (для будущего раздела)."""
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=8)
        code, out, _ = exec_sudo(
            ssh,
            server,
            "if command -v ufw >/dev/null 2>&1; then echo UFW; "
            "elif command -v firewall-cmd >/dev/null 2>&1; then echo firewalld; "
            "elif command -v nft >/dev/null 2>&1; then echo nftables; "
            "else echo none; fi",
            timeout=15,
        )
        name = (out or "").strip().splitlines()[-1].strip() if out else "none"
        if code != 0 or name in ("", "none"):
            return "Не обнаружен"
        return name
    except Exception:
        return "—"
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass
