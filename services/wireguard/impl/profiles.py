# -*- coding: utf-8 -*-
"""Менеджмент клиентских профилей: добавление, удаление, включение/выключение, переименование, перевыпуск."""
from __future__ import annotations

import base64
import binascii
import ipaddress
import shlex
import uuid

from typing import Any, Dict

from core.integrator import StepError, StepRunner, read_cache
from core.ssh import create_ssh_client, exec_sudo, private_remote_upload

from . import templates
from .network import next_client_ip
from .validation import is_private_ip, validate_dns, validate_host


def _peer_value(path: str, field: str) -> str:
    return (f"awk '/^[[:space:]]*{field}[[:space:]]*=/ "
            f"{{sub(/^[^=]*=/, \"\"); print; exit}}' {shlex.quote(path)} | tr -d ' \\r\\n'")


def _peer_live_command(path: str, *, remove: bool = False) -> str:
    """Применить один peer с проверкой результата; при отсутствии wg0 — только файлы."""
    fields = f'[ -r {shlex.quote(path)} ] || exit 1; pub=$({_peer_value(path, "PublicKey")}); [ -n "$pub" ] || exit 1; '
    if remove:
        action = 'wg set wg0 peer "$pub" remove || exit $?; '
    else:
        fields += (f'aip=$({_peer_value(path, "AllowedIPs")}); [ -n "$aip" ] || exit 1; '
                   f'keep=$({_peer_value(path, "PersistentKeepalive")}); '
                   f'endp=$({_peer_value(path, "Endpoint")}); ')
        action = ('set -- wg set wg0 peer "$pub" allowed-ips "$aip"; '
                  '[ -z "$keep" ] || set -- "$@" persistent-keepalive "$keep"; '
                  '[ -z "$endp" ] || set -- "$@" endpoint "$endp"; '
                  f'"$@" preshared-key <({_peer_value(path, "PresharedKey")}) || exit $?; ')
    verify = ('peers=$(wg show wg0 peers) || exit $?; '
              'present=0; while IFS= read -r peer; do '
              '[ "$peer" != "$pub" ] || present=1; done <<< "$peers"; '
              f'[ "$present" = {0 if remove else 1} ] || '
              '{ echo "Не удалось подтвердить состояние пира wg0" >&2; exit 1; }; ')
    return fields + 'if [ -d /sys/class/net/wg0 ]; then ' + action + verify + 'fi'


def _restore_after_failure(runner, command: str, failure: Exception) -> None:
    try:
        from core.cancel_flags import recovery_scope
        with recovery_scope():
            runner.run("restore_peer_state", command, title="Восстановление состояния пира")
    except Exception as recovery:
        raise StepError("restore_peer_state", -1, title="Операция с профилем и восстановление",
                        detail=f"{failure}. Не удалось восстановить состояние: {recovery}") from failure


def add_profile(namespace: str, server: dict, name: str, params: Dict[str, Any], emit) -> Dict[str, str]:
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    cdir = f"/etc/wireguard/clients/{name}"
    try:
        runner.run("ensure_running", "ip link show wg0 up >/dev/null 2>&1",
                   title="Проверка интерфейса wg0")

        server_addr = runner.probe("awk '/^ *Address/{print $3}' /etc/wireguard/wg0.conf")
        if not server_addr:
            raise StepError("read_server_state", -1, title="Чтение состояния сервера",
                            detail="не удалось прочитать Address из wg0.conf")

        used_ips_raw = runner.probe(
            "cat /etc/wireguard/peers/*.conf /etc/wireguard/peers.disabled/*.conf 2>/dev/null | "
            "awk -F= '/^[[:space:]]*AllowedIPs/ {print $2}'"
        )
        
        client_ip = next_client_ip(server_addr, used_ips_raw)
        prefix = "32"
        # DNS: явный параметр → сохранённое предпочтение (меню «Изменить конфигурацию») → дефолт.
        dns = str(
            params.get("WG_DNS")
            or (read_cache(namespace, server.get("id", "")).get("dns") if server.get("id") else None)
            or "1.1.1.1"
        ).strip()
        
        cached = read_cache(namespace, server.get("id", "")) if server.get("id") else {}
        host = validate_host(
            params.get("WG_ENDPOINT") or cached.get("endpoint") or server.get("host") or ""
        )
        
        if is_private_ip(host):
            runner.emit("   [!] Указан приватный адрес. Клиенты вне локальной сети не смогут подключиться.")
            
        port = runner.probe("awk '/^ *ListenPort/{print $3}' /etc/wireguard/wg0.conf")
        if not port:
            raise StepError("read_server_state", -1, title="Чтение состояния сервера",
                            detail="не удалось прочитать ListenPort из wg0.conf")
        endpoint = f"{host}:{port.strip()}"

        runner.run("gen_client_keys",
                   f"install -d -m 700 {cdir} && umask 077 && "
                   f"wg genkey > {cdir}/privatekey && wg pubkey < {cdir}/privatekey > {cdir}/publickey",
                   title=f"Генерация ключей клиента «{name}»")
        templates.write_client_config(runner, name, cdir, client_ip, prefix, dns, endpoint)
        
        runner.run("write_peer_file",
                   f'printf "[Peer]\\nPublicKey = %s\\nAllowedIPs = {client_ip}/32\\n" '
                   f'"$(cat {cdir}/publickey)" > /etc/wireguard/peers/{name}.conf && '
                   f'chmod 600 /etc/wireguard/peers/{name}.conf',
                   title=f"peers/{name}.conf")
                   
        runner.run("add_peer_live",
                   _peer_live_command(f"/etc/wireguard/peers/{name}.conf"),
                   title="Применение пиров (wg set)")
    finally:
        ssh.close()
    return {"client_ip": client_ip}


def _rewrite_configuration(server, *, endpoint=None, port=None, address=None, old_address=None, dns=None, emit=None):
    from . import configuration
    ssh = create_ssh_client(server)
    try:
        files = configuration.read_files(ssh, server)
        planned = files
        if old_address is not None:
            planned = dict(files)
            path = configuration.ROOT + '/wg0.conf'
            planned[path] = configuration.replace(files[path].decode(), 'Address', old_address).encode()
        changes = configuration.prepare(planned, endpoint=endpoint, port=port, address=address, dns=dns)
        changes.pop(configuration.ROOT + '/wg0.conf', None)
        count = configuration.apply(ssh, server, files, changes)
        if emit:
            emit(f'   подтверждено изменений клиентских конфигов: {count}')
        return count
    finally:
        ssh.close()


def rewrite_client_endpoints(server: dict, host: str, emit=None) -> int:
    return _rewrite_configuration(server, endpoint=validate_host(host), emit=emit)



def rewrite_client_endpoint_ports(server: dict, port: str, emit=None) -> int:
    from .validation import validate_port
    return _rewrite_configuration(server, port=validate_port(port), emit=emit)



def rewrite_client_subnet(server: dict, old_addr: str, new_addr: str, emit=None) -> int:
    from .validation import validate_addr
    return _rewrite_configuration(server, address=validate_addr(new_addr), old_address=old_addr, emit=emit)


def rewrite_client_dns(server: dict, dns: str, emit=None) -> int:
    return _rewrite_configuration(server, dns=validate_dns(dns), emit=emit)


def reissue_profile(namespace: str, server: dict, name: str, params: Dict[str, Any], emit) -> None:
    """Перевыпуск профиля для импортированных клиентов (без изменения IP).
    
    Генерирует новую пару ключей, обновляет peers/*.conf и live-интерфейс.
    """
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    cdir = f"/etc/wireguard/clients/{name}"
    peer_file = f"/etc/wireguard/peers/{name}.conf"
    disabled_peer_file = f"/etc/wireguard/peers.disabled/{name}.conf"
    
    try:
        is_active = runner.probe(f"test -f {peer_file} && echo yes || echo no") == "yes"
        is_disabled = runner.probe(f"test -f {disabled_peer_file} && echo yes || echo no") == "yes"
        
        if is_active and is_disabled:
            raise StepError("reissue_profile", -1, title=f"Профиль «{name}»",
                            detail="Обнаружены две копии пира. Проверьте peers и peers.disabled.")
        if not is_active and not is_disabled:
            raise StepError("reissue_profile", -1, title=f"Профиль «{name}»", detail="профиль не найден")
            
        target_file = peer_file if is_active else disabled_peer_file
        
        # Безопасное чтение через awk '{sub(/^[^=]*=/, ""); print; exit}', чтобы не отрезать Base64
        allowed_ips = runner.probe(
            f'awk \'/^[[:space:]]*AllowedIPs/ {{sub(/^[^=]*=/, ""); print; exit}}\' {target_file} | tr -d \' \\r\\n\''
        )
        old_pub = runner.probe(
            f'awk \'/^[[:space:]]*PublicKey/ {{sub(/^[^=]*=/, ""); print; exit}}\' {target_file} | tr -d \' \\r\\n\''
        )
        preshared_key = runner.probe(_peer_value(target_file, "PresharedKey")) or None
        
        if not allowed_ips or not old_pub:
            raise StepError("reissue_profile", -1, title=f"Профиль «{name}»", 
                            detail="не удалось прочитать данные профиля")
                            
        try:
            if len(base64.b64decode(old_pub, validate=True)) != 32:
                raise ValueError()
            if preshared_key and len(base64.b64decode(preshared_key, validate=True)) != 32:
                raise ValueError()
            for address in allowed_ips.split(","):
                ipaddress.ip_network(address, strict=False)
        except (ValueError, binascii.Error):
            raise StepError("reissue_profile", -1, title=f"Профиль «{name}»",
                            detail="В профиле некорректные ключи или AllowedIPs") from None
        client_ip = allowed_ips.split(",")[0].split("/")[0]
        prefix = "32"
        cached = read_cache(namespace, server.get("id", "")) if server.get("id") else {}
        dns = validate_dns(str(params.get("WG_DNS") or cached.get("dns") or "1.1.1.1").strip())
        host = validate_host(
            params.get("WG_ENDPOINT") or cached.get("endpoint") or server.get("host") or ""
        )
        port = runner.probe("awk '/^ *ListenPort/{print $3}' /etc/wireguard/wg0.conf")
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise StepError("reissue_profile", -1, title=f"Профиль «{name}»",
                            detail="Не удалось прочитать корректный ListenPort из wg0.conf")
        endpoint = f"{host}:{port.strip()}"

        backup = "/etc/wireguard/.bot4vps-reissue-" + uuid.uuid4().hex
        client_conf = f"/etc/wireguard/clients/{name}.conf"
        new_keys = backup + "/new_keys"
        new_peer = backup + "/new_peer"
        ready = False
        try:
            runner.run("backup_reissue",
                       f"install -d -m 700 {backup} && cp -a {target_file} {backup}/peer && "
                       f"if [ -d {cdir} ]; then cp -a {cdir} {backup}/client_keys; fi && "
                       f"if [ -f {client_conf} ]; then cp -a {client_conf} {backup}/client.conf; fi",
                       title="Защитная копия профиля перед перевыпуском")
            ready = True
            runner.run("gen_client_keys",
                       f"install -d -m 700 {new_keys} /etc/wireguard/clients && umask 077 && "
                       f"wg genkey > {new_keys}/privatekey && wg pubkey < {new_keys}/privatekey > {new_keys}/publickey",
                       title=f"Генерация новых ключей для «{name}»")
            runner.run("prepare_new_peer",
                       f"cp -a {backup}/peer {new_peer} && "
                       f'sed -i -e "s|^[[:space:]]*PublicKey[[:space:]]*=.*|PublicKey = $(cat {new_keys}/publickey)|" {new_peer}',
                       title="Подготовка новой конфигурации пира")
            templates.write_client_config(runner, name, new_keys, client_ip, prefix, dns, endpoint,
                                          preshared_key=preshared_key)
            if is_active:
                runner.run("add_new_peer_live", _peer_live_command(new_peer),
                           title="Добавление и проверка нового пира")
                runner.run("remove_old_peer_live", _peer_live_command(backup + "/peer", remove=True),
                           title="Удаление и проверка старого пира")
            runner.run("install_reissued_profile",
                       f"install -d -m 700 {cdir} && "
                       f"install -m 600 -o root -g root {new_keys}/privatekey {cdir}/privatekey && "
                       f"install -m 600 -o root -g root {new_keys}/publickey {cdir}/publickey && "
                       f"install -m 600 -o root -g root {new_peer} {target_file}",
                       title="Сохранение перевыпущенного профиля")
        except Exception as failure:
            if ready:
                restore = (f"cp -a {backup}/peer {target_file} && rm -rf -- {cdir} && "
                           f"if [ -d {backup}/client_keys ]; then cp -a {backup}/client_keys {cdir}; fi && "
                           f"if [ -f {backup}/client.conf ]; then cp -a {backup}/client.conf {client_conf}; "
                           f"else rm -f -- {client_conf}; fi")
                if is_active:
                    restore += (f" && if [ -f {new_peer} ]; then {_peer_live_command(new_peer, remove=True)}; fi"
                                f" && {_peer_live_command(backup + '/peer')}")
                try:
                    _restore_after_failure(runner, restore, failure)
                except StepError as recovery:
                    raise StepError("reissue_recovery", -1, title="Перевыпуск и восстановление профиля",
                                    detail=f"Защитная копия сохранена: {backup}. {recovery}") from failure
            _restore_after_failure(runner, f"rm -rf -- {backup}", failure)
            raise
        try:
            from core.cancel_flags import recovery_scope
            with recovery_scope():
                runner.run("cleanup_reissue", f"rm -rf -- {backup}", title="Очистка защитной копии")
        except Exception:
            runner.emit(f"   [!] Профиль обновлён, но защитную копию не удалось удалить: {backup}")
                       
        runner.emit(f"   [OK] Профиль «{name}» перевыпущен. IP сохранен: {client_ip}")
    finally:
        ssh.close()


def reissue_all(namespace: str, server: dict, params: Dict[str, Any], emit) -> int:
    """Перевыпустить все импортированные (без clients/<name>/) профили.

    Переиспользует ``reissue_profile`` по каждому неуправляемому профилю (active
    и disabled). Возвращает число перевыпущенных. Требует настроенный Endpoint
    (иначе свежие clients/<name>.conf бесполезны) — проверяет заранее и падает с
    понятной ошибкой. Ошибка отдельного профиля не валит всю операцию.
    """
    cached = read_cache(namespace, server.get("id", "")) if server.get("id") else {}
    if not (cached.get("endpoint") or "").strip():
        raise StepError("reissue_all", -1, title="Перевыпуск профилей",
                        detail="сначала укажите Endpoint в настройках сервиса")
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        active = runner.probe(
            "find /etc/wireguard/peers -maxdepth 1 -name '*.conf' -printf '%f\\n' 2>/dev/null || true"
        )
        disabled = runner.probe(
            "find /etc/wireguard/peers.disabled -maxdepth 1 -name '*.conf' -printf '%f\\n' 2>/dev/null || true"
        )
        names = [n[:-5] for n in active.splitlines() if n.endswith(".conf")] + \
                [n[:-5] for n in disabled.splitlines() if n.endswith(".conf")]
        runner.emit(f"   кандидатов к перевыпуску: {len(names)}")
        reissued = 0
        for name in names:
            managed = runner.probe(f"test -d /etc/wireguard/clients/{name} && echo yes || echo no") == "yes"
            if managed:
                continue  # уже управляемый — пропускаем
            try:
                reissue_profile(namespace, server, name, params, emit)
                reissued += 1
            except StepError as e:
                runner.emit(f"   [!] «{name}»: {e.detail or e}")
        runner.emit(f"   перевыпущено: {reissued}")
        return reissued
    finally:
        ssh.close()


def remove_profile(server: dict, name: str, emit) -> None:
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    cdir = f"/etc/wireguard/clients/{name}"
    try:
        active = f"/etc/wireguard/peers/{name}.conf"
        disabled = f"/etc/wireguard/peers.disabled/{name}.conf"
        path = runner.probe(f"if [ -f {shlex.quote(active)} ]; then echo {shlex.quote(active)}; "
                            f"elif [ -f {shlex.quote(disabled)} ]; then echo {shlex.quote(disabled)}; fi")
        if path not in {active, disabled}:
            raise StepError("remove_profile", -1, title=f"Профиль «{name}»", detail="профиль не найден")
        runner.run("remove_peer_live", _peer_live_command(path, remove=True),
                   title="Удаление и проверка пира (wg set)")
                       
        runner.run("cleanup_profile_files",
                   f"rm -f -- {shlex.quote(active)} {shlex.quote(disabled)} && "
                   f"rm -rf -- {shlex.quote(cdir)} && rm -f -- {shlex.quote('/etc/wireguard/clients/' + name + '.conf')}",
                   title="Удаление файлов профиля")
    finally:
        ssh.close()


def toggle_profile(server: dict, name: str, enabled: bool, emit) -> None:
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    active = f"/etc/wireguard/peers/{name}.conf"
    disabled = f"/etc/wireguard/peers.disabled/{name}.conf"
    try:
        has_active = runner.probe(f"test -f {active} && echo yes || echo no") == "yes"
        has_disabled = runner.probe(f"test -f {disabled} && echo yes || echo no") == "yes"

        if has_active and has_disabled:
            raise StepError("toggle_profile", -1, title=f"Профиль «{name}»",
                            detail="Обнаружены две копии пира: peers и peers.disabled. Проверьте конфигурацию.")
        if not has_active and not has_disabled:
            raise StepError("toggle_profile", -1, title=f"Профиль «{name}»", detail="профиль не найден")
        source = active if has_active else disabled
        target = active if enabled else disabled
        runner.run("ensure_peer_directory", f"install -d -m 700 {shlex.quote(target.rsplit('/', 1)[0])}",
                   title="Подготовка каталога пиров")
        try:
            runner.run("enable_peer" if enabled else "disable_peer",
                       _peer_live_command(source, remove=not enabled),
                       title=f"{'Включение' if enabled else 'Выключение'} и проверка пира «{name}»")
            if source != target:
                runner.run("move_peer_file", f"mv -- {shlex.quote(source)} {shlex.quote(target)}",
                           title="Сохранение состояния профиля")
        except Exception as failure:
            if source != target:
                _restore_after_failure(runner, _peer_live_command(source, remove=not has_active), failure)
            raise
    finally:
        ssh.close()


def rename_profile(server: dict, old_name: str, new_name: str, emit) -> None:
    """Переименование профиля: перемещает clients/, clients.conf и peers/ (или peers.disabled/)."""
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    old_cdir = f"/etc/wireguard/clients/{old_name}"
    new_cdir = f"/etc/wireguard/clients/{new_name}"
    
    try:
        has_client = runner.probe(f"test -d {old_cdir} && echo yes || echo no") == "yes"
        has_peer = runner.probe(
            f"test -f /etc/wireguard/peers/{old_name}.conf -o -f /etc/wireguard/peers.disabled/{old_name}.conf "
            "&& echo yes || echo no") == "yes"
        if not has_client and not has_peer:
            raise StepError("rename_profile", -1, title=f"Профиль «{old_name}»", detail="профиль не найден")
            
        target_exists = runner.probe(
            f"test -e {new_cdir} -o -e /etc/wireguard/peers/{new_name}.conf "
            f"-o -e /etc/wireguard/peers.disabled/{new_name}.conf -o -e /etc/wireguard/clients/{new_name}.conf "
            f"&& echo yes || echo no"
        ) == "yes"
        if target_exists:
            raise StepError("rename_profile", -1, title=f"Профиль «{new_name}»", detail="имя уже занято")
            
        paths = [(old_cdir, new_cdir),
                 (f"/etc/wireguard/clients/{old_name}.conf", f"/etc/wireguard/clients/{new_name}.conf"),
                 (f"/etc/wireguard/peers/{old_name}.conf", f"/etc/wireguard/peers/{new_name}.conf"),
                 (f"/etc/wireguard/peers.disabled/{old_name}.conf", f"/etc/wireguard/peers.disabled/{new_name}.conf")]
        moved = []
        try:
            for index, (source, target) in enumerate(paths):
                if runner.probe(f"test -e {shlex.quote(source)} && echo yes || echo no") != "yes":
                    continue
                runner.run(f"rename_profile_{index}", f"mv -- {shlex.quote(source)} {shlex.quote(target)}",
                           title=f"Переименование {source.rsplit('/', 1)[-1]}")
                moved.append((source, target))
        except Exception as failure:
            for source, target in reversed(moved):
                _restore_after_failure(runner, f"mv -- {shlex.quote(target)} {shlex.quote(source)}", failure)
            raise
                   
        runner.emit(f"   [OK] Профиль «{old_name}» переименован в «{new_name}».")
    finally:
        ssh.close()
