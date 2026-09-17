# -*- coding: utf-8 -*-
"""Сертификат панели 3x-ui — зеркало их CLI-меню x-ui.sh (опция 20,
«SSL Certificate Management»).

Принцип (пользователь): карточка дублирует CLI, чтобы не лезть в консоль.
Управляет не бот, а администратор — через карточку, на сервере где стоит
3x-ui. Их интерактивный bash (read/confirm) НЕ эмулируем: выполняем те же
команды неинтерактивно, все выборы администратор делает в модалке.

Соответствие их пунктам:
  1 Get SSL (Domain)       → issue_domain (acme.sh + socat, LE standalone)
  2 Revoke & Remove        → remove_cert  (+ сброс путей панели, если ссылаются)
  3 Force Renew            → renew        (acme.sh --renew --force)
  4 Show Existing Domains  → read_state   (домены /root/cert + серт панели)
  5 Set Cert paths         → set_paths    (x-ui setting -webCert/-webCertKey)
  6 Get SSL for IP         → issue_ip     (shortlived ~6 дней, auto-renew)

Их Cloudflare-флоу (ssl_cert_issue_CF) — отдельный пункт их ГЛАВНОГО меню,
не части SSL-меню: не дублируем.
"""
from __future__ import annotations

import shlex
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.integrator import StepError
from core.ssh import exec_sudo

from . import templates
from .manage import panel_display_host, read_settings_show, unit_action
from .validation import (
    validate_certificate_identifier,
    validate_cert_path,
    validate_domain,
    validate_ipv4,
    validate_ipv6,
)

ACME = "/root/.acme.sh/acme.sh"
CERT_ROOT = "/root/cert"

# socat: тот же выбор пакетного менеджера, что в их ssl_cert_issue
_SOCAT_INSTALL = {
    "debian": "apt-get update -qq && apt-get install -y -qq socat",
    "ubuntu": "apt-get update -qq && apt-get install -y -qq socat",
    "armbian": "apt-get update -qq && apt-get install -y -qq socat",
    "fedora": "dnf makecache -y -q && dnf -y -q install socat",
    "amzn": "dnf makecache -y -q && dnf -y -q install socat",
    "virtuozzo": "dnf makecache -y -q && dnf -y -q install socat",
    "rhel": "dnf makecache -y -q && dnf -y -q install socat",
    "almalinux": "dnf makecache -y -q && dnf -y -q install socat",
    "rocky": "dnf makecache -y -q && dnf -y -q install socat",
    "ol": "dnf makecache -y -q && dnf -y -q install socat",
    "centos": "yum makecache -q -y && yum -y -q install socat",
    "arch": "pacman -Sy --noconfirm socat",
    "manjaro": "pacman -Sy --noconfirm socat",
    "parch": "pacman -Sy --noconfirm socat",
    "opensuse-tumbleweed": "zypper -q refresh && zypper -q install -y socat",
    "opensuse-leap": "zypper -q refresh && zypper -q install -y socat",
    "alpine": "apk add socat curl openssl",
}


def _probe(ssh, server: dict, command: str) -> str:
    code, out, _ = exec_sudo(ssh, server, command, timeout=60)
    return out.strip()


def _run(ssh, server: dict, command: str, *, step: str, title: str,
         timeout: int = 180) -> str:
    code, out, err = exec_sudo(ssh, server, command, timeout=timeout)
    if code != 0:
        raise StepError(step, code, title=title,
                        detail=(err or out or "команда завершилась с ошибкой").strip()[:500])
    return out.strip()


# ------------------------------------------------------------------
# Чтение состояния (их пункт 4)
# ------------------------------------------------------------------

def _parse_expiry(raw: str) -> Optional[str]:
    """'Sep 15 12:34:56 2026 GMT' (openssl enddate) → '2026-09-15'.
    Не разобралось — отдаём как есть (карточке всё равно информативнее)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z").strftime("%Y-%m-%d")
    except ValueError:
        return raw


def read_state(ssh, server: dict, cert_file: Optional[str] = None) -> Dict[str, Any]:
    """Состояние сертификатов для карточки: наличие acme.sh/certbot, домены
    обоих движков с датами, срок и ВЛАДЕЛЕЦ серта панели (движок, чей файл
    назначен панели — определяем по пути).

    ``cert_file`` — путь серта панели, если вызывающий его уже прочитал
    (getCert в _read_live) — не пробиваем повторно."""
    # один пробой: acme.sh + certbot + домены с датами (без отдельного
    # openssl на каждый). Домены /root/cert — через find (как их скрипт):
    # пустой glob иначе даёт литеральный '*'
    out = _probe(ssh, server,
                 f"command -v {ACME} >/dev/null 2>&1 && echo acme:yes || echo acme:no; "
                 f"command -v certbot >/dev/null 2>&1 && echo cb:yes || echo cb:no; "
                 f'for d in $(find {CERT_ROOT} -mindepth 1 -maxdepth 1 -type d 2>/dev/null); do '
                 'n=$(basename "$d"); '
                 'if [ -f "$d/fullchain.pem" ] && [ -f "$d/privkey.pem" ]; then '
                 'e=$(openssl x509 -noout -enddate -in "$d/fullchain.pem" 2>/dev/null | cut -d= -f2-); '
                 'else e=""; fi; echo "dom:$n|$e"; done; '
                 'for r in /etc/letsencrypt/renewal/*.conf; do '
                 '[ -f "$r" ] || continue; echo "cbdom:$(basename "$r" .conf)"; done')
    acme = False
    certbot = False
    domains: Dict[str, Optional[str]] = {}
    cb_domains: List[str] = []
    for line in out.splitlines():
        line = line.strip()
        if line == "acme:yes":
            acme = True
        elif line == "cb:yes":
            certbot = True
        elif line.startswith("dom:"):
            name, _, exp = line[4:].partition("|")
            if name:
                domains[name] = _parse_expiry(exp)
        elif line.startswith("cbdom:"):
            cb_domains.append(line[6:])
    panel_expires = None
    panel_engine = None
    if cert_file:
        panel_expires = _parse_expiry(_probe(ssh, server,
            f"openssl x509 -noout -enddate -in {shlex.quote(cert_file)} 2>/dev/null | cut -d= -f2-"))
        # владелец по пути: наш выпуск всегда кладёт в /root/cert/<домен>/,
        # certbot — /etc/letsencrypt/live/<домен>/. Иной путь (админ вручную)
        # — честное «другое», движок продления неизвестен.
        cf = str(cert_file)
        if cf.startswith(f"{CERT_ROOT}/"):
            panel_engine = "acme"
        elif cf.startswith("/etc/letsencrypt/live/"):
            panel_engine = "certbot"
        else:
            panel_engine = "other"
    return {"acme": acme, "certbot": certbot, "domains": domains,
            "certbot_domains": cb_domains, "panel_expires": panel_expires,
            "panel_engine": panel_engine}


# ------------------------------------------------------------------
# Общие шаги выпуска (их install_acme + socat из ssl_cert_issue)
# ------------------------------------------------------------------

def _ensure_acme(ssh, server: dict) -> None:
    if _probe(ssh, server, f"test -x {ACME} && echo yes") == "yes":
        return
    # их install_acme: официальный установщик, ~root
    _run(ssh, server, f"cd /root && curl -s https://get.acme.sh | sh",
         step="acme_install", title="Установка acme.sh", timeout=180)


def _ensure_socat(ssh, server: dict) -> None:
    if _probe(ssh, server, "command -v socat >/dev/null && echo yes") == "yes":
        return
    rid = _probe(ssh, server, ". /etc/os-release 2>/dev/null; echo $ID")
    cmd = _SOCAT_INSTALL.get(rid)
    if not cmd:
        raise StepError("socat", -1, title="Установка socat",
                        detail=f"дистрибутив не поддерживается: {rid or 'неизвестен'}")
    _run(ssh, server, cmd, step="socat", title="Установка socat", timeout=300)


def _listen_flag(ssh, server: dict) -> str:
    """Их acme_listen_flag: нет глобального IPv4 → --listen-v6."""
    v4 = _probe(ssh, server,
                "ip -4 addr show scope global 2>/dev/null | grep -q 'inet ' && echo yes || echo no")
    return "" if v4 == "yes" else "--listen-v6"


def _cleanup_acme(ssh, server: dict, idents: List[str]) -> None:
    """Убрать состояние acme.sh по идентификаторам (их cleanup при провале)."""
    for ident in idents:
        _probe(ssh, server,
               f"{ACME} --revoke -d {shlex.quote(ident)} >/dev/null 2>&1; "
               f"{ACME} --remove -d {shlex.quote(ident)} >/dev/null 2>&1; "
               f"rm -rf /root/.acme.sh/{shlex.quote(ident)} /root/.acme.sh/{shlex.quote(ident)}_ecc")


# ------------------------------------------------------------------
# Комбо, которого нет в их CLI: подготовить HTTP-порт к standalone-выпуску
# acme.sh и вернуть всё как было. Владелец порта — мы: открыли в firewall
# сами → закроем; остановили чужой systemd-юнит → запустим. Чужие
# не-systemd процессы не трогаем (kill без известного способа старта
# оставит сервер сломанным) — честная ошибка с именем процесса.
# ------------------------------------------------------------------

class _HttpPortLease:
    """Что комбо изменило на сервере ради выпуска (для отката)."""

    def __init__(self, port: Optional[int] = None) -> None:
        self.port: Optional[int] = port
        self.firewall_opened: bool = False      # порт 80 открыли мы
        self.stopped_unit: Optional[str] = None  # юнит, который остановили мы


def _prepare_http_port(ssh, server: dict, port: int,
                       emit=lambda line: None) -> _HttpPortLease:
    """Перед standalone-выпуском: порт должен быть открыт в firewall и свободен.

    1. Firewall: open_port_on_ssh идемпотентен; existed_before=True — уже был
       открыт, откат не нужен. Ошибка открытия — не роняем (выпуск ещё может
       пройти: firewall может отсутствовать вообще), но честно сообщаем.
    2. Занятость: ss -tlnp называет процесс. systemd-юнит (nginx, apache,
       сам x-ui) — останавливаем и запоминаем; не-systemd процесс — StepError:
       его судьбу после kill мы не знаем.
    """
    lease = _HttpPortLease(port=int(port))
    from core.quick_setup.firewall import open_port_on_ssh
    try:
        m = open_port_on_ssh(ssh, server, int(port), "tcp")
        if m.ok and m.verified:
            lease.firewall_opened = not m.existed_before
            if lease.firewall_opened:
                emit(f"Порт {port}/tcp открыт в firewall (на время выпуска)")
        else:
            emit(f"[!] firewall, порт {port}/tcp: {m.error or m.message} — "
                 "если выпуск провалится по таймауту, откройте вручную")
    except Exception as e:  # firewall-модуль упал — выпуск продолжается
        emit(f"[!] firewall, порт {port}/tcp: {e}")

    # кто слушает порт: 'users:(("nginx",pid=123,fd=6))' у LISTEN-строки
    out = _probe(ssh, server,
                 f"ss -tlnp 'sport = :{int(port)}' 2>/dev/null | tail -n +2")
    holder = ""
    pid = ""
    for line in out.splitlines():
        if 'users:(("' in line:
            holder = line.split('users:(("', 1)[1].split('"', 1)[0]
            pid = line.split('pid=', 1)[1].split(',', 1)[0] if "pid=" in line else ""
            break
    if not holder:
        return lease
    try:
        # наш собственный юнит x-ui трогать нельзя при выпуске: перезапуск
        # панели в reloadcmd во время остановленного x-ui — путаница; панель
        # на 80 — редкий случай, честно отказываем
        if holder in ("x-ui", "x-ui.service"):
            raise StepError("cert_port_busy", -1, title=f"Порт {port} занят панелью",
                            detail="панель 3x-ui сама слушает этот порт — смените "
                                   "порт панели и повторите выпуск")
        unit = _probe(ssh, server,
                      f"ps -o unit= -p {pid} 2>/dev/null").strip() if pid else ""
        if not unit or unit == "-":
            raise StepError("cert_port_busy", -1, title=f"Порт {port} занят",
                            detail=f"процесс {holder} не принадлежит systemd-юниту — "
                                   "остановите его вручную и повторите выпуск")
        emit(f"Порт {port} занят ({unit}) — останавливаем на время выпуска…")
        _run(ssh, server, f"systemctl stop {shlex.quote(unit)}",
             step="cert_port_free", title=f"Освобождение порта {port}")
        lease.stopped_unit = unit
        return lease
    except BaseException:
        # дальше не пошли — вернуть firewall как было (порт мы открыли)
        _release_http_port(ssh, server, lease, emit)
        raise


def _release_http_port(ssh, server: dict, lease: _HttpPortLease,
                       emit=lambda line: None) -> None:
    """Откат после выпуска (и при провале — finally): вернуть как было.
    Ошибки отката не роняют результат выпуска — админ видит строки в логе."""
    if not lease or not lease.port:
        return
    if lease.stopped_unit:
        try:
            _run(ssh, server, f"systemctl start {shlex.quote(lease.stopped_unit)}",
                 step="cert_port_restore", title=f"Запуск {lease.stopped_unit}")
            emit(f"{lease.stopped_unit} запущен обратно")
        except StepError as e:
            emit(f"[!] не удалось запустить {lease.stopped_unit} обратно: {e}")
    if lease.firewall_opened:
        try:
            from core.quick_setup.firewall import close_port_on_ssh
            m = close_port_on_ssh(ssh, server, lease.port, "tcp")
            if m.ok and m.verified:
                emit(f"Порт {lease.port}/tcp закрыт в firewall (как было)")
            else:
                emit(f"[!] порт {lease.port}/tcp НЕ закрыт в firewall "
                     f"({m.error or m.message}) — закройте вручную")
        except Exception as e:
            emit(f"[!] firewall, порт {lease.port}/tcp: {e}")


def _with_http_port(ssh, server: dict, port: int,
                    emit=lambda line: None):
    """Контекст-менеджер комбо: подготовить HTTP-порт → yield → откат.

    with _with_http_port(ssh, server, port, emit):
        ... acme-шаги ...
    """
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        # _prepare_http_port сам откатывает своё при ошибке (внешний
        # lease ещё пуст), поэтому здесь — только finally вокруг тела
        lease = _prepare_http_port(ssh, server, port, emit)
        try:
            yield lease
        finally:
            _release_http_port(ssh, server, lease, emit)
    return _cm()



# ------------------------------------------------------------------
# Путь серта панели + URL (их пункт 5)
# ------------------------------------------------------------------

def set_paths(ssh, server: dict, cert_file: str, key_file: str) -> Dict[str, Any]:
    """Назначить панели пути сертификата (их «Set Cert paths», свой путь).
    Рестарт панели — они тоже делают сразу после установки путей."""
    cert_file = validate_cert_path(cert_file)
    key_file = validate_cert_path(key_file)
    if _probe(ssh, server,
              f"test -f {shlex.quote(cert_file)} && test -f {shlex.quote(key_file)} "
              "&& echo yes") != "yes":
        raise StepError("cert_files", -1, title="Файлы сертификата",
                        detail="файл сертификата или ключа не найден на сервере")
    _run(ssh, server,
         f"{templates.XUI_FOLDER}/x-ui setting -webCert {shlex.quote(cert_file)} "
         f"-webCertKey {shlex.quote(key_file)}",
         step="cert_set_paths", title="Пути сертификата панели")
    unit_action(ssh, server, "restart")
    settings = read_settings_show(ssh, server)
    port = (settings.get("port") or "").strip()
    path = (settings.get("web_base_path") or "").strip("/")
    url = f"https://{panel_display_host(server)}:{port}/{path}"
    return {"cert_file": cert_file, "key_file": key_file, "panel_url": url}


# ------------------------------------------------------------------
# 1. Get SSL (Domain)
# ------------------------------------------------------------------

def issue_domain(ssh, server: dict, domain: str, port: int = 80,
                 set_panel: bool = True,
                 emit=lambda line: None) -> Dict[str, Any]:
    """Выпустить LE-сертификат для домена (standalone, порт 80 по умолчанию),
    установить в /root/cert/<домен>/, включить авто-renew и (по умолчанию)
    назначить панели. Их пункт 1."""
    domain = validate_domain(domain)
    try:
        port = int(port or 80)
    except (TypeError, ValueError):
        port = 80
    if not 1 <= port <= 65535:
        raise StepError("cert_port", -1, title="Порт выпуска",
                        detail="порт: целое число 1-65535")

    _ensure_acme(ssh, server)
    _ensure_socat(ssh, server)
    d = shlex.quote(domain)
    cert_dir = f"{CERT_ROOT}/{domain}"

    _run(ssh, server, f"{ACME} --set-default-ca --server letsencrypt --force",
         step="cert_ca", title="acme.sh: CA Let's Encrypt")
    with _with_http_port(ssh, server, port, emit):
        emit(f"Выпуск Let's Encrypt: {domain} (порт {port})…")
        code, out, err = exec_sudo(ssh, server,
            f"{ACME} --issue -d {d} {_listen_flag(ssh, server)} "
            f"--standalone --httpport {port} --force", timeout=300)
        if code != 0:
            _cleanup_acme(ssh, server, [domain])
            raise StepError("cert_issue", code, title=f"Выпуск сертификата {domain}",
                            detail=(err or out or "выпуск не удался").strip()[:500])

    emit("Установка сертификата в /root/cert…")
    # acme.sh copies to the requested paths but does not create the target
    # directory itself. Creating it first also makes an actual copy failure
    # visible instead of masking it behind the later "files not created" check.
    _run(ssh, server, f"install -d -m 700 {shlex.quote(cert_dir)}",
         step="cert_install_dir", title="Подготовка каталога сертификата")
    try:
        _run(ssh, server,
             f"{ACME} --installcert --force -d {d} "
             f"--key-file {cert_dir}/privkey.pem --fullchain-file {cert_dir}/fullchain.pem "
             f"--reloadcmd 'x-ui restart'",
             step="cert_install", title="Установка сертификата")
    except StepError:
        _cleanup_acme(ssh, server, [domain])
        _probe(ssh, server, f"rm -rf {shlex.quote(cert_dir)}")
        raise
    if _probe(ssh, server,
              f"test -s {cert_dir}/fullchain.pem && test -s {cert_dir}/privkey.pem "
              "&& echo yes") != "yes":
        _cleanup_acme(ssh, server, [domain])
        _probe(ssh, server, f"rm -rf {shlex.quote(cert_dir)}")
        raise StepError("cert_install", -1, title="Установка сертификата",
                        detail="acme.sh завершился без ошибок, но файлы сертификата не созданы")

    _run(ssh, server, f"{ACME} --upgrade --auto-upgrade",
         step="cert_autorenew", title="Авто-renew acme.sh", timeout=180)
    _probe(ssh, server,
           f"chmod 600 {cert_dir}/privkey.pem && chmod 644 {cert_dir}/fullchain.pem")

    result: Dict[str, Any] = {"domain": domain}
    if set_panel:
        emit("Назначение сертификата панели…")
        result.update(set_paths(ssh, server,
                                f"{cert_dir}/fullchain.pem",
                                f"{cert_dir}/privkey.pem"))
    emit(f"Готово: {domain}")
    return result


# ------------------------------------------------------------------
# 6. Get SSL for IP (shortlived ~6 дней, auto-renews)
# ------------------------------------------------------------------

def issue_ip(ssh, server: dict, ip: str, ipv6: Optional[str] = None,
             port: int = 80, set_panel: bool = True,
             emit=lambda line: None) -> Dict[str, Any]:
    """Короткоживущий сертификат для IP (их shortlived-профиль, ~6 дней,
    обновляется кроном acme.sh). Живёт в /root/cert/ip/."""
    ip = validate_ipv4(ip)
    ipv6 = validate_ipv6(ipv6) if ipv6 else None
    try:
        port = int(port or 80)
    except (TypeError, ValueError):
        port = 80

    _ensure_acme(ssh, server)
    _ensure_socat(ssh, server)
    cert_dir = f"{CERT_ROOT}/ip"
    args = f"-d {shlex.quote(ip)}" + (f" -d {shlex.quote(ipv6)}" if ipv6 else "")

    with _with_http_port(ssh, server, port, emit):
        emit(f"Выпуск shortlived-сертификата для {ip} (порт {port})…")
        code, out, err = exec_sudo(ssh, server,
            f"{ACME} --issue {args} --standalone --server letsencrypt "
            f"--certificate-profile shortlived --days 6 --httpport {port} --force",
            timeout=300)
        if code != 0:
            _cleanup_acme(ssh, server, [i for i in (ip, ipv6) if i])
            raise StepError("cert_issue_ip", code, title=f"Выпуск сертификата для {ip}",
                            detail=(err or out or "выпуск не удался").strip()[:500])

    emit("Установка сертификата в /root/cert/ip…")
    # acme.sh не создаёт родительский каталог путей --key-file/--fullchain-file.
    # Раньше из-за отсутствующего /root/cert/ip выпуск проходил HTTP-01, но
    # тихо ломался именно на копировании сертификата.
    _run(ssh, server, f"install -d -m 700 {cert_dir}",
         step="cert_install_dir", title="Подготовка каталога сертификата")
    try:
        _run(ssh, server,
             f"{ACME} --installcert --force -d {shlex.quote(ip)} "
             f"--key-file {cert_dir}/privkey.pem --fullchain-file {cert_dir}/fullchain.pem "
             f"--reloadcmd 'x-ui restart'",
             step="cert_install", title="Установка сертификата")
    except StepError:
        _cleanup_acme(ssh, server, [i for i in (ip, ipv6) if i])
        _probe(ssh, server, f"rm -rf {cert_dir}")
        raise
    if _probe(ssh, server,
              f"test -s {cert_dir}/fullchain.pem && test -s {cert_dir}/privkey.pem "
              "&& echo yes") != "yes":
        _cleanup_acme(ssh, server, [i for i in (ip, ipv6) if i])
        _probe(ssh, server, f"rm -rf {cert_dir}")
        raise StepError("cert_install", -1, title="Установка сертификата",
                        detail="acme.sh завершился без ошибок, но файлы сертификата не созданы")

    _run(ssh, server, f"{ACME} --upgrade --auto-upgrade",
         step="cert_autorenew", title="Авто-renew acme.sh", timeout=180)
    _probe(ssh, server,
           f"chmod 600 {cert_dir}/privkey.pem && chmod 644 {cert_dir}/fullchain.pem")

    result: Dict[str, Any] = {"domain": "ip"}
    if set_panel:
        emit("Назначение сертификата панели…")
        result.update(set_paths(ssh, server,
                                f"{cert_dir}/fullchain.pem",
                                f"{cert_dir}/privkey.pem"))
    emit(f"Готово: {ip} (~6 дней, обновляется автоматически)")
    return result

def _panel_cert_paths(ssh, server: dict) -> Dict[str, str]:
    raw = _probe(ssh, server,
                 f"{templates.XUI_FOLDER}/x-ui setting -getCert true 2>/dev/null")
    values = {"cert": "", "key": ""}
    for line in raw.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in values:
            values[key.strip()] = value.strip()
    return values


def _clear_panel_cert_paths(ssh, server: dict) -> None:
    before = read_settings_show(ssh, server)
    # 3.8.5: `setting -webCert '' -webCertKey ''` молча игнорирует пустые
    # значения, а голая `x-ui cert` перезаписывает пути панели пустыми.
    # Проверки ниже страхуют, если сборка поведёт себя иначе.
    _run(ssh, server,
         f"{templates.XUI_FOLDER}/x-ui cert",
         step="cert_reset_panel", title="Сброс путей сертификата панели")
    paths = _panel_cert_paths(ssh, server)
    after = read_settings_show(ssh, server)
    if paths["cert"] or paths["key"]:
        raise StepError("cert_reset_panel", -1, title="Сброс путей сертификата панели",
                        detail="3x-ui не очистил пути сертификата")
    if any(after[key] != before[key] for key in ("port", "web_base_path")):
        raise StepError("cert_reset_panel", -1, title="Сброс путей сертификата панели",
                        detail="3x-ui изменил настройки панели вместо очистки сертификата")
    unit_action(ssh, server, "restart")


def _certbot_lineage_exists(ssh, server: dict, domain: str) -> bool:
    live = f"/etc/letsencrypt/live/{domain}"
    renewal = f"/etc/letsencrypt/renewal/{domain}.conf"
    return _probe(ssh, server,
                  f"test -f {shlex.quote(renewal)} -o -d {shlex.quote(live)} && echo yes") == "yes"


# ------------------------------------------------------------------
# 3. Force Renew
# ------------------------------------------------------------------

def renew(ssh, server: dict, domain: str, port: int = 80,
          emit=lambda line: None) -> Dict[str, Any]:
    """Принудительное обновление (их пункт 3). Зарегистрированный
    installcert-хук сам скопирует файлы и перезапустит панель.
    Порт standalone — 80 по умолчанию (в CLI его не спросят)."""
    domain = validate_certificate_identifier(domain)
    if domain not in read_state(ssh, server)["domains"]:
        raise StepError("cert_renew", -1, title="Продление сертификата",
                        detail=f"домена {domain} нет в /root/cert")
    try:
        port = int(port or 80)
    except (TypeError, ValueError):
        port = 80
    with _with_http_port(ssh, server, port, emit):
        emit(f"Продление {domain}…")
        _run(ssh, server, f"{ACME} --renew -d {shlex.quote(domain)} --force",
             step="cert_renew", title=f"Продление {domain}", timeout=300)
    emit(f"Готово: {domain}")
    return {"domain": domain}


# ------------------------------------------------------------------
# certbot: выпуск/продление/удаление (альтернативный движок, параллельный
# их CLI-механике на acme.sh; выбор движка — в модалке карточки)
# ------------------------------------------------------------------

def _ensure_certbot(ssh, server: dict) -> None:
    if _probe(ssh, server, "command -v certbot >/dev/null && echo yes") == "yes":
        return
    rid = _probe(ssh, server, ". /etc/os-release 2>/dev/null; echo $ID")
    pkgs = {
        "debian": "apt-get update -qq && apt-get install -y -qq certbot",
        "ubuntu": "apt-get update -qq && apt-get install -y -qq certbot",
        "armbian": "apt-get update -qq && apt-get install -y -qq certbot",
        "fedora": "dnf makecache -y -q && dnf -y -q install certbot",
        "amzn": "dnf makecache -y -q && dnf -y -q install certbot",
        "virtuozzo": "dnf makecache -y -q && dnf -y -q install certbot",
        "rhel": "dnf makecache -y -q && dnf -y -q install certbot",
        "almalinux": "dnf makecache -y -q && dnf -y -q install certbot",
        "rocky": "dnf makecache -y -q && dnf -y -q install certbot",
        "ol": "dnf makecache -y -q && dnf -y -q install certbot",
        "centos": "yum makecache -q -y && yum -y -q install certbot",
        "arch": "pacman -Sy --noconfirm certbot",
        "manjaro": "pacman -Sy --noconfirm certbot",
        "parch": "pacman -Sy --noconfirm certbot",
        "opensuse-tumbleweed": "zypper -q refresh && zypper -q install -y certbot",
        "opensuse-leap": "zypper -q refresh && zypper -q install -y certbot",
        "alpine": "apk add certbot",
    }
    cmd = pkgs.get(rid)
    if not cmd:
        raise StepError("certbot_install", -1, title="Установка certbot",
                        detail=f"дистрибутив не поддерживается: {rid or 'неизвестен'} — "
                               "установите certbot вручную")
    _run(ssh, server, cmd, step="certbot_install", title="Установка certbot",
         timeout=600)


def issue_domain_certbot(ssh, server: dict, domain: str, port: int = 80,
                         set_panel: bool = True,
                         emit=lambda line: None) -> Dict[str, Any]:
    """Выпустить LE-сертификат certbot'ом (standalone, как renew-конфиг
    этой панели). Серт — /etc/letsencrypt/live/<домен>/, авто-renew —
    certbot.timer (ставится пакетом). Комбо-порт-80 — общее."""
    domain = validate_domain(domain)
    try:
        port = int(port or 80)
    except (TypeError, ValueError):
        port = 80
    if not 1 <= port <= 65535:
        raise StepError("cert_port", -1, title="Порт выпуска",
                        detail="порт: целое число 1-65535")

    _ensure_certbot(ssh, server)
    email = "admin@" + ".".join(domain.split(".")[-2:])  # для аккаунта LE
    with _with_http_port(ssh, server, port, emit):
        emit(f"Выпуск Let's Encrypt (certbot): {domain} (порт {port})…")
        # --keep-until-expiring: повторный выпуск того же домена не создаёт
        # дубль в archive, а продолжает серию; -n: неинтерактивно
        _run(ssh, server,
             f"certbot certonly --standalone -n --agree-tos "
             f"-m {shlex.quote(email)} -d {shlex.quote(domain)} "
             f"--http-01-port {int(port)} --keep-until-expiring",
             step="certbot_issue", title=f"Выпуск сертификата {domain}",
             timeout=300)

    live = f"/etc/letsencrypt/live/{domain}"
    if _probe(ssh, server,
              f"test -s {shlex.quote(live)}/fullchain.pem && echo yes") != "yes":
        raise StepError("cert_install", -1, title="Установка сертификата",
                        detail="файлы сертификата не созданы")
    result: Dict[str, Any] = {"domain": domain}
    if set_panel:
        emit("Назначение сертификата панели…")
        result.update(set_paths(ssh, server,
                                f"{live}/fullchain.pem", f"{live}/privkey.pem"))
    emit(f"Готово: {domain} (certbot, авто-renew через certbot.timer)")
    return result


def renew_certbot(ssh, server: dict, domain: str,
                  emit=lambda line: None) -> Dict[str, Any]:
    """Принудительное продление certbot'ом: certbot renew --force-renewal
    по конкретному серту. deploy-hook (если задан) выполнится сам."""
    domain = validate_domain(domain)
    if domain not in read_state(ssh, server)["certbot_domains"]:
        raise StepError("cert_renew", -1, title="Продление сертификата",
                        detail=f"домена {domain} нет в /etc/letsencrypt")
    with _with_http_port(ssh, server, 80, emit):
        emit(f"Продление {domain} (certbot)…")
        _run(ssh, server,
             f"certbot renew -n --force-renewal "
             f"--cert-name {shlex.quote(domain)}",
             step="certbot_renew", title=f"Продление {domain}", timeout=300)
    emit(f"Готово: {domain}")
    return {"domain": domain}


def remove_cert_certbot(ssh, server: dict, domain: str,
                        emit=lambda line: None) -> Dict[str, Any]:
    """Удалить Certbot-сертификат, включая случай, когда revoke уже снёс lineage."""
    domain = validate_domain(domain)
    known = domain in read_state(ssh, server)["certbot_domains"]
    live = f"/etc/letsencrypt/live/{domain}/"
    paths = _panel_cert_paths(ssh, server)
    reset_panel = paths["cert"].startswith(live) or paths["key"].startswith(live)
    if known:
        emit(f"Отзыв {domain} (certbot)…")
        _probe(ssh, server,
               f"certbot revoke -n --cert-name {shlex.quote(domain)} "
               f">/dev/null 2>&1")
        if _certbot_lineage_exists(ssh, server, domain):
            code, out, err = exec_sudo(
                ssh, server, f"certbot delete -n --cert-name {shlex.quote(domain)}", timeout=300)
            if code != 0 and _certbot_lineage_exists(ssh, server, domain):
                raise StepError("certbot_delete", code, title=f"Удаление {domain}",
                                detail=(err or out or "certbot не удалил сертификат").strip()[:500])
    else:
        emit(f"Сертификат {domain} уже отсутствует в certbot")
    if reset_panel:
        emit("Сброс путей сертификата панели…")
        _clear_panel_cert_paths(ssh, server)
    emit(f"Готово: {domain} удалён (certbot)")
    return {"domain": domain, "panel_reset": reset_panel}


# ------------------------------------------------------------------
# 2. Revoke & Remove
# ------------------------------------------------------------------

def remove_cert(ssh, server: dict, domain: str,
                emit=lambda line: None) -> Dict[str, Any]:
    """Отозвать и удалить acme.sh-сертификат, не сбрасывая настройки панели целиком."""
    domain = validate_certificate_identifier(domain)
    known = domain in read_state(ssh, server)["domains"]

    cert_dir = f"{CERT_ROOT}/{domain}/"
    paths = _panel_cert_paths(ssh, server)
    reset_panel = paths["cert"].startswith(cert_dir) or paths["key"].startswith(cert_dir)
    if known:
        emit(f"Отзыв {domain}…")
        # IP-серт лежит в /root/cert/ip, но acme.sh трекает реальные адреса
        idents = [domain]
        if domain == "ip":
            listing = _probe(ssh, server, f"{ACME} --list 2>/dev/null")
            idents = [line.split()[0] for line in listing.splitlines()[1:]
                      if line.split() and (":" in line.split()[0] or
                                           line.split()[0].count(".") == 3)]
        for ident in idents:
            _probe(ssh, server,
                   f"{ACME} --revoke -d {shlex.quote(ident)} >/dev/null 2>&1; "
                   f"{ACME} --remove -d {shlex.quote(ident)} >/dev/null 2>&1; "
                   f"rm -rf /root/.acme.sh/{shlex.quote(ident)} "
                   f"/root/.acme.sh/{shlex.quote(ident)}_ecc")
        _probe(ssh, server, f"rm -rf {CERT_ROOT}/{shlex.quote(domain)}")
    else:
        emit(f"Сертификат {domain} уже отсутствует в acme.sh")

    if reset_panel:
        emit("Сброс путей сертификата панели…")
        _clear_panel_cert_paths(ssh, server)
    emit(f"Готово: {domain} удалён")
    return {"domain": domain, "panel_reset": reset_panel}
