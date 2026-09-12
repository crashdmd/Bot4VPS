"""Systemd/firewall/journalctl — единственное место в ui/cli с subprocess.

menu.py и ops.py не вызывают systemctl/ufw/journalctl напрямую — только
через этот модуль (легко мокается в тестах).

Шаблоны юнитов и правила firewall перенесены из install.sh
(write_web_unit / write_tg_unit / open_web_port / close_web_port) —
install.sh остаётся reference-ом, но в runtime CLI от него не зависит.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

SERVICE = "bot4vps"
UNIT_PATH = Path("/etc/systemd/system/bot4vps.service")
WRAPPER_PATH = Path("/usr/local/bin/bot4vps")
# ui/cli/systemd_ops.py -> /opt/bot4vps
INSTALL_DIR = Path(__file__).resolve().parents[2]

# ─────────────────────────────────────────────
# Шаблоны юнитов (перенос из install.sh, без изменений)
# ─────────────────────────────────────────────

WEB_UNIT_TEMPLATE = """\
[Unit]
Description=Bot4VPS (Web UI + Telegram bot)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory={install_dir}
Environment=PYTHONPATH={install_dir}
ExecStart={install_dir}/venv/bin/python -m uvicorn ui.web.app:app --host 0.0.0.0 --port {port}
Restart=always
RestartSec=5
TimeoutStopSec=3
KillMode=mixed

[Install]
WantedBy=multi-user.target
"""

TG_UNIT_TEMPLATE = """\
[Unit]
Description=Bot4VPS (Telegram only)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory={install_dir}
Environment=PYTHONPATH={install_dir}
ExecStart={install_dir}/venv/bin/python bot.py
Restart=always
RestartSec=5
# Stop-настройки нужны и здесь: web_disable пишет tg-юнит ДО рестарта,
# и остановка ещё работающего uvicorn идёт уже по НОВОМУ юниту — без
# этого капа systemd ждал бы дефолтные 90 c (uvicorn не выходит по
# SIGTERM при открытых соединениях браузера). bot.py по SIGTERM
# останавливается чисто и быстро, кап его не режет.
TimeoutStopSec=3
KillMode=mixed

[Install]
WantedBy=multi-user.target
"""


def run(cmd: list[str], timeout: int = 90) -> subprocess.CompletedProcess:
    """subprocess.run с текстовым выводом; код возврата не проверяется."""
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )


def systemctl(*args: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return run(["systemctl", *args], timeout=timeout)


# ─────────────────────────────────────────────
# Фактическое состояние сервиса
# ─────────────────────────────────────────────

def is_active() -> bool:
    return systemctl("is-active", "--quiet", SERVICE).returncode == 0


def unit_exists() -> bool:
    return UNIT_PATH.exists()


def service_started_at() -> datetime | None:
    """Момент старта сервиса (локальное время, naive datetime).

    ActiveEnterTimestamp имеет формат «Tue 2026-09-08 13:16:05 EET» —
    дата числовая, локаль влияет только на имя дня недели, которое мы
    не парсим. Monotonic-вариант не подходит: в LXC /proc/uptime
    подменяется lxcfs и с monotonic-меткой systemd несравним.
    """
    from datetime import datetime

    result = systemctl("show", SERVICE, "-p", "ActiveEnterTimestamp", "--value")
    raw = (result.stdout or "").strip()
    if not raw or raw == "0":
        return None
    try:
        # "Tue 2026-09-08 13:16:05 EET" → "2026-09-08 13:16:05"
        return datetime.strptime(" ".join(raw.split()[1:3]), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def unit_mode() -> str | None:
    """Режим юнита: web+tg (uvicorn) | tg-only (bot.py) | None (юнита нет).

    Паритет с install.sh get_mode().
    """
    try:
        text = UNIT_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    if "uvicorn" in text:
        return "web+tg"
    return "tg-only"


# ─────────────────────────────────────────────
# Изменение юнита / управление сервисом
# ─────────────────────────────────────────────

def write_unit(text: str) -> None:
    """Атомарная запись юнита (tmp + os.replace, как core/web_port)."""
    tmp = UNIT_PATH.with_suffix(".service.tmp")
    tmp.write_text(text, encoding="utf-8")
    import os

    os.replace(tmp, UNIT_PATH)


def write_web_unit(port: int) -> None:
    """Юнит web+tg; TLS-флаги — из config web.tls (core/web_tls).

    Режим HTTPS переживает выключение/включение Web. Управляемая пара
    (letsencrypt/self-signed/custom-upload) обязана существовать: юнит с
    ssl-флагами на отсутствующие файлы не стартует вовсе — отказ с
    понятным текстом лучше молчаливого даунгрейда на HTTP.
    """
    from core.config import get_tls_config
    from core.web_tls import tls_asset_paths, unit_tls_flags

    tls = get_tls_config()
    for path in tls_asset_paths(tls):
        if not path.is_file():
            raise ValueError(
                "Сертификат HTTPS не найден: %s — перевыпустите его "
                "(Безопасность → HTTPS сертификат) или выключите HTTPS" % path)
    text = WEB_UNIT_TEMPLATE.format(install_dir=INSTALL_DIR, port=port)
    flags = unit_tls_flags(tls)
    if flags:
        text = text.replace(
            "--port %d\n" % port, "--port %d %s\n" % (port, flags), 1)
    write_unit(text)


def write_tg_unit() -> None:
    write_unit(TG_UNIT_TEMPLATE.format(install_dir=INSTALL_DIR))


def daemon_reload() -> subprocess.CompletedProcess:
    return systemctl("daemon-reload", timeout=60)


def restart_service() -> tuple[bool, str]:
    result = systemctl("restart", SERVICE)
    if result.returncode != 0:
        return False, (result.stderr or "").strip()[:300] or "неизвестная ошибка"
    return True, ""


def start_service() -> tuple[bool, str]:
    result = systemctl("start", SERVICE)
    if result.returncode != 0:
        return False, (result.stderr or "").strip()[:300] or "неизвестная ошибка"
    return True, ""


def stop_service() -> tuple[bool, str]:
    """Остановка на время восстановления config (CLI «Восстановление»):
    работающий сервис может перезаписать восстанавливаемый файл."""
    result = systemctl("stop", SERVICE)
    if result.returncode != 0:
        return False, (result.stderr or "").strip()[:300] or "неизвестная ошибка"
    return True, ""


def remove_unit() -> None:
    UNIT_PATH.unlink(missing_ok=True)


def remove_wrapper() -> bool:
    """Удалить /usr/local/bin/bot4vps (создаётся install.sh при установке)."""
    if WRAPPER_PATH.exists():
        WRAPPER_PATH.unlink()
        return True
    return False


def delete_install_dir() -> None:
    """Полное удаление: /opt/bot4vps целиком. Только для пункта
    «Полное удаление» (ввод слова DELETE) и только последним шагом."""
    import shutil as _shutil

    _shutil.rmtree(INSTALL_DIR, ignore_errors=False)


# ─────────────────────────────────────────────
# Firewall (перенос open_web_port / close_web_port из install.sh)
# ─────────────────────────────────────────────

def firewall_open_port(port: int) -> str:
    """Открыть порт Web UI. Возвращает: none | ufw | firewalld | failed.

    nftables с runtime-only конфигурацией не трогаем (паритет с install.sh):
    без известной persistent-конфигурации правило исчезло бы после reboot.
    """
    if shutil.which("ufw"):
        status = run(["ufw", "status"], timeout=15)
        if "active" in (status.stdout or "").lower():
            allowed = run(
                ["ufw", "allow", f"{port}/tcp", "comment", "Bot4VPS Web UI"],
                timeout=30,
            )
            return "ufw" if allowed.returncode == 0 else "failed"

    if shutil.which("firewall-cmd") and systemctl("is-active", "--quiet", "firewalld").returncode == 0:
        added = run(
            ["firewall-cmd", "--permanent", f"--add-port={port}/tcp"],
            timeout=30,
        )
        if added.returncode == 0 and run(["firewall-cmd", "--reload"], timeout=30).returncode == 0:
            return "firewalld"
        return "failed"

    if shutil.which("nft"):
        rules = run(["nft", "list", "ruleset"], timeout=15)
        if (rules.stdout or "").strip():
            return "failed"

    return "none"


def firewall_close_port(port: int) -> bool:
    """Закрыть порт Web UI (ufw/firewalld). Паритет с close_web_port."""
    handled = False
    if shutil.which("ufw"):
        status = run(["ufw", "status"], timeout=15)
        if "active" in (status.stdout or "").lower():
            run(["ufw", "delete", "allow", f"{port}/tcp"], timeout=30)
            handled = True
    if shutil.which("firewall-cmd") and systemctl("is-active", "--quiet", "firewalld").returncode == 0:
        run(["firewall-cmd", "--permanent", f"--remove-port={port}/tcp"], timeout=30)
        run(["firewall-cmd", "--reload"], timeout=30)
        handled = True
    return handled


# ─────────────────────────────────────────────
# Журнал
# ─────────────────────────────────────────────

def journal_follow() -> subprocess.Popen:
    """Живой журнал (journalctl -f). Управление процессом — на вызывающем."""
    return subprocess.Popen(
        ["journalctl", "-u", SERVICE, "-f", "-n", "50", "--no-pager"],
        stdout=None,
    )


# ─────────────────────────────────────────────
# Прочее
# ─────────────────────────────────────────────

def detect_ip() -> str:
    """IP сервера для отображения адреса Web. Паритет с install.sh."""
    result = run(["hostname", "-I"], timeout=10)
    fields = (result.stdout or "").split()
    if fields:
        return fields[0]
    route = run(["ip", "-4", "route", "get", "1.1.1.1"], timeout=10)
    parts = (route.stdout or "").split()
    for i, part in enumerate(parts):
        if part == "src" and i + 1 < len(parts):
            return parts[i + 1]
    return "<IP-сервера>"
