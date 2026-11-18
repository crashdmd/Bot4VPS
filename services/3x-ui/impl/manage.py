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
import re
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


def _run(ssh, server: dict, command: str, *, step: str, title: str, timeout: int = 120) -> str:
    """Команда с проверкой кода возврата → StepError с stderr при провале."""
    code, out, err = exec_sudo(ssh, server, command, timeout=timeout)
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
    return parse_install_result(out)


def parse_install_result(out: str) -> Dict[str, str]:
    """Разобрать shell-экранированные значения без выполнения env-файла."""
    result: Dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line or "=" not in line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not re.fullmatch(r"XUI_[A-Z0-9_]+", key):
            continue
        value = value.strip()
        if value.startswith("$'") and value.endswith("'"):
            # Bash printf %q использует ANSI-C quoting для непечатных байтов.
            body = value[2:-1]
            decoded = bytearray()
            i = 0
            escapes = {"a": 7, "b": 8, "e": 27, "E": 27, "f": 12,
                       "n": 10, "r": 13, "t": 9, "v": 11, "\\": 92, "'": 39, '"': 34}
            while i < len(body):
                if body[i] != "\\":
                    decoded.extend(body[i].encode("utf-8")); i += 1
                    continue
                i += 1
                if i >= len(body):
                    raise ValueError("Неверное экранирование install-result.env")
                char = body[i]
                if char in escapes:
                    decoded.append(escapes[char]); i += 1
                else:
                    match = re.match(r"[0-7]{1,3}", body[i:])
                    if match:
                        decoded.append(int(match.group(), 8)); i += len(match.group())
                    elif char in "xuU":
                        limit = {"x": 2, "u": 4, "U": 8}[char]
                        match = re.match(r"[0-9a-fA-F]{1," + str(limit) + "}", body[i+1:])
                        if not match:
                            raise ValueError("Неверное экранирование install-result.env")
                        number = int(match.group(), 16)
                        decoded.extend(bytes([number]) if char == "x" else chr(number).encode("utf-8"))
                        i += 1 + len(match.group())
                    else:
                        raise ValueError("Неподдерживаемое экранирование install-result.env")
            result[key] = decoded.decode("utf-8")
        else:
            parts = shlex.split(value, posix=True)
            if len(parts) > 1:
                raise ValueError("Неверный формат install-result.env")
            result[key] = parts[0] if parts else ""
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

def require_setting_cli(ssh, server: dict, flags: set[str]) -> None:
    """Проверить контракт живого бинарника; версии и флаги не кэшируем."""
    code, out, err = exec_sudo(
        ssh, server, f"{templates.XUI_FOLDER}/x-ui setting -h", timeout=30)
    help_text = (out or "") + "\n" + (err or "")
    declarations = dict(re.findall(r"(?m)^\s+-([A-Za-z][A-Za-z0-9]*)(?:[^\S\n]+(string|int))?[^\S\n]*$", help_text))
    available = set(declarations)
    missing = sorted(flags - available)
    types = {"username": "string", "password": "string", "port": "int",
             "webBasePath": "string", "webCert": "string", "webCertKey": "string", "reset": ""}
    changed = sorted(flag for flag in flags & available if flag in types and declarations[flag] != types[flag])
    if code not in (0, 2) or "Usage of setting:" not in help_text or not available or missing or changed:
        version = _probe(ssh, server, f"{templates.XUI_FOLDER}/x-ui -v")
        version = version if re.fullmatch(r"v?\d+(?:\.\d+){1,3}[-+a-zA-Z0-9.]*", version) else "неизвестна"
        detail = ("не поддерживает параметры " + ", ".join("-" + flag for flag in missing)
                  if available and missing else
                  "изменились типы параметров " + ", ".join("-" + flag for flag in changed)
                  if changed else "не удалось прочитать справку команды setting")
        raise StepError("cli_compatibility", -1, title="Несовместимый CLI 3x-ui",
                        detail=f"Версия {version}: {detail}. Действие не запущено; требуется обновление интеграции.")


def _setting(ssh, server: dict, args: str, *, step: str, title: str,
             expected: tuple[str, ...] = (), secrets: tuple[str, ...] = ()) -> None:
    """Проверить параметры CLI до мутации и его ответ после выполнения.

    Значения пользовательского ввода (логин/пароль/path) вызывающие
    передают уже shlex-экранированными — интерполяции «сырого» ввода
    в команду здесь нет."""
    words = shlex.split(args)
    flags = {words[i][1:].split("=", 1)[0] for i in range(0, len(words), 2)}
    require_setting_cli(ssh, server, flags)
    try:
        code, out, err = exec_sudo(
            ssh, server, f"{templates.XUI_FOLDER}/x-ui setting {args}", timeout=120)
    except Exception:
        raise StepError(step, -1, title=title,
                        detail="Ответ CLI не получен. Результат не подтверждён; проверьте панель перед повтором.") from None
    text = (out or "") + "\n" + (err or "")
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    failure = re.search(r"(?im)^.*(?:\bfailed\b|\berror\b|flag provided but not defined|warning: ignored).*$", text)
    if code != 0 or failure:
        detail = failure.group().strip() if failure else (err or out or "команда завершилась с ошибкой").strip()
        for secret in secrets:
            for representation in (secret, shlex.quote(secret)):
                if representation:
                    detail = detail.replace(representation, "[скрыто]")
        raise StepError(step, code if code != 0 else -1, title=title, detail=detail[:500])
    if expected and not all(re.search(pattern, text, re.I | re.M) for pattern in expected):
        raise StepError("cli_compatibility", -1, title="Ответ CLI 3x-ui не распознан",
                        detail="CLI не подтвердил изменение. Его формат или поведение могло измениться; "
                               "проверьте панель перед повтором. Сохранённые данные бота не обновлены.")


def change_credentials(ssh, server: dict, username: str, password: str, restart: bool) -> None:
    """Одна команда с обоими значениями: поддерживается текущим CLI.

    CLI UpdateFirstUser сохраняет 2FA. Вывод с exit 0 не является успехом
    без явного подтверждения совместного обновления учётных данных.
    """
    _setting(ssh, server, f"-username {shlex.quote(username)} -password {shlex.quote(password)}",
             step="change_credentials", title="Смена логина и пароля панели",
             expected=(r"^\s*Username and password (?:updated|set) successfully[.!]?\s*$",),
             secrets=(password,))
    try:
        patch_install_result(ssh, server, {"XUI_USERNAME": username, "XUI_PASSWORD": password})
    except Exception:
        raise StepError("write_install_result", -1, title="Учётные данные изменены",
                        detail="CLI подтвердил смену логина и пароля, но сохранить их для бота не удалось. "
                               "Используйте введённые данные для входа; повторная смена не требуется.") from None
    if restart:
        try:
            unit_action(ssh, server, "restart")
        except Exception:
            raise StepError("credentials_restart", -1, title="Учётные данные изменены и сохранены",
                            detail="Перезапуск панели не подтверждён. Проверьте её состояние; повторная смена не требуется.") from None


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
    from core.ssh import private_remote_directory
    from .geo import commit_command
    was_active = False
    if restart:
        state = _run(ssh, server, 'systemctl show x-ui -p ActiveState --value',
                     step='geo_state', title='Состояние 3x-ui перед обновлением')
        if state not in {'active', 'inactive', 'failed'}:
            raise StepError('geo_state', -1, title='Обновление geo-файлов',
                            detail='Не удалось определить стабильное состояние 3x-ui. Повторите проверку.')
        was_active = state == 'active'
    with private_remote_directory(ssh, server, privileged=True) as directory:
        for name in _GEO_FILES:
            path = shlex.quote(directory + '/' + name)
            _run(ssh, server,
                 f'curl -fL --connect-timeout 15 --max-time 300 --retry 3 --retry-delay 5 '
                 f'-o {path} {shlex.quote(_GEO_URL + name)} && test -s {path} && '
                 f'test "$(stat -c %s -- {path})" -le 134217728 && '
                 f'test "$(od -An -tu1 -N1 -- {path} | tr -d " \\n")" = 10',
                 step='update_geo', title=f'Загрузка и проверка {name}', timeout=1260)
        _run(ssh, server, commit_command(templates.XUI_FOLDER + '/bin', directory, restart, was_active),
             step='update_geo', title='Применение пары geoip/geosite', timeout=240)
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
    from core.ssh import private_remote_upload
    with private_remote_upload(ssh, server, content) as tmp_path:
        dest_dir = posixpath.dirname(dest)
        _run(ssh, server,
             f"install -d -m 755 {shlex.quote(dest_dir)} && install -m 644 {shlex.quote(tmp_path)} {shlex.quote(dest)}",
             step="write_file", title=f"Запись {dest}")
