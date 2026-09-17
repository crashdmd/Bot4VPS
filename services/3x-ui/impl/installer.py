# -*- coding: utf-8 -*-
"""Тонкий установщик 3x-ui на целевой сервер (единый код-путь, два источника).

Философия: раскладка байт-в-байт как у официального install.sh —
bot-installed и official-installed 3x-ui неотличимы. Офф-скрипт при этом
остаётся ручным альтернативным путём (наш код его не вызывает).

Источник артефакта — параметр:
    source="github"  — сервер сам качает тарболл+.sha256 с GitHub;
    source="push"    — бот перегоняет тарболл из локального кэша по SFTP.

Шаги идентичны офф-скрипту (install.sh MHSanaei/3x-ui):
    1. deps: cron curl tar tzdata socat ca-certificates openssl
    2. артефакт (по source) + sha256-сверка
    3. бэкап кастомного bin/ → распаковка /usr/local/x-ui → рестор кастомного
    4. /usr/bin/x-ui (x-ui.sh из тарболла), /var/log/x-ui
    5. systemd unit (из тарболла; fallback — шаблон), daemon-reload, enable
    6. x-ui setting (username/password/port/webBasePath) + migrate
    6b. SSL: LE домен / LE IP (shortlived) / свои пути / skip (bind 127.0.0.1)
    7. fail2ban: 3x-ipl jail (к нашему базовому fail2ban)
    8. старт сервиса, запись install-result.env (как write_install_result
       офф-скрипта: root 600, XUI_* ключи, %q-экранирование)

Self-healing fallback: source=github упал по таймауту/сети → автоматически
push из кэша (если версия там есть) — тот же runner, тот же результат.
"""
from __future__ import annotations

import posixpath
import shlex
from typing import Any, Dict, Optional

from core.integrator import StepError, StepRunner
from core.ssh import create_ssh_client

from . import templates
from .releases import ReleaseError, parse_tag, tarball_url, sha256_url

_DEPS = "cron curl tar tzdata socat ca-certificates openssl"

# Ожидаемая структура тарболла релиза (как в install.sh): каталог x-ui/
# с бинарником x-ui, x-ui.sh и bin/ (xray, mtg, geo-даты).
_EXTRACT_MARKER = "x-ui/x-ui"


def _quote(value: str) -> str:
    return shlex.quote(value)


# ------------------------------------------------------------------
# Шаг 1: зависимости
# ------------------------------------------------------------------

def ensure_deps(runner: StepRunner) -> None:
    runner.run(
        "ensure_deps",
        "DEBIAN_FRONTEND=noninteractive apt-get update -qq && "
        f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {_DEPS}",
        title="Установка зависимостей (cron curl tar socat openssl…)",
    )


# ------------------------------------------------------------------
# Шаг 2: артефакт
# ------------------------------------------------------------------

def fetch_from_github(runner: StepRunner, tag: str, arch: str) -> None:
    """Скачивание тарболла и .sha256 НА сервере с GitHub + сверка.

    Timeout жёстче общего (медленный канал не должен подвешивать установку
    навсегда — caller использует это для self-healing fallback на кэш).
    """
    tar_url = tarball_url(tag, arch)
    sha_url = sha256_url(tag, arch)
    tmp_tar = "/tmp/x-ui-release.tar.gz"
    tmp_sha = "/tmp/x-ui-release.tar.gz.sha256"
    runner.run(
        "fetch_tarball",
        f"curl -fLR --connect-timeout 15 --max-time 900 "
        f"--speed-limit 1024 --speed-time 120 -o {_quote(tmp_tar)} {_quote(tar_url)}",
        title=f"Загрузка тарболла {tag} ({arch}) с GitHub",
    )
    runner.run(
        "fetch_checksum",
        f"curl -fLR --connect-timeout 15 --max-time 60 -o {_quote(tmp_sha)} {_quote(sha_url)}",
        title="Загрузка чексуммы релиза",
    )
    _verify_sha256(runner, tmp_tar, tmp_sha)


def push_from_cache(runner: StepRunner, local_tarball: str, tag: str, arch: str) -> None:
    """Перегон тарболла из локального кэша бота на сервер (SFTP + verify).

    local_tarball — путь на МАШИНЕ БОТА (release_cache.tarball_path).
    Чексумму берём из кэша (release_cache уже верифицировал её при скачивании).
    """
    import os
    if not os.path.isfile(local_tarball):
        raise ReleaseError(f"Тарболл не найден в кэше: {local_tarball}")

    tmp_tar = "/tmp/x-ui-release.tar.gz"
    tmp_sha = "/tmp/x-ui-release.tar.gz.sha256"

    sftp = runner.ssh.open_sftp()
    try:
        sftp.put(local_tarball, tmp_tar)
        sha_local = str(local_tarball) + ".sha256"
        sftp.put(sha_local, tmp_sha)
    finally:
        sftp.close()

    runner.emit(f"• Тарболл {tag} ({arch}) передан из кэша бота")
    _verify_sha256(runner, tmp_tar, tmp_sha)


def _verify_sha256(runner: StepRunner, tmp_tar: str, tmp_sha: str) -> None:
    """Сверка sha256 на сервере (sha256sum -c с sidecar-файлом)."""
    runner.run(
        "verify_checksum",
        f"expected=$(awk 'NR==1 {{print $1}}' {_quote(tmp_sha)}) && "
        f"actual=$(sha256sum {_quote(tmp_tar)} | awk '{{print $1}}') && "
        f"[ \"$expected\" = \"$actual\" ] || {{ echo \"sha256 mismatch: $expected != $actual\" >&2; exit 1; }}",
        title="Проверка sha256 тарболла",
    )


# ------------------------------------------------------------------
# Шаг 3: распаковка (с сохранением кастомного bin/)
# ------------------------------------------------------------------

def extract_release(runner: StepRunner) -> None:
    """Распаковка в /usr/local/x-ui по образцу офф-скрипта.

    Кастомные файлы bin/ (свои geoip/geosite, добавленные админом) не
    теряются: bin/ переименовывается в бэкап до распаковки, после —
    недостающие файлы возвращаются (релизные не перезаписываются).
    Рантайм-остатки (config.json, mtproto/, tuic/) не возвращаются.
    """
    # бэкап существующего каталога (если стоит старая версия).
    # .old.$$ и .old.* НЕ в кавычках: $$ и glob должны раскрыться шеллом
    # (пути — константы без пробелов, шлёк-экранирование тут только мешает).
    runner.run(
        "backup_old_install",
        "if [ -d " + _quote(templates.XUI_FOLDER) + " ]; then "
        "mv " + _quote(templates.XUI_FOLDER) + " " + templates.XUI_FOLDER + ".old.$$; fi",
        title="Сохранение предыдущей установки (если была)",
    )
    runner.run(
        "extract_tarball",
        "cd /usr/local && "
        "tar xzf /tmp/x-ui-release.tar.gz && "
        f"test -d {_quote(templates.XUI_FOLDER)} && "
        f"test -x {_quote(templates.XUI_FOLDER + '/x-ui')} && "
        "rm -f /tmp/x-ui-release.tar.gz /tmp/x-ui-release.tar.gz.sha256",
        title="Распаковка релиза в /usr/local/x-ui",
    )
    # рестор кастомных файлов bin/ из старой установки (glob не в кавычках)
    runner.run(
        "restore_custom_bin",
        "old=$(ls -d " + templates.XUI_FOLDER + ".old.* 2>/dev/null | head -n1); "
        "if [ -n \"$old\" ] && [ -d \"$old/bin\" ]; then "
        "  (cd \"$old/bin\" && find . -type f) | while read -r f; do "
        "    case \"$f\" in ./config.json|./mtproto|./mtproto/*|./tuic|./tuic/*) continue;; esac; "
        f"    if [ ! -e {_quote(templates.XUI_FOLDER)}/bin/\"$f\" ]; then "
        f"      cp -a \"$old/bin/$f\" {_quote(templates.XUI_FOLDER)}/bin/\"$f\"; fi; "
        "  done; "
        "fi; "
        "rm -rf " + templates.XUI_FOLDER + ".old.* 2>/dev/null; exit 0",
        title="Восстановление кастомных файлов bin/",
    )


# ------------------------------------------------------------------
# Шаг 4: CLI + логи
# ------------------------------------------------------------------

def install_cli_and_unit(runner: StepRunner) -> None:
    """/usr/bin/x-ui (x-ui.sh из тарболла), /var/log/x-ui, systemd unit.

    Unit берём из тарболла (x-ui.service.debian — как офф-скрипт для
    Debian/Ubuntu); если тарболл юнита не содержит — fallback-шаблон
    через SFTP (templates.XUI_UNIT_FALLBACK).
    """
    runner.run(
        "install_cli",
        f"cp -f {templates.XUI_FOLDER}/x-ui.sh {templates.XUI_BIN} && "
        f"chmod +x {templates.XUI_BIN} && "
        f"mkdir -p {templates.XUI_LOG_DIR}",
        title="Установка CLI x-ui (/usr/bin/x-ui)",
    )
    # unit: сначала пробуем из тарболла, потом distro-специфичный, потом шаблон
    runner.run(
        "install_unit",
        f"unit_src=''; "
        f"for f in x-ui.service x-ui.service.debian; do "
        f"  if [ -s {templates.XUI_FOLDER}/$f ]; then unit_src={templates.XUI_FOLDER}/$f; break; fi; "
        f"done; "
        f"if [ -n \"$unit_src\" ]; then "
        f"  install -m 644 \"$unit_src\" {templates.XUI_UNIT}; "
        f"else echo NO_UNIT_IN_TARBALL; fi",
        title="Установка systemd unit x-ui.service",
    )
    if runner.probe(f"test -s {templates.XUI_UNIT} && echo ok || echo missing") == "missing":
        _write_unit_fallback(runner)
    runner.run(
        "enable_unit",
        "systemctl daemon-reload && systemctl enable x-ui",
        title="daemon-reload + автозагрузка x-ui",
    )


def _write_unit_fallback(runner: StepRunner) -> None:
    """Fallback: unit-файл из шаблона (тарболл его не содержал)."""
    tmp_path = "/tmp/bot4vps_xui_unit"
    sftp = runner.ssh.open_sftp()
    try:
        with sftp.file(tmp_path, "w") as f:
            f.write(templates.XUI_UNIT_FALLBACK)
    finally:
        sftp.close()
    runner.run(
        "install_unit_fallback",
        f"install -m 644 {tmp_path} {templates.XUI_UNIT} && rm -f {tmp_path} && "
        f"test -s {templates.XUI_UNIT}",
        title="Установка systemd unit (шаблон)",
    )


# ------------------------------------------------------------------
# Шаг 6: конфигурация панели
# ------------------------------------------------------------------

def configure_panel(
    runner: StepRunner,
    username: str,
    password: str,
    port: int,
    web_base_path: str,
) -> None:
    """Креды/порт/path через CLI их бинарника + migrate.

    Значения подставляются в shlex-quoted аргументы — интерполяции ввода
    в команду нет. Рестарт НЕ здесь ( его делает start_service), чтобы
    конфигурация и старт оставались разными шагами.
    """
    runner.run(
        "configure_settings",
        f"{templates.XUI_FOLDER}/x-ui setting "
        f"-username {_quote(username)} -password {_quote(password)} "
        f"-port {int(port)} -webBasePath {_quote(web_base_path)}",
        title="Настройка логина/пароля/порта/web base path",
    )
    runner.run(
        "migrate_db",
        f"{templates.XUI_FOLDER}/x-ui migrate",
        title="Миграция базы данных",
    )


# ------------------------------------------------------------------
# Шаг 6b: SSL (Let's Encrypt / свои сертификаты / skip)
# ------------------------------------------------------------------

def _ensure_acme(runner: StepRunner) -> None:
    """acme.sh для LE-сертификатов (как install_acme офф-скрипта)."""
    runner.run(
        "ensure_acme",
        "if ! command -v ~/.acme.sh/acme.sh >/dev/null 2>&1; then "
        "curl -s https://get.acme.sh | sh; "
        "command -v ~/.acme.sh/acme.sh >/dev/null 2>&1; "
        "fi",
        title="Проверка/установка acme.sh",
    )


def _acme_listen_flag(runner: StepRunner) -> str:
    """IPv4-адрес есть → обычный standalone; иначе --listen-v6 (их логика)."""
    flag = runner.probe(
        "ip -4 addr show scope global 2>/dev/null | grep -q 'inet ' && echo '' || echo --listen-v6"
    ).strip()
    return flag


def configure_ssl_domain(runner: StepRunner, domain: str) -> bool:
    """LE-сертификат для домена (90 дней, autorrenew) — как их вариант 1.

    Порт 80 должен быть свободен и открыт: standalone-режим acme.sh.
    Возвращает True при успехе; False — выпуск не удался (панель остаётся
    на HTTP, честное предупреждение в выводе — установка НЕ падает, так
    же ведёт себя офф-скрипт).
    """
    _ensure_acme(runner)
    cert_dir = f"/root/cert/{domain}"
    listen = _acme_listen_flag(runner)
    try:
        runner.run(
            "ssl_issue_domain",
            f"~/.acme.sh/acme.sh --set-default-ca --server letsencrypt --force >/dev/null 2>&1; "
            f"~/.acme.sh/acme.sh --issue -d {_quote(domain)} {listen} --standalone --httpport 80 --force",
            title=f"Выпуск сертификата Let's Encrypt для {domain}",
        )
    except StepError:
        # выпуск не удался (порт 80 занят/закрыт, rate limit…) — панель
        # остаётся на HTTP; установка НЕ падает (так же ведёт офф-скрипт)
        return False
    runner.run(
        "ssl_install_domain",
        f"~/.acme.sh/acme.sh --installcert --force -d {_quote(domain)} "
        f"--key-file {_quote(cert_dir + '/privkey.pem')} "
        f"--fullchain-file {_quote(cert_dir + '/fullchain.pem')} "
        f"--reloadcmd 'systemctl restart x-ui 2>/dev/null || true' && "
        f"chmod 600 {_quote(cert_dir + '/privkey.pem')} && "
        f"chmod 644 {_quote(cert_dir + '/fullchain.pem')} && "
        f"~/.acme.sh/acme.sh --upgrade --auto-upgrade >/dev/null 2>&1; "
        f"test -s {_quote(cert_dir + '/fullchain.pem')}",
        title="Установка сертификата (автопродление)",
    )
    runner.run(
        "ssl_apply_domain",
        f"{templates.XUI_FOLDER}/x-ui setting -webCert {_quote(cert_dir + '/fullchain.pem')} "
        f"-webCertKey {_quote(cert_dir + '/privkey.pem')}",
        title="Подключение сертификата к панели",
    )
    return True


def configure_ssl_ip(runner: StepRunner, server_ip: str, ipv6: str = "") -> bool:
    """Короткоживущий LE-сертификат для IP (~6 дней, autorrenew) — их вариант 2.

    Перед выпуском панель останавливается: acme.sh нужен порт 80.
    """
    _ensure_acme(runner)
    cert_dir = "/root/cert/ip"
    domain_args = f"-d {_quote(server_ip)}"
    if ipv6:
        domain_args += f" -d {_quote(ipv6)}"

    # порт 80 нужен acme: остановить панель, если она уже слушает его
    runner.run(
        "ssl_stop_panel_for_acme",
        f"ss -ltn '( sport = :80 )' 2>/dev/null | grep -q LISTEN && systemctl stop x-ui || true",
        title="Освобождение порта 80 для ACME",
    )
    try:
        runner.run(
            "ssl_issue_ip",
            f"~/.acme.sh/acme.sh --set-default-ca --server letsencrypt --force >/dev/null 2>&1; "
            f"~/.acme.sh/acme.sh --issue {domain_args} --standalone --server letsencrypt "
            f"--certificate-profile shortlived --days 6 --httpport 80 --force",
            title=f"Выпуск IP-сертификата для {server_ip}",
        )
    except StepError:
        return False
    runner.run(
        "ssl_install_ip",
        f"~/.acme.sh/acme.sh --installcert --force -d {_quote(server_ip)} "
        f"--key-file {cert_dir}/privkey.pem --fullchain-file {cert_dir}/fullchain.pem "
        f"--reloadcmd 'systemctl restart x-ui 2>/dev/null || true' 2>&1 || true; "
        f"test -s {cert_dir}/fullchain.pem && test -s {cert_dir}/privkey.pem && "
        f"chmod 600 {cert_dir}/privkey.pem && chmod 644 {cert_dir}/fullchain.pem && "
        f"~/.acme.sh/acme.sh --upgrade --auto-upgrade >/dev/null 2>&1; "
        f"test -s {cert_dir}/fullchain.pem",
        title="Установка IP-сертификата (автопродление ~6 дней)",
    )
    runner.run(
        "ssl_apply_ip",
        f"{templates.XUI_FOLDER}/x-ui setting -webCert {cert_dir}/fullchain.pem "
        f"-webCertKey {cert_dir}/privkey.pem",
        title="Подключение IP-сертификата к панели",
    )
    return True


def configure_ssl_custom(
    runner: StepRunner, cert_file: str, key_file: str,
) -> None:
    """Свои пути к сертификатам — их вариант 3 (проверка файлов на сервере)."""
    runner.run(
        "ssl_apply_custom",
        f"test -s {_quote(cert_file)} && test -s {_quote(key_file)} && "
        f"{templates.XUI_FOLDER}/x-ui setting -webCert {_quote(cert_file)} "
        f"-webCertKey {_quote(key_file)}",
        title="Подключение своего сертификата",
    )
    runner.emit("• Продление этих файлов — ваша ответственность (внешне)")


def configure_ssl_none(runner: StepRunner, bind_local: bool) -> None:
    """Без SSL — их вариант 4 (reverse proxy / SSH-туннель).

    bind_local=True → панель слушает только 127.0.0.1 (недоступна из
    интернета; доступ через туннель/прокси — URL покажет 127.0.0.1).
    """
    if bind_local:
        runner.run(
            "ssl_bind_local",
            f"{templates.XUI_FOLDER}/x-ui setting -listenIP 127.0.0.1",
            title="Бинд панели на 127.0.0.1 (доступ по SSH-туннелю)",
        )
    else:
        runner.emit("• Панель на HTTP: гарантируйте TLS перед ней (прокси/туннель)")


def configure_ssl(runner: StepRunner, params: Dict[str, Any]) -> Optional[bool]:
    """Диспетчер SSL по ssl_mode. None → режим не задан (без SSL, без слов).

    Возвращает True/False (успех выпуска LE) или None (custom/none).
    """
    mode = str(params.get("ssl_mode") or "none")
    if mode == "domain":
        return configure_ssl_domain(runner, str(params["domain"]))
    if mode == "ip":
        return configure_ssl_ip(
            runner, str(params["server_ip"]), str(params.get("ipv6") or ""),
        )
    if mode == "custom":
        configure_ssl_custom(
            runner, str(params["cert_file"]), str(params["key_file"]),
        )
        return None
    if mode == "none":
        configure_ssl_none(runner, bool(params.get("bind_local")))
        return None
    runner.emit(f"• Неизвестный ssl_mode {mode!r} — SSL пропущен")
    return None


# ------------------------------------------------------------------
# Шаг 6c: firewall — открыть порт панели (и 80 для выпуска LE)
# ------------------------------------------------------------------

def open_panel_firewall_ports(
    runner: StepRunner, port: int, *, need_http: bool
) -> Dict[str, Any]:
    """Открыть порт панели (tcp) во всех активных firewall сервера.

    Ядерный quick_setup.firewall.open_port_on_ssh: детект активных backend'ов
    (ufw/firewalld/nftables), мутация + верификация. Firewall нет / не
    определился — не ошибка установки (панель сама доступна; правило
    админ добавит руками) — честная строка в лог.

    need_http: LE-режимы (domain/ip) — acme.sh standalone слушает входящий
    80; без него выпуск сертификата провалится. 80 открываем только тогда.
    """
    from core.quick_setup.firewall import open_port_on_ssh

    ports: list[int] = [int(port)]
    if need_http:
        ports.append(80)
    summary: Dict[str, Any] = {"ports": ports, "opened": [], "skipped": []}
    for p in ports:
        try:
            mutation = open_port_on_ssh(runner.ssh, runner.server, p, "tcp")
        except Exception as e:  # firewall-модуль упал — не роняем установку
            runner.emit(f"   [!] firewall, порт {p}: {e}")
            summary["skipped"].append(p)
            continue
        if mutation.ok and mutation.verified:
            runner.emit(
                f"   [!] порт {p}/tcp открыт в firewall — панель доступна извне"
                if p != 80 else
                f"   [!] порт {p}/tcp открыт в firewall (нужен для выпуска сертификата)"
            )
            summary["opened"].append(p)
        else:
            # не критично для продолжения, но админ должен видеть
            runner.emit(
                f"   [!] НЕ удалось открыть порт {p}/tcp в firewall: "
                f"{mutation.error or mutation.message} — правило придётся добавить вручную"
            )
            summary["skipped"].append(p)
    return summary

def install_iplimit_jail(runner: StepRunner, panel_port: int) -> None:
    """3x-ipl jail к нашему базовому fail2ban (их setup-fail2ban смысл).

    fail2ban уже может стоять (наш QS его ставит) — тогда только jail;
    если нет — ставим пакет (как офф-скрипт). Файлы пишем через
    SFTP+atomic move (паттерн WG templates), потом fail2ban-client -t
    валидирует и reload поднимает jail.
    """
    runner.run(
        "ensure_fail2ban",
        "if ! command -v fail2ban-client >/dev/null 2>&1; then "
        "DEBIAN_FRONTEND=noninteractive apt-get update -qq && "
        "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq fail2ban; "
        "fi",
        title="Проверка/установка fail2ban",
    )

    # exempt-порты: SSH (все Port из sshd_config) + порт панели
    exempt_ports = runner.probe(
        "ports=$(grep -oE '^[[:space:]]*Port[[:space:]]+[0-9]+' /etc/ssh/sshd_config 2>/dev/null | "
        "awk '{print $NF}' | paste -sd, -); "
        f'[ -z "$ports" ] && ports=22; echo "$ports,{int(panel_port)}"'
    ).strip() or f"22,{panel_port}"

    # touch логов (fail2ban падает на отсутствующем logpath)
    runner.run(
        "touch_iplimit_logs",
        f"mkdir -p {templates.XUI_LOG_DIR} && "
        f"touch {templates.IPLIMIT_LOG} {templates.IPLIMIT_BANNED_LOG}",
        title="Создание лог-файлов IP Limit",
    )

    _sftp_write_configs(runner, {
        templates.IPLIMIT_JAIL: templates.iplimit_jail_conf(),
        templates.IPLIMIT_FILTER: templates.iplimit_filter_conf(),
        templates.IPLIMIT_ACTION: templates.iplimit_action_conf(exempt_ports),
    }, step_prefix="iplimit")

    # backend=systemd только на Debian 12+/Ubuntu 22.04+ (как офф-скрипт)
    backend_needed = runner.probe(
        "if grep -Eqi 'debian' /etc/os-release && [ \"$(. /etc/os-release; echo ${VERSION_ID%%.*})\" -ge 12 ]; then echo yes; "
        "elif grep -Eqi 'ubuntu' /etc/os-release && [ \"$(. /etc/os-release; echo ${VERSION_ID%%.*})\" -ge 22 ]; then echo yes; "
        "else echo no; fi"
    ).strip()
    if backend_needed == "yes":
        _sftp_write_configs(runner, {
            templates.IPLIMIT_BACKEND: templates.iplimit_backend_conf(),
        }, step_prefix="iplimit_backend")

    # разрешить ipv6 (раскомментарить allowipv6) — как create_iplimit_jails
    runner.run(
        "enable_ipv6_f2b",
        "sed -i 's/#allowipv6 = auto/allowipv6 = auto/g' /etc/fail2ban/fail2ban.conf 2>/dev/null; exit 0",
        title="fail2ban: allowipv6 (если закомментирован)",
    )

    runner.run(
        "reload_fail2ban",
        "fail2ban-client -t && "
        "(systemctl is-active --quiet fail2ban && systemctl restart fail2ban || systemctl enable --now fail2ban)",
        title="Валидация и перезапуск fail2ban",
    )


def _sftp_write_configs(runner: StepRunner, files: Dict[str, str], *, step_prefix: str) -> None:
    """Запись конфигов через SFTP → /tmp → atomic move (паттерн WG)."""
    moves = []
    sftp = runner.ssh.open_sftp()
    try:
        for i, (dest, content) in enumerate(files.items()):
            tmp_path = f"/tmp/bot4vps_{step_prefix}_{i}"
            with sftp.file(tmp_path, "w") as f:
                f.write(content)
            dest_dir = posixpath.dirname(dest)
            moves.append(
                f"install -d -m 755 {dest_dir} && "
                f"mv {tmp_path} {dest} && chmod 644 {dest}"
            )
    finally:
        sftp.close()
    for cmd in moves:
        runner.run(f"write_{step_prefix}_config", cmd,
                   title=f"Запись конфигурации fail2ban ({step_prefix})")


# ------------------------------------------------------------------
# Шаг 8: старт + результат
# ------------------------------------------------------------------

def start_service(runner: StepRunner) -> None:
    runner.run(
        "start_service",
        "systemctl restart x-ui",
        title="Запуск x-ui.service",
    )


def write_install_result(
    runner: StepRunner,
    username: str,
    password: str,
    port: int,
    web_base_path: str,
    scheme: str,
    host: str,
    db_type: str = "sqlite",
) -> Dict[str, str]:
    """Написать /etc/x-ui/install-result.env (root 600) — паритет с офф-скриптом.

    Значения через printf %q (shell-escaped, файл безопасно source-ится);
    офф-скрипт и наш бот-installed оставляют одинаковый формат. Плюс
    API-токен их бинарника — читается после старта (-getApiToken).
    """
    def q(v: str) -> str:
        # %q-экранирование: всё небуквенно-цифровое — в безопасной форме
        return "'" + str(v).replace("'", "'\\''") + "'"

    api_token = runner.probe(
        f"{templates.XUI_FOLDER}/x-ui setting -getApiToken 2>/dev/null | "
        "grep -Eo 'apiToken: .+' | awk '{print $2}'"
    ).strip()
    # awk не отрезал поле (формат «apiToken: токен» без пробела и т.п.) —
    # подстрахуемся явным split
    if api_token.startswith("apiToken:"):
        api_token = api_token.split(":", 1)[1].strip()
    result = {
        "XUI_USERNAME": str(username),
        "XUI_PASSWORD": str(password),
        "XUI_PANEL_PORT": str(port),
        "XUI_WEB_BASE_PATH": str(web_base_path),
        "XUI_ACCESS_URL": f"{scheme}://{host}:{port}/{web_base_path}",
        "XUI_API_TOKEN": api_token or "",
        "XUI_DB_TYPE": db_type,
    }
    lines = " ".join(f"printf '%s=%q\\n' {k} {q(v)};" for k, v in result.items())
    runner.run(
        "write_install_result",
        f"install -d -m 700 {templates.XUI_ETC} && "
        f"(umask 077; {{ {lines} }} > {templates.XUI_INSTALL_RESULT}) && "
        f"chmod 600 {templates.XUI_INSTALL_RESULT}",
        title="Запись install-result.env (креды, URL, токен)",
    )
    return result


def read_install_result(runner: StepRunner) -> Dict[str, str]:
    """Прочитать /etc/x-ui/install-result.env (root 600, пишет их скрипт).

    Нас парсим пары KEY='value' (%q-экранированные) — env-файл безопасно
    source-ить НЕ будем (не доверяем формат), берём простым парсером.
    Возвращает словарь ключей XUI_*.
    """
    out = runner.probe(
        f"if [ -r {templates.XUI_INSTALL_RESULT} ]; then cat {templates.XUI_INSTALL_RESULT}; fi"
    )
    result: Dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line or "=" not in line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip("'").strip('"')
        result[key.strip()] = value
    return result


# ------------------------------------------------------------------
# Оркестрация: полный прогон установки
# ------------------------------------------------------------------

def run_install(
    server: dict,
    params: Dict[str, Any],
    emit,
    *,
    source: str = "github",
    local_tarball: Optional[str] = None,
    fallback_local_tarball: Optional[str] = None,
    fallback_tag: Optional[str] = None,
) -> StepRunner:
    """Полный прогон установки. source: 'github' | 'push'.

    Self-healing: source='github' + передан fallback_local_tarball → при
    провале шагов fetch_* (таймаут/сеть на сервере) установка автоматически
    продолжается push'ем из кэша — без потери сделанных шагов (deps идемпотентны).
    fallback_tag — версия в кэше (может отличаться от целевой; ставится
    честная пометка в результате, не молча).
    """
    tag = str(params["tag"])
    arch = str(params.get("arch") or "amd64")
    username = str(params["username"])
    password = str(params["password"])
    port = int(params["port"])
    web_base_path = str(params["web_base_path"])

    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        ensure_deps(runner)

        used_source = source
        if source == "push":
            if not local_tarball:
                raise ReleaseError("source=push требует local_tarball из кэша")
            push_from_cache(runner, local_tarball, tag, arch)
        else:
            try:
                fetch_from_github(runner, tag, arch)
            except StepError as e:
                if e.step in ("fetch_tarball", "fetch_checksum") and fallback_local_tarball:
                    runner.emit(
                        f"   [!] сервер не смог скачать с GitHub ({e.step}); "
                        "переключаюсь на локальный кэш бота"
                    )
                    fb_tag = fallback_tag or tag
                    push_from_cache(runner, fallback_local_tarball, fb_tag, arch)
                    used_source = "push_fallback"
                    if fb_tag != tag:
                        runner.emit(
                            f"   [!] в кэше версия {fb_tag}, а не {tag} — "
                            "ставим её (обновление до свежей отложено)"
                        )
                        tag = fb_tag
                else:
                    raise

        extract_release(runner)
        install_cli_and_unit(runner)
        configure_panel(runner, username, password, port, web_base_path)
        install_iplimit_jail(runner, port)

        # firewall: порт панели открыт всегда (кроме bind_local — панель
        # принципиально локальная, открывать было бы ошибкой); 80 — только
        # для LE-режимов (выпуск сертификата). Неудача не роняет установку,
        # но видно в логе и в результате.
        ssl_mode = str(params.get("ssl_mode") or "none")
        fw = {"ports": [], "opened": [], "skipped": []}
        if not params.get("bind_local"):
            fw = open_panel_firewall_ports(
                runner, port,
                need_http=ssl_mode in ("domain", "ip"),
            )

        # SSL до старта: acme.sh нужен свободный порт 80 (панель не слушает)
        ssl_ok = configure_ssl(runner, params)

        start_service(runner)

        # host для URL: домен (custom/domain) > bind_local 127.0.0.1 > IP сервера
        scheme = "https"
        if ssl_mode == "domain" and ssl_ok:
            host = str(params["domain"])
        elif ssl_mode == "custom":
            host = str(params.get("domain") or server.get("host") or "")
            scheme = "https"
        elif ssl_mode == "ip" and ssl_ok:
            host = str(params.get("server_ip") or server.get("host") or "")
        elif params.get("bind_local"):
            host = "127.0.0.1"
            scheme = "http"
        else:
            host = str(server.get("host") or "")
            scheme = "http"
        if ssl_mode in ("domain", "ip") and not ssl_ok:
            runner.emit(
                "   [!] выпуск сертификата не удался (порт 80?) — "
                "панель осталась на HTTP; SSL можно настроить позже из карточки"
            )
            scheme = "http"
            host = str(server.get("host") or "")

        install_result = write_install_result(
            runner, username, password, port, web_base_path, scheme, host,
        )
        # Финальное предупреждение (запрошено пользователем): панель
        # доступна извне — порт открыт в firewall сервера.
        if fw.get("opened"):
            ports_note = ", ".join(f"{p}/tcp" for p in fw["opened"])
            runner.emit(
                f"   [!] ВНИМАНИЕ: в firewall сервера открыт порт {ports_note} — "
                "панель 3x-ui доступна из интернета. Вход: логин/пароль из "
                "install-result.env, IP Limit (fail2ban) прикрывает перебор."
            )
        elif not params.get("bind_local"):
            skipped = ", ".join(f"{p}/tcp" for p in fw.get("skipped") or [])
            if skipped:
                runner.emit(
                    f"   [!] порт панели {skipped} НЕ открыт в firewall — "
                    "добавьте правило вручную, иначе панель недоступна извне"
                )
        runner.result = {  # type: ignore[attr-defined]
            "source": used_source,
            "install_result": install_result,
            "tag": tag,
            "scheme": scheme,
            "panel_host": host,
            "firewall": fw,
        }
        return runner
    finally:
        ssh.close()
