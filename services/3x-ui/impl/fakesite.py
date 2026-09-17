# -*- coding: utf-8 -*-
"""Native SelfSNI fake-site lifecycle for 3x-ui Reality.

The target server fetches one random public template directly from GitHub for
one installation only.  Bot4VPS never keeps a template collection.  The only
persistent operational record is the ``fakesite`` extension block in the
ordinary 3x-ui service cache; the tiny document-root marker only proves that
content currently in /var/www/html was installed by this module.
"""
from __future__ import annotations

import ipaddress
import json
import posixpath
import re
import shlex
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Tuple
from urllib.parse import quote

from core.integrator import StepError
from core.ssh import exec_sudo

from . import certs, templates
from .validation import validate_domain

GITHUB_REPOSITORY = "learning-zone/website-templates"
GITHUB_REPOSITORY_URL = f"https://github.com/{GITHUB_REPOSITORY}"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}"
GITHUB_ARCHIVE_URL = f"https://codeload.github.com/{GITHUB_REPOSITORY}/tar.gz/refs/heads/{{branch}}"

_SOURCE_UNAVAILABLE = "Источник шаблонов временно недоступен. Повторите попытку позже."
_SOURCE_NOT_FOUND = "Источник шаблонов не найден. Возможно, репозиторий был удалён или перемещён."

_TMP_ARCHIVE = "/tmp/bot4vps-selfsni-templates.tar.gz"
_TMP_WORK = "/tmp/bot4vps-selfsni-template-work"
_CONFIG_BACKUP = "/tmp/bot4vps-selfsni-nginx.previous"
_OWNER_TEXT = "bot4vps-selfsni v1\n"
_BRANCH_RE = re.compile(r"[A-Za-z0-9._/-]{1,128}\Z")
_VERSION_RE = re.compile(r"nginx/(\d+)\.(\d+)\.(\d+)")


class TemplateSourceError(RuntimeError):
    """Exact user-facing GitHub source failure."""


def _probe(ssh, server: dict, command: str) -> str:
    code, out, _ = exec_sudo(ssh, server, command, timeout=60)
    return out.strip()


def _run(
    ssh, server: dict, command: str, *, step: str, title: str, timeout: int = 180,
) -> str:
    code, out, err = exec_sudo(ssh, server, command, timeout=timeout)
    if code != 0:
        raise StepError(
            step, code, title=title,
            detail=(err or out or "команда завершилась с ошибкой").strip()[:500],
        )
    return out.strip()


def _q(value: object) -> str:
    return shlex.quote(str(value))


def _marker_path(root: str = templates.FAKESITE_WEB_ROOT) -> str:
    return posixpath.join(root, templates.FAKESITE_OWNER_MARKER)


def _split_http_response(raw: str) -> Tuple[str, str]:
    """Separate curl body from the status trailer.

    ``_exec_remote`` reads stdout line-by-line and drops a leading newline.
    Archive downloads use ``-o`` and therefore stdout consists solely of the
    trailer (``__B4HTTP__200``); requiring a preceding newline incorrectly
    classified every successful archive fetch as an unavailable source.
    """
    body, marker, status = (raw or "").rpartition("__B4HTTP__")
    return body.rstrip("\n"), status.strip() if marker else ""


def _github_response(ssh, server: dict, url: str, *, output: str | None = None,
                     timeout: int = 90) -> Tuple[str, str]:
    """GET GitHub and return (body, HTTP status) without confusing 404/network.

    curl intentionally does not use ``-f``: a HTTP 404 still has exit zero,
    and must produce the distinct source-not-found UI message.
    """
    target = f"-o {_q(output)} " if output else ""
    code, out, _err = exec_sudo(
        ssh, server,
        "curl -4 -sS -L --connect-timeout 15 --max-time " + str(timeout)
        + " --retry 3 --retry-all-errors --retry-delay 2 " + target + "-w '\\n__B4HTTP__%{http_code}' " + _q(url),
        timeout=timeout + 30,
    )
    body, status = _split_http_response(out)
    if status == "404":
        raise TemplateSourceError(_SOURCE_NOT_FOUND)
    if code != 0 or status != "200":
        raise TemplateSourceError(_SOURCE_UNAVAILABLE)
    return body, status


def _github_default_branch(ssh, server: dict) -> str:
    body, _ = _github_response(ssh, server, GITHUB_API_URL)
    try:
        branch = str((json.loads(body) or {}).get("default_branch") or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        branch = ""
    if not _BRANCH_RE.fullmatch(branch):
        raise TemplateSourceError(_SOURCE_UNAVAILABLE)
    return branch


def _prepare_template(ssh, server: dict, emit: Callable[[str], None]) -> Tuple[str, str]:
    """Resolve current GitHub default branch and prepare one random template.

    The archive is created and removed on the target.  The returned staging
    directory is under /var/www so its later rename into /var/www/html is
    atomic on normal installations.
    """
    emit("Проверка источника шаблонов…")
    branch = _github_default_branch(ssh, server)
    archive_url = GITHUB_ARCHIVE_URL.format(branch=quote(branch, safe="/"))
    emit("Загрузка случайного шаблона с GitHub…")
    _github_response(ssh, server, archive_url, output=_TMP_ARCHIVE, timeout=300)

    command = " ".join((
        "set -eu;",
        f"rm -rf {_q(_TMP_WORK)};",
        f"mkdir -p {_q(_TMP_WORK)}/extract;",
        # Reject archive path traversal and archive links before extraction.
        f"tar -tzf {_q(_TMP_ARCHIVE)} | while IFS= read -r p; do "
        "case \"/$p/\" in /*/../*|//*) exit 41;; esac; done;",
        f"if tar -tvzf {_q(_TMP_ARCHIVE)} | awk 'substr($0,1,1) ~ /[lh]/ {{ exit 1 }}'; then :; else exit 42; fi;",
        f"tar xzf {_q(_TMP_ARCHIVE)} --no-same-owner --no-same-permissions -C {_q(_TMP_WORK)}/extract;",
        f"root=$(find {_q(_TMP_WORK)}/extract -mindepth 1 -maxdepth 1 -type d -print -quit);",
        "test -n \"$root\";",
        "candidate=$(find \"$root\" -mindepth 1 -maxdepth 1 -type d ! -name assets "
        "-exec sh -c 'test -f \"$1/index.html\" && printf \"%s\\n\" \"$1\"' _ {} \\; | shuf -n1);",
        "test -n \"$candidate\";",
        f"stage={_q(templates.FAKESITE_WEB_ROOT)}.bot4vps-selfsni-stage.$$;",
        "mkdir -p \"$stage\";",
        "cp -a \"$candidate\"/. \"$stage\"/;",
        f"printf {_q(_OWNER_TEXT)} > \"$stage/{templates.FAKESITE_OWNER_MARKER}\";",
        f"rm -rf {_q(_TMP_WORK)} {_q(_TMP_ARCHIVE)};",
        "printf '\\n__STAGE__%s\\n__TEMPLATE__%s\\n' \"$stage\" \"$(basename \"$candidate\")\";",
    ))
    out = _run(ssh, server, command, step="template_prepare",
               title="Подготовка случайного шаблона", timeout=300)
    stage = template = ""
    for line in out.splitlines():
        if line.startswith("__STAGE__"):
            stage = line[len("__STAGE__"):].strip()
        elif line.startswith("__TEMPLATE__"):
            template = line[len("__TEMPLATE__"):].strip()
    valid_stage = stage.startswith(templates.FAKESITE_WEB_ROOT + ".bot4vps-selfsni-stage.")
    if not valid_stage or not template or "/" in template or "\x00" in template:
        _cleanup_template(ssh, server, stage)
        raise StepError("template_prepare", -1, title="Подготовка шаблона",
                        detail="GitHub-архив не содержит подходящего шаблона")
    return stage, template


def _cleanup_template(ssh, server: dict, stage: str = "") -> None:
    paths = [_TMP_ARCHIVE, _TMP_WORK]
    if stage.startswith(templates.FAKESITE_WEB_ROOT + ".bot4vps-selfsni-stage."):
        paths.append(stage)
    _probe(ssh, server, "rm -rf " + " ".join(_q(path) for path in paths))


def _public_ipv4(ssh, server: dict) -> str:
    """Read the public IPv4 as seen by the target rather than guessing NAT."""
    raw = _probe(
        ssh, server,
        "(curl -4 -fsS --connect-timeout 10 --max-time 20 https://api.ipify.org "
        "|| curl -4 -fsS --connect-timeout 10 --max-time 20 https://ifconfig.me/ip) 2>/dev/null",
    ).splitlines()
    for value in raw:
        try:
            ip = ipaddress.IPv4Address(value.strip())
        except ipaddress.AddressValueError:
            continue
        return str(ip)
    raise StepError("public_ip", -1, title="Определение публичного IP",
                    detail="не удалось определить публичный IPv4 сервера")


def _domain_a_records(ssh, server: dict, domain: str) -> list[str]:
    """getent follows CNAME and returns every resolved A address."""
    raw = _probe(
        ssh, server,
        f"getent ahostsv4 {_q(domain)} 2>/dev/null | awk '{{print $1}}' | sort -u",
    )
    records: list[str] = []
    for value in raw.splitlines():
        try:
            records.append(str(ipaddress.IPv4Address(value.strip())))
        except ipaddress.AddressValueError:
            continue
    return sorted(set(records))


def validate_domain_points_here(ssh, server: dict, domain: str) -> Dict[str, Any]:
    """Validate all DNS A records and expose the complete diagnostic data."""
    domain = validate_domain(domain)
    public_ip = _public_ipv4(ssh, server)
    records = _domain_a_records(ssh, server, domain)
    if public_ip not in records:
        found = ", ".join(records) if records else "не найдены"
        raise StepError(
            "dns_mismatch", -1, title="Проверка DNS",
            detail=(f"Домен: {domain}\nНайдены A-записи: {found}\n"
                    f"Публичный IP сервера: {public_ip}"),
        )
    return {"domain": domain, "a_records": records, "server_ip": public_ip}


def _ensure_nginx(ssh, server: dict) -> None:
    if _probe(ssh, server, "command -v nginx >/dev/null 2>&1 && echo yes") == "yes":
        return
    distro = _probe(ssh, server, ". /etc/os-release 2>/dev/null; echo $ID")
    installers = {
        "debian": "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx",
        "ubuntu": "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx",
        "armbian": "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx",
        "fedora": "dnf makecache -y -q && dnf -y -q install nginx",
        "amzn": "dnf makecache -y -q && dnf -y -q install nginx",
        "virtuozzo": "dnf makecache -y -q && dnf -y -q install nginx",
        "rhel": "dnf makecache -y -q && dnf -y -q install nginx",
        "almalinux": "dnf makecache -y -q && dnf -y -q install nginx",
        "rocky": "dnf makecache -y -q && dnf -y -q install nginx",
        "ol": "dnf makecache -y -q && dnf -y -q install nginx",
        "centos": "yum makecache -q -y && yum -y -q install nginx",
        "arch": "pacman -Sy --noconfirm nginx",
        "manjaro": "pacman -Sy --noconfirm nginx",
        "parch": "pacman -Sy --noconfirm nginx",
        "opensuse-tumbleweed": "zypper -q refresh && zypper -q install -y nginx",
        "opensuse-leap": "zypper -q refresh && zypper -q install -y nginx",
        "alpine": "apk add nginx",
    }
    command = installers.get(distro)
    if not command:
        raise StepError("nginx_install", -1, title="Установка nginx",
                        detail=f"дистрибутив не поддерживается: {distro or 'неизвестен'}")
    _run(ssh, server, command, step="nginx_install", title="Установка nginx", timeout=600)


def _nginx_is_modern(ssh, server: dict) -> bool:
    raw = _probe(ssh, server, "nginx -v 2>&1")
    match = _VERSION_RE.search(raw)
    if not match:
        return False
    version = tuple(int(part) for part in match.groups())
    return version >= (1, 25, 1)


def _ensure_certificate(ssh, server: dict, domain: str,
                        emit: Callable[[str], None]) -> Tuple[str, str]:
    live = f"/etc/letsencrypt/live/{domain}"
    cert_file = f"{live}/fullchain.pem"
    key_file = f"{live}/privkey.pem"
    usable = _probe(
        ssh, server,
        f"test -s {_q(cert_file)} && test -s {_q(key_file)} && "
        f"openssl x509 -checkend 0 -noout -in {_q(cert_file)} >/dev/null 2>&1 && echo yes",
    ) == "yes"
    if usable:
        emit(f"Используется существующий сертификат Let's Encrypt: {domain}")
    else:
        certs.issue_domain_certbot(ssh, server, domain, 80, False, emit)
    return cert_file, key_file


def _write_remote_file(ssh, server: dict, dest: str, content: str, *, mode: int,
                       step: str, title: str) -> None:
    """Write through /tmp then install as root, following existing SFTP pattern."""
    tmp = "/tmp/bot4vps_selfsni_" + posixpath.basename(dest)
    sftp = ssh.open_sftp()
    try:
        with sftp.file(tmp, "w") as file:
            file.write(content)
    finally:
        sftp.close()
    _run(
        ssh, server,
        f"install -d -m 755 {_q(posixpath.dirname(dest))} && "
        f"install -m {int(mode):o} {_q(tmp)} {_q(dest)} && rm -f {_q(tmp)}",
        step=step, title=title,
    )


def _install_deploy_hook(ssh, server: dict) -> None:
    # The hook is inert after config removal.  It is deliberately separate
    # from any existing renewal hook and does not alter a certificate lineage.
    content = """#!/bin/sh
# bot4vps-selfsni v1: reload only if this managed fake-site remains installed.
test -f /etc/nginx/conf.d/bot4vps-selfsni.conf || exit 0
systemctl is-active --quiet nginx || exit 0
nginx -t && systemctl reload nginx
"""
    _write_remote_file(
        ssh, server, templates.FAKESITE_DEPLOY_HOOK, content, mode=0o755,
        step="certbot_deploy_hook", title="Настройка обновления сертификата nginx",
    )


def _save_previous_config(ssh, server: dict) -> bool:
    out = _run(
        ssh, server,
        f"rm -f {_q(_CONFIG_BACKUP)}; "
        f"if test -f {_q(templates.FAKESITE_NGINX_CONF)}; then "
        f"cp -p {_q(templates.FAKESITE_NGINX_CONF)} {_q(_CONFIG_BACKUP)}; echo yes; else echo no; fi",
        step="nginx_config_backup", title="Сохранение конфигурации nginx",
    )
    return out.strip().endswith("yes")


def _restore_previous_config(ssh, server: dict, existed: bool) -> None:
    if existed:
        _probe(ssh, server,
               f"test -f {_q(_CONFIG_BACKUP)} && mv {_q(_CONFIG_BACKUP)} {_q(templates.FAKESITE_NGINX_CONF)}")
    else:
        _probe(ssh, server, f"rm -f {_q(templates.FAKESITE_NGINX_CONF)}")
    _probe(ssh, server, f"rm -f {_q(_CONFIG_BACKUP)}")


def _test_nginx(ssh, server: dict) -> None:
    _run(ssh, server, "nginx -t", step="nginx_test", title="Проверка конфигурации nginx")


def _apply_nginx(ssh, server: dict) -> None:
    active = _probe(ssh, server, "systemctl is-active nginx 2>/dev/null") == "active"
    _run(ssh, server, "systemctl reload nginx" if active else "systemctl start nginx",
         step="nginx_apply", title="Применение конфигурации nginx")


def _verify_listener(ssh, server: dict) -> None:
    _run(
        ssh, server,
        "ss -H -ltn 'sport = :9000' 2>/dev/null | grep -q '127.0.0.1:9000'",
        step="nginx_verify", title="Проверка локального слушателя 127.0.0.1:9000",
    )


def _read_tagged_output(out: str, prefix: str) -> str:
    for line in (out or "").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _install_content(ssh, server: dict, stage: str,
                     previous: Dict[str, Any]) -> Dict[str, str]:
    """Move staged content into the document root without merging files."""
    root = templates.FAKESITE_WEB_ROOT
    cached_backup = str((previous or {}).get("content_backup") or "").strip()
    command = " ".join((
        "set -eu;",
        f"root={_q(root)}; stage={_q(stage)}; backup={_q(cached_backup)};",
        "test -d \"$stage\" && test -f \"$stage/.bot4vps-selfsni-owner\";",
        "retired=''; newbackup='';",
        "if test -e \"$root\"; then",
        "  if test -f \"$root/.bot4vps-selfsni-owner\"; then",
        "    retired=\"/var/www/.bot4vps-selfsni-retired.$$\"; mv \"$root\" \"$retired\";",
        "  else",
        "    test -z \"$backup\" || { echo 'current root is not Bot4VPS-owned' >&2; exit 63; };",
        "    backup=\"/var/www/.bot4vps-selfsni-backup-$(date +%s)-$$\"; mv \"$root\" \"$backup\"; newbackup=\"$backup\";",
        "  fi;",
        "fi;",
        "mv \"$stage\" \"$root\";",
        "printf '\\n__BACKUP__%s\\n__RETIRED__%s\\n__NEWBACKUP__%s\\n' \"$backup\" \"$retired\" \"$newbackup\";",
    ))
    out = _run(ssh, server, command, step="site_install", title="Установка сайта-заглушки")
    return {
        "backup": _read_tagged_output(out, "__BACKUP__"),
        "retired": _read_tagged_output(out, "__RETIRED__"),
        "new_backup": _read_tagged_output(out, "__NEWBACKUP__"),
    }


def _finalize_content(ssh, server: dict, retired: str) -> None:
    if retired.startswith("/var/www/.bot4vps-selfsni-retired."):
        _probe(ssh, server, f"rm -rf {_q(retired)}")


def _rollback_content(ssh, server: dict, result: Dict[str, str]) -> None:
    root = templates.FAKESITE_WEB_ROOT
    retired = str(result.get("retired") or "")
    new_backup = str(result.get("new_backup") or "")
    if retired.startswith("/var/www/.bot4vps-selfsni-retired."):
        _probe(ssh, server,
               f"if test -f {_q(_marker_path(root))}; then rm -rf {_q(root)}; fi; "
               f"test -e {_q(retired)} && mv {_q(retired)} {_q(root)}")
    elif new_backup.startswith("/var/www/.bot4vps-selfsni-backup-"):
        _probe(ssh, server,
               f"if test -f {_q(_marker_path(root))}; then rm -rf {_q(root)}; fi; "
               f"test -e {_q(new_backup)} && mv {_q(new_backup)} {_q(root)}")


def install(ssh, server: dict, domain: str, previous: Dict[str, Any],
            emit: Callable[[str], None] = lambda _line: None) -> Dict[str, Any]:
    """Full non-destructive SelfSNI installation on one target server."""
    domain = validate_domain(domain)
    stage = ""
    config_existed = False
    content_result: Dict[str, str] = {}
    try:
        emit("Проверка DNS домена…")
        dns = validate_domain_points_here(ssh, server, domain)
        emit("DNS: " + ", ".join(dns["a_records"]) + f" → {dns['server_ip']}")
        stage, selected_template = _prepare_template(ssh, server, emit)
        certificate, certificate_key = _ensure_certificate(ssh, server, domain, emit)
        emit("Проверка nginx…")
        _ensure_nginx(ssh, server)
        _install_deploy_hook(ssh, server)

        config_existed = _save_previous_config(ssh, server)
        config = templates.fakesite_nginx_conf(
            domain, certificate, certificate_key, selected_template,
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            modern_http2=_nginx_is_modern(ssh, server),
        )
        _write_remote_file(ssh, server, templates.FAKESITE_NGINX_CONF, config, mode=0o644,
                           step="nginx_config", title="Запись конфигурации nginx")
        try:
            _test_nginx(ssh, server)
        except Exception:
            _restore_previous_config(ssh, server, config_existed)
            raise

        content_result = _install_content(ssh, server, stage, previous)
        stage = ""  # moved into the final document root
        try:
            _apply_nginx(ssh, server)
            _verify_listener(ssh, server)
        except Exception:
            _rollback_content(ssh, server, content_result)
            _restore_previous_config(ssh, server, config_existed)
            # Best effort: restore previously working nginx configuration.
            try:
                _apply_nginx(ssh, server)
            except Exception:
                pass
            raise
        _finalize_content(ssh, server, content_result.get("retired", ""))
        _probe(ssh, server, f"rm -f {_q(_CONFIG_BACKUP)}")
        return {
            "present": True,
            "domain": domain,
            "dest": f"127.0.0.1:{templates.FAKESITE_PORT}",
            "sport": templates.FAKESITE_PORT,
            "sni": domain,
            "xver": 1,
            "certificate": certificate,
            "certificate_key": certificate_key,
            "template": selected_template,
            "mode": "le",
            "content_backup": content_result.get("backup") or None,
        }
    finally:
        _cleanup_template(ssh, server, stage)


def remove(ssh, server: dict, previous: Dict[str, Any],
           emit: Callable[[str], None] = lambda _line: None) -> Dict[str, Any]:
    """Remove only managed nginx config and safely restore owned site content."""
    config = templates.FAKESITE_NGINX_CONF
    config_existed = _save_previous_config(ssh, server)
    _run(ssh, server, f"rm -f {_q(config)}", step="nginx_remove_config",
         title="Удаление конфигурации сайта-заглушки")
    try:
        _test_nginx(ssh, server)
    except Exception:
        _restore_previous_config(ssh, server, config_existed)
        raise
    _probe(ssh, server, f"rm -f {_q(_CONFIG_BACKUP)}")

    # A stopped nginx has no loaded configuration.  Do not start a user-owned
    # stopped service merely because a config file was removed.
    if _probe(ssh, server, "systemctl is-active nginx 2>/dev/null") == "active":
        _run(ssh, server, "systemctl reload nginx", step="nginx_apply_remove",
             title="Применение удаления конфигурации nginx")

    root = templates.FAKESITE_WEB_ROOT
    backup = str((previous or {}).get("content_backup") or "").strip()
    owned = _probe(ssh, server, f"test -f {_q(_marker_path(root))} && echo yes") == "yes"
    restored = False
    if owned:
        retired = "/var/www/.bot4vps-selfsni-removed.$$"
        if backup.startswith("/var/www/.bot4vps-selfsni-backup-"):
            command = (
                f"retired={_q(retired)}; mv {_q(root)} \"$retired\"; "
                f"if test -e {_q(backup)}; then mv {_q(backup)} {_q(root)}; "
                f"else mkdir -p {_q(root)}; fi; rm -rf \"$retired\""
            )
            _run(ssh, server, command, step="site_restore", title="Восстановление прежнего сайта")
            restored = True
        else:
            # There was no original document root.  Remove only a root whose
            # marker was just verified, then recreate an empty conventional root.
            _run(ssh, server,
                 f"retired={_q(retired)}; mv {_q(root)} \"$retired\"; "
                 f"mkdir -p {_q(root)}; rm -rf \"$retired\"",
                 step="site_remove", title="Удаление сайта-заглушки")
    elif config_existed:
        emit("[!] Контент /var/www/html не отмечен Bot4VPS — оставлен без изменений")

    return {"present": False, "restored_content": restored}
