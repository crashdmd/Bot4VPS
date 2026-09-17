# -*- coding: utf-8 -*-
"""Управление сервис-уровнем установленной 3x-ui — действия карточки (этап 4).

Три слоя их CLI (видение, изучен x-ui.sh):
    1. ``x-ui setting ...`` — неинтерактивные обёртки над бинарником →
       смена логина/пароля, порт, web base path, сброс настроек;
    2. systemd — старт/стоп/рестарт/автостарт (наша машинерия юнитов);
    3. bash-меню — НЕ эмулируем; своим кодом только BBR (sysctl) и
       обновление geo-файлов (те же URL, что их download_geo).

Их firewall/SSH-форвардинг/SSL/Postgres-меню не дублируем.

После каждой смены аккаунта переписываем /etc/x-ui/install-result.env
(паритет с офф-скриптом: root 600, %q-экранирование) — кэш панели бота
обновляется последующим sync (роутер вызывает его автоматически).
"""
from __future__ import annotations

import posixpath
import shlex
from typing import Any, Dict, Optional

from core.integrator import StepError
from core.ssh import exec_sudo

from . import templates

# systemd: xray — дочерний процесс панели, отдельной subcommand у их
# бинарника нет (в их меню рестарт Xray = рестарт x-ui.service).
UNIT_COMMANDS = {
    "start": "systemctl start x-ui",
    "stop": "systemctl stop x-ui",
    "restart": "systemctl restart x-ui",
    "restart_xray": "systemctl restart x-ui",
}

UNIT_TITLES = {
    "start": "запуск", "stop": "остановка",
    "restart": "перезапуск", "restart_xray": "перезапуск (вместе с Xray)",
}

# geo-даты их релиза (Loyalsoldier/v2ray-rules-dat) — те же URL, что
# download_geo офф-скрипта; качаем на сервер (его канал), с ретраями.
_GEO_FILES = ("geoip.dat", "geosite.dat")
_GEO_URL = "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/"


def _probe(ssh, server: dict, command: str) -> str:
    code, out, _ = exec_sudo(ssh, server, command, timeout=60)
    return out.strip()


def _run(ssh, server: dict, command: str, *, step: str, title: str) -> str:
    """Команда с проверкой кода возврата → StepError с stderr при провале."""
    code, out, err = exec_sudo(ssh, server, command, timeout=120)
    if code != 0:
        raise StepError(step, code, title=title,
                        detail=(err or out or "команда завершилась с ошибкой").strip()[:500])
    return out.strip()


# ------------------------------------------------------------------
# systemd-юнит
# ------------------------------------------------------------------

def unit_action(ssh, server: dict, action: str) -> str:
    """start/stop/restart/restart_xray. Возвращает is-active после команды."""
    cmd = UNIT_COMMANDS.get(action)
    if not cmd:
        raise StepError("unit_action", -1, title="Управление сервисом",
                        detail=f"неизвестное действие: {action}")
    _run(ssh, server, cmd, step=f"unit_{action}",
         title=UNIT_TITLES.get(action, action))
    return _probe(ssh, server, "systemctl is-active x-ui 2>/dev/null") or "unknown"


def set_autostart(ssh, server: dict, enabled: bool) -> bool:
    """enable/disable автозапуска. Возвращает is-enabled после команды."""
    cmd = "systemctl enable x-ui" if enabled else "systemctl disable x-ui"
    _run(ssh, server, cmd, step="autostart", title="Автозагрузка x-ui")
    return _probe(ssh, server, "systemctl is-enabled x-ui 2>/dev/null") == "enabled"


def fetch_logs(ssh, server: dict, tail: int = 200) -> str:
    """journalctl по юниту x-ui (включая вывод Xray — дочерний процесс)."""
    tail = max(1, min(int(tail or 200), 2000))
    code, out, _ = exec_sudo(
        ssh, server,
        f"journalctl -u x-ui -n {tail} --no-pager -o short-iso 2>/dev/null",
        timeout=60,
    )
    return out if code == 0 else ""


# ------------------------------------------------------------------
# install-result.env: точечное обновление после смены аккаунта
# ------------------------------------------------------------------

def read_install_result(ssh, server: dict) -> Dict[str, str]:
    out = _probe(
        ssh, server,
        f"if [ -r {templates.XUI_INSTALL_RESULT} ]; then cat {templates.XUI_INSTALL_RESULT}; fi",
    )
    result: Dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line or "=" not in line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip("'").strip('"')
    return result


def write_install_result(ssh, server: dict, values: Dict[str, str]) -> None:
    """Перезаписать install-result.env (формат офф-скрипта: %q, root 600)."""
    def q(v: str) -> str:
        return "'" + str(v).replace("'", "'\\''") + "'"

    lines = " ".join(f"printf '%s=%q\\n' {k} {q(v)};" for k, v in values.items())
    _run(
        ssh, server,
        f"install -d -m 700 {templates.XUI_ETC} && "
        f"(umask 077; {{ {lines} }} > {templates.XUI_INSTALL_RESULT}) && "
        f"chmod 600 {templates.XUI_INSTALL_RESULT}",
        step="write_install_result", title="Запись install-result.env",
    )


def patch_install_result(ssh, server: dict, updates: Dict[str, str]) -> Dict[str, str]:
    """Прочитать env, наложить изменения, перезаписать. Возвращает итог."""
    values = read_install_result(ssh, server)
    values.update({k: str(v) for k, v in updates.items() if v is not None})
    write_install_result(ssh, server, values)
    return values


def read_settings_show(ssh, server: dict) -> Dict[str, Optional[str]]:
    """Разобрать ``x-ui setting -show true`` (port/webBasePath/username)."""
    from .service import _grep_setting
    text = _probe(
        ssh, server,
        f"{templates.XUI_FOLDER}/x-ui setting -show true 2>/dev/null",
    )
    return {
        "port": _grep_setting(text, "port"),
        "web_base_path": _grep_setting(text, "webBasePath"),
        "username": _grep_setting(text, "username"),
    }


# ------------------------------------------------------------------
# Аккаунт панели (x-ui setting …)
# ------------------------------------------------------------------

def _setting(ssh, server: dict, args: str, *, step: str, title: str) -> None:
    """Выполнить ``x-ui setting <args>`` с проверкой кода возврата.

    Значения пользовательского ввода (логин/пароль/path) вызывающие
    передают уже shlex-экранированными — интерполяции «сырого» ввода
    в команду здесь нет."""
    _run(ssh, server, f"{templates.XUI_FOLDER}/x-ui setting {args}",
         step=step, title=title)


def change_username(ssh, server: dict, username: str, restart: bool) -> str:
    """Смена логина; env обновляем точечно (пароль не трогаем — он не
    читается извне, остаётся прежним)."""
    _setting(ssh, server, f"-username {shlex.quote(username)}",
             step="change_username", title="Смена логина панели")
    if restart:
        unit_action(ssh, server, "restart")
    patch_install_result(ssh, server, {"XUI_USERNAME": username})
    return username


def change_password(ssh, server: dict, password: str, restart: bool) -> None:
    """Смена пароля. ВАЖНО (видение): пароль меняется только через бота —
    иначе рассинхрон наших секретов; после смены env + кэш обновятся."""
    _setting(ssh, server, f"-password {shlex.quote(password)}",
             step="change_password", title="Смена пароля панели")
    if restart:
        unit_action(ssh, server, "restart")
    patch_install_result(ssh, server, {"XUI_PASSWORD": password})


def panel_display_host(server: dict) -> str:
    """Хост для адреса панели 3x-ui: домен — первым, IP — только если
    домена нет.

    Приоритет: host-домен > ssl_host-домен > host (IP). Сервер,
    добавленный по IP с позднее вписанным доменом (ssl_host), раньше
    показывал IP в колонке «Панель» — и «Перейти ↗» открывал IP."""
    from core.dns_resolve import is_ip_literal

    host = str(server.get("host") or "").strip()
    if host and not is_ip_literal(host):
        return host
    ssl = str(server.get("ssl_host") or "").strip()
    if ssl and not is_ip_literal(ssl):
        return ssl
    return host


def change_port(ssh, server: dict, port: int, restart: bool,
                close_old_port: bool = True) -> Dict[str, Any]:
    """Смена порта панели. Возвращает {port, url}: адрес пересобирается из
    актуальных значений (webBasePath читаем заново).

    Новый порт открываем в firewall всегда (иначе панель недоступна);
    close_old_port управляет только закрытием старого (ядро
    quick_setup.firewall — та же машина, что у установщика). Firewall
    нет/не определился — не ошибка, честная строка в выводе."""
    # старый порт знаем только ДО смены
    old_port = None
    try:
        old_port = int((read_settings_show(ssh, server).get("port") or "").strip())
    except (TypeError, ValueError):
        old_port = None
    _setting(ssh, server, f"-port {int(port)}",
             step="change_port", title="Смена порта панели")
    if restart:
        unit_action(ssh, server, "restart")
    settings = read_settings_show(ssh, server)
    actual_port = (settings.get("port") or str(port)).strip()
    path = (settings.get("web_base_path") or "").strip("/")
    host = panel_display_host(server)
    scheme = _detect_scheme(ssh, server)
    url = f"{scheme}://{host}:{actual_port}/{path}"
    patch_install_result(ssh, server, {
        "XUI_PANEL_PORT": actual_port,
        "XUI_ACCESS_URL": url,
    })
    fw_notes: list[str] = []
    if old_port and old_port != int(actual_port):
        fw_notes = _sync_firewall_ports(ssh, server, int(actual_port), old_port,
                                        close_old_port=close_old_port)
    out_extra = ("; " + "; ".join(fw_notes)) if fw_notes else ""
    return {"port": actual_port, "panel_url": url, "fw_notes": out_extra}


def _sync_firewall_ports(ssh, server: dict, new_port: int, old_port: int,
                         close_old_port: bool = True) -> list[str]:
    """Открыть новый порт панели в firewall (всегда) и закрыть старый
    (по флагу).

    Не роняет смену порта при ошибке firewall — возвращаем строки для
    вывода (админ должен видеть, что правило придётся поправить руками)."""
    from core.quick_setup.firewall import close_port_on_ssh, open_port_on_ssh
    notes: list[str] = []
    try:
        m = open_port_on_ssh(ssh, server, new_port, "tcp")
        if m.ok and m.verified:
            notes.append(f"порт {new_port}/tcp открыт в firewall")
        else:
            notes.append(f"НЕ удалось открыть порт {new_port}/tcp в firewall "
                         f"({m.error or m.message}) — правило нужно добавить вручную")
    except Exception as e:
        notes.append(f"firewall, порт {new_port}: {e}")
    if close_old_port and old_port != new_port:
        try:
            m = close_port_on_ssh(ssh, server, old_port, "tcp")
            if m.ok and m.verified:
                notes.append(f"старый порт {old_port}/tcp закрыт в firewall")
            else:
                notes.append(f"старый порт {old_port}/tcp НЕ закрыт "
                             f"({m.error or m.message}) — закройте вручную")
        except Exception as e:
            notes.append(f"firewall, порт {old_port}: {e}")
    return notes


def change_path(ssh, server: dict, path: Optional[str], restart: bool) -> Dict[str, Any]:
    """Изменение web base path: свой путь или случайный (path=None — как при
    установке). Возвращает {path, url}."""
    from .validation import validate_web_base_path
    import secrets
    new_path = validate_web_base_path(
        path if path else
        "".join(secrets.choice("abcdefghijkmnpqrstuvwxyz23456789") for _ in range(18))
    )
    _setting(ssh, server, f"-webBasePath {shlex.quote(new_path)}",
             step="change_path", title="Изменение web base path")
    if restart:
        unit_action(ssh, server, "restart")
    settings = read_settings_show(ssh, server)
    actual_path = (settings.get("web_base_path") or new_path).strip("/")
    port = (settings.get("port") or "").strip()
    host = panel_display_host(server)
    scheme = _detect_scheme(ssh, server)
    url = f"{scheme}://{host}:{port}/{actual_path}"
    patch_install_result(ssh, server, {
        "XUI_WEB_BASE_PATH": actual_path,
        "XUI_ACCESS_URL": url,
    })
    return {"web_base_path": actual_path, "panel_url": url}


def reset_settings(ssh, server: dict, restart: bool) -> Dict[str, Any]:
    """Полный сброс настроек панели (их ``-reset``): креды/порт/path
    возвращаются к дефолтам admin/admin, порт читаем заново из -show.
    env перезаписываем целиком — старые креды недействительны."""
    _setting(ssh, server, "-reset true",
             step="reset_settings", title="Сброс настроек панели")
    if restart:
        unit_action(ssh, server, "restart")
    settings = read_settings_show(ssh, server)
    port = (settings.get("port") or "").strip()
    path = (settings.get("web_base_path") or "").strip("/")
    host = panel_display_host(server)
    url = f"http://{host}:{port}/{path}"
    values = read_install_result(ssh, server)
    values.update({
        "XUI_USERNAME": "admin",
        "XUI_PASSWORD": "admin",
        "XUI_PANEL_PORT": port,
        "XUI_WEB_BASE_PATH": path,
        "XUI_ACCESS_URL": url,
    })
    write_install_result(ssh, server, values)
    return {"port": port, "web_base_path": path, "panel_url": url}


def _detect_scheme(ssh, server: dict) -> str:
    """Схема URL: сертификат настроен → https (как _read_live)."""
    from .service import _grep_setting
    cert = _probe(
        ssh, server,
        f"{templates.XUI_FOLDER}/x-ui setting -getCert true 2>/dev/null",
    )
    return "https" if _grep_setting(cert, "cert") else "http"


# ------------------------------------------------------------------
# BBR (слой 3: свой sysctl-код, паттерн их disable_bbr)
# ------------------------------------------------------------------

def set_bbr(ssh, server: dict, enable: bool) -> Dict[str, str]:
    """Вкл/выкл BBR через /etc/sysctl.d/99-bbr-x-ui.conf.

    Вкл: текущие qdisc/cc сохраняются в комментарии первой строки файла —
    откат при выключении (паттерн офф-скрипта). Возвращает актуальные
    значения net.core.default_qdisc / net.ipv4.tcp_congestion_control."""
    if enable:
        # В некоторых дистрибутивах BBR собран модулем и не появляется в
        # tcp_available_congestion_control, пока модуль не загружен. Попытка
        # загрузки безопасна; после неё обязательно проверяем реальную
        # доступность до записи sysctl-файла, иначе не оставляем сломанный
        # /etc/sysctl.d/99-bbr-x-ui.conf на ядре без BBR.
        _probe(ssh, server, "modprobe tcp_bbr 2>/dev/null || true")
        available = _probe(
            ssh, server,
            "sysctl -n net.ipv4.tcp_available_congestion_control 2>/dev/null",
        )
        if "bbr" not in available.split():
            # Старый путь писал файл до проверки ядра; подчистим только наш
            # собственный sysctl-файл, чтобы следующая загрузка не пыталась
            # применить несуществующий алгоритм.
            _probe(ssh, server, f"rm -f {templates.BBR_SYSCTL_FILE}")
            choices = available or "не определены"
            raise StepError(
                "bbr_unsupported", -1, title="Включение BBR",
                detail=("Ядро сервера не поддерживает BBR. Доступные алгоритмы: "
                        f"{choices}. Установите ядро с поддержкой TCP BBR и повторите попытку."),
            )
        qdisc = _probe(ssh, server, "sysctl -n net.core.default_qdisc 2>/dev/null")
        cc = _probe(ssh, server, "sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null")
        _sftp_write_file(ssh, server, templates.BBR_SYSCTL_FILE,
                         templates.bbr_sysctl_conf(qdisc or "fq_cubic", cc or "cubic"))
        _run(ssh, server,
             f"sysctl -p {templates.BBR_SYSCTL_FILE} >/dev/null && "
             "test \"$(sysctl -n net.ipv4.tcp_congestion_control)\" = bbr",
             step="bbr_enable", title="Включение BBR")
    else:
        # предыдущие значения — из комментария первой строки файла
        prev = _probe(
            ssh, server,
            f"head -n1 {templates.BBR_SYSCTL_FILE} 2>/dev/null | sed -n 's/^#\\(.*\\):\\(.*\\)$/\\1 \\2/p'",
        )
        qdisc, cc = "fq_cubic", "cubic"
        if " " in prev:
            qdisc, _, cc = prev.partition(" ")
            qdisc, cc = qdisc.strip() or qdisc, cc.strip() or cc
        _run(ssh, server,
             f"sysctl -w net.core.default_qdisc={qdisc} "
             f"net.ipv4.tcp_congestion_control={cc} >/dev/null && "
             f"rm -f {templates.BBR_SYSCTL_FILE}",
             step="bbr_disable", title="Отключение BBR")
    return {
        "qdisc": _probe(ssh, server, "sysctl -n net.core.default_qdisc 2>/dev/null"),
        "cc": _probe(ssh, server, "sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null"),
    }


def read_bbr_state(ssh, server: dict) -> Dict[str, Any]:
    """Состояние BBR для карточки: текущий cc и управляемость нашим файлом."""
    cc = _probe(ssh, server, "sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null")
    managed = _probe(
        ssh, server,
        f"test -f {templates.BBR_SYSCTL_FILE} && echo yes || echo no",
    ) == "yes"
    return {"cc": cc or None, "enabled": cc == "bbr", "managed": managed}


# ------------------------------------------------------------------
# Geo-файлы (слой 3: их download_geo, наши руки)
# ------------------------------------------------------------------

def update_geo(ssh, server: dict, restart: bool = True) -> Dict[str, str]:
    """Скачать свежие geoip.dat/geosite.dat в bin/ (те же URL, что их меню),
    затем рестарт панели (подхватывает файлы). Возвращает даты файлов."""
    parts = [f"cd {templates.XUI_FOLDER}/bin"]
    for name in _GEO_FILES:
        parts.append(
            f"curl -fL --connect-timeout 15 --max-time 300 "
            f"--retry 3 --retry-delay 5 -o {name}.new {_GEO_URL}{name} && "
            f"mv {name}.new {name}"
        )
    _run(ssh, server, " && ".join(parts), step="update_geo",
         title="Обновление geo-файлов (geoip/geosite)")
    if restart:
        unit_action(ssh, server, "restart")
    return read_geo_state(ssh, server)


def read_geo_state(ssh, server: dict) -> Dict[str, str]:
    """Даты geo-файлов для карточки: {geoip.dat: 'YYYY-MM-DD', …}.
    Глоб `/usr/local/x-ui/bin/geo*.dat` раскрывается в абсолютные пути —
    берём basename (карточка показывает имена файлов)."""
    out = _probe(
        ssh, server,
        f"ls -l --time-style=+%Y-%m-%d {templates.XUI_FOLDER}/bin/geo*.dat 2>/dev/null "
        "| awk '{print $6, $7}'",
    )
    dates: Dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2:
            dates[posixpath.basename(parts[1])] = parts[0]
    return dates


def _sftp_write_file(ssh, server: dict, dest: str, content: str) -> None:
    """SFTP → /tmp → atomic move (паттерн WG templates/installer)."""
    tmp_path = "/tmp/bot4vps_xui_" + posixpath.basename(dest)
    sftp = ssh.open_sftp()
    try:
        with sftp.file(tmp_path, "w") as f:
            f.write(content)
    finally:
        sftp.close()
    dest_dir = posixpath.dirname(dest)
    _run(ssh, server,
         f"install -d -m 755 {dest_dir} && mv {tmp_path} {dest} && chmod 644 {dest}",
         step="write_file", title=f"Запись {dest}")
