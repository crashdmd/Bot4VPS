# -*- coding: utf-8 -*-
"""Менеджмент клиентских профилей: добавление, удаление, включение/выключение, переименование, перевыпуск."""
from __future__ import annotations

import ipaddress

from typing import Any, Dict

from core.integrator import StepError, StepRunner, read_cache
from core.ssh import create_ssh_client, exec_sudo

from . import templates
from .network import next_client_ip
from .validation import is_private_ip, validate_dns, validate_host


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
                   f'{templates.PEER_LOADER_SCRIPT_PATH}',
                   title="Применение пиров (wg set)")
    finally:
        ssh.close()
    return {"client_ip": client_ip}


def rewrite_client_endpoints(server: dict, host: str, emit=None) -> int:
    """Перезаписать ``Endpoint = <host>:<port>`` во всех ``clients/*.conf``.

    Вызывается при смене Endpoint, чтобы уже созданные профили получили новый
    адрес (при следующем скачивании .conf / QR). host — внешний IP/домен без
    порта, валидируется (HOST_RE → sed-safe). Возвращает число обновлённых
    клиентских конфигов. Конфиги лежат и для включённых, и для выключенных
    профилей (toggle двигает только peers/ ↔ peers.disabled/), так что
    обновляются все.
    """
    host = validate_host(host)
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit or (lambda _line: None))
    try:
        port = runner.probe("awk '/^ *ListenPort/{print $3}' /etc/wireguard/wg0.conf").strip()
        if not port:
            raise StepError("rewrite_endpoints", -1, title="Смена Endpoint",
                            detail="не удалось прочитать ListenPort из wg0.conf")
        new_ep = f"{host}:{port}"
        # host валидирован (нет |, &, \, /) → безопасно подставлять в sed-замену.
        runner.run(
            "rewrite_endpoints",
            f"for f in /etc/wireguard/clients/*.conf; do "
            f'[ -f "$f" ] || continue; '
            f"sed -i -E 's|^[[:space:]]*Endpoint[[:space:]]*=.*|Endpoint = {new_ep}|' \"$f\"; "
            f"done",
            title=f"Обновление Endpoint → {new_ep} в существующих профилях",
        )
        count = runner.probe("ls -1 /etc/wireguard/clients/*.conf 2>/dev/null | wc -l").strip()
        return int(count) if count.isdigit() else 0
    finally:
        ssh.close()



def rewrite_client_endpoint_ports(server: dict, port: str, emit=None) -> int:
    """Обновить только порт в Endpoint во всех clients/*.conf (хост сохраняется)."""
    port = str(port).strip()
    if not port.isdigit() or not (1 <= int(port) <= 65535):
        raise StepError(
            "rewrite_endpoint_ports", -1, title="Смена порта",
            detail=f"некорректный порт: {port}",
        )
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit or (lambda _line: None))
    try:
        # Python-side generate: for each conf we could SFTP, but keep remote sed via printf script
        remote = (
            "PORT=%s; "
            "for f in /etc/wireguard/clients/*.conf; do "
            "[ -f \"$f\" ] || continue; "
            "awk -v p=\"$PORT\" '"
            "/^[[:space:]]*Endpoint[[:space:]]*=/ {"
            "  line=$0; sub(/^[^=]*=[[:space:]]*/, \"\", line);"
            "  host=line; sub(/:[0-9]+[[:space:]]*$/, \"\", host);"
            "  gsub(/[[:space:]]/, \"\", host);"
            "  print \"Endpoint = \" host \":\" p; next"
            "} { print }' \"$f\" > \"$f.bot4vps_tmp\" && mv \"$f.bot4vps_tmp\" \"$f\"; "
            "done"
        ) % (port,)
        runner.run(
            "rewrite_endpoint_ports",
            remote,
            title=f"Обновление порта Endpoint → {port} в клиентских профилях",
        )
        count = runner.probe(
            "ls -1 /etc/wireguard/clients/*.conf 2>/dev/null | wc -l"
        ).strip()
        return int(count) if count.isdigit() else 0
    finally:
        ssh.close()



def rewrite_client_subnet(server: dict, old_addr: str, new_addr: str, emit=None) -> int:
    """Смена подсети туннеля: сеть меняется, host-часть адреса пира сохраняется.

    Пример: сервер 10.8.0.1/24 → 10.9.0.1/24
            клиент 10.8.0.5/32 → 10.9.0.5/32
            peers AllowedIPs то же.

    Обновляет:
      • clients/*.conf  → Address
      • peers/*.conf и peers.disabled/*.conf → AllowedIPs

    После вызова нужен reload пиров (wg set / peer loader) — делает update_config.
    Возвращает число затронутых клиентских .conf.
    """
    try:
        old_iface = ipaddress.ip_interface(old_addr.strip())
        new_iface = ipaddress.ip_interface(new_addr.strip())
    except ValueError as e:
        raise StepError("rewrite_subnet", -1, title="Смена подсети", detail=str(e))

    if old_iface.version != new_iface.version:
        raise StepError(
            "rewrite_subnet", -1, title="Смена подсети",
            detail="IPv4/IPv6 нельзя смешивать",
        )
    old_net = old_iface.network
    new_net = new_iface.network
    # Для типичного /24: меняются первые 3 октета; общий алгоритм — offset в сети
    if old_net.prefixlen != new_net.prefixlen:
        # разрешаем, но offset считаем по min prefix host bits
        pass

    old_base = int(old_net.network_address)
    new_base = int(new_net.network_address)
    old_size = old_net.num_addresses
    new_size = new_net.num_addresses

    def map_ip(ip_str: str) -> str | None:
        try:
            ip = ipaddress.ip_address(ip_str.strip())
        except ValueError:
            return None
        if ip.version != old_iface.version:
            return None
        # если IP был в старой сети — переносим offset
        if ip in old_net:
            offset = int(ip) - old_base
            if offset >= new_size:
                return None  # не влезает в новую сеть
            return str(ipaddress.ip_address(new_base + offset))
        return None

    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit or (lambda _line: None))
    updated = 0
    try:
        # Список clients/*.conf
        names = runner.probe(
            "ls -1 /etc/wireguard/clients/*.conf 2>/dev/null | xargs -n1 basename 2>/dev/null || true"
        )
        for fname in names.splitlines():
            fname = fname.strip()
            if not fname.endswith(".conf"):
                continue
            path = f"/etc/wireguard/clients/{fname}"
            _, content, _ = exec_sudo(
                runner.ssh, runner.server, f"cat {path} 2>/dev/null || true"
            )
            if not content.strip():
                continue
            new_lines = []
            changed = False
            for line in content.splitlines():
                if line.strip().lower().startswith("address"):
                    # Address = 10.8.0.5/32
                    try:
                        _, val = line.split("=", 1)
                    except ValueError:
                        new_lines.append(line)
                        continue
                    val = val.strip()
                    ip_part = val.split("/")[0].strip()
                    prefix = val.split("/")[1].strip() if "/" in val else "32"
                    mapped = map_ip(ip_part)
                    if mapped:
                        new_lines.append(f"Address = {mapped}/{prefix}")
                        changed = True
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            if changed:
                body = "\n".join(new_lines) + "\n"
                tmp = f"/tmp/bot4vps_subnet_{fname}"
                sftp = runner.ssh.open_sftp()
                try:
                    with sftp.file(tmp, "w") as f:
                        f.write(body)
                finally:
                    sftp.close()
                runner.run(
                    f"subnet_client_{fname}",
                    f"mv {tmp} {path} && chmod 600 {path}",
                    title=f"Подсеть: {fname}",
                )
                updated += 1

        # peers + peers.disabled AllowedIPs
        for peer_glob in (
            "/etc/wireguard/peers/*.conf",
            "/etc/wireguard/peers.disabled/*.conf",
        ):
            peer_list = runner.probe(
                f"ls -1 {peer_glob} 2>/dev/null || true"
            )
            for path in peer_list.splitlines():
                path = path.strip()
                if not path:
                    continue
                _, content, _ = exec_sudo(
                    runner.ssh, runner.server, f"cat {path} 2>/dev/null || true"
                )
                if not content.strip():
                    continue
                new_lines = []
                changed = False
                for line in content.splitlines():
                    if line.strip().lower().startswith("allowedips"):
                        try:
                            key, val = line.split("=", 1)
                        except ValueError:
                            new_lines.append(line)
                            continue
                        parts = []
                        for tok in val.split(","):
                            tok = tok.strip()
                            if not tok:
                                continue
                            ip_part = tok.split("/")[0].strip()
                            pref = tok.split("/")[1].strip() if "/" in tok else "32"
                            mapped = map_ip(ip_part)
                            if mapped:
                                parts.append(f"{mapped}/{pref}")
                                changed = True
                            else:
                                parts.append(tok)
                        new_lines.append(f"AllowedIPs = {', '.join(parts)}")
                    else:
                        new_lines.append(line)
                if changed:
                    body = "\n".join(new_lines) + "\n"
                    tmp = "/tmp/bot4vps_peer_subnet.tmp"
                    sftp = runner.ssh.open_sftp()
                    try:
                        with sftp.file(tmp, "w") as f:
                            f.write(body)
                    finally:
                        sftp.close()
                    runner.run(
                        "subnet_peer",
                        f"mv {tmp} {path} && chmod 600 {path}",
                        title=f"Подсеть peer: {path.split('/')[-1]}",
                    )

        if emit:
            emit(f"   подсеть: {old_addr} → {new_addr}, клиентских conf: {updated}")
        return updated
    finally:
        ssh.close()


def rewrite_client_dns(server: dict, dns: str, emit=None) -> int:
    """Перезаписать ``DNS = <dns>`` во всех ``clients/*.conf``. dns валидируется
    (validate_dns → HOST_RE на каждый токен → sed-safe). Возвращает число обновлённых
    клиентских конфигов. Используется ``update_config`` (частичная правка, §12)."""
    dns = validate_dns(dns)
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit or (lambda _line: None))
    try:
        runner.run(
            "rewrite_dns",
            "for f in /etc/wireguard/clients/*.conf; do "
            '[ -f "$f" ] || continue; '
            f"sed -i -E 's|^[[:space:]]*DNS[[:space:]]*=.*|DNS = {dns}|' \"$f\"; "
            "done",
            title=f"Обновление DNS → {dns} в клиентских профилях",
        )
        count = runner.probe("ls -1 /etc/wireguard/clients/*.conf 2>/dev/null | wc -l").strip()
        return int(count) if count.isdigit() else 0
    finally:
        ssh.close()


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
        
        if not allowed_ips or not old_pub:
            raise StepError("reissue_profile", -1, title=f"Профиль «{name}»", 
                            detail="не удалось прочитать данные профиля")
                            
        client_ip = allowed_ips.split("/")[0]
        prefix = "32"
        
        runner.run("gen_client_keys",
                   f"install -d -m 700 {cdir} && umask 077 && "
                   f"wg genkey > {cdir}/privatekey && wg pubkey < {cdir}/privatekey > {cdir}/publickey",
                   title=f"Генерация новых ключей для «{name}»")
                   
        runner.run("update_peer_pubkey",
                   f'sed -i -e "s|^\\s*PublicKey\\s*=.*|PublicKey = $(cat {cdir}/publickey)|" {target_file}',
                   title="Обновление PublicKey в peers/")
                   
        server_addr = runner.probe("awk '/^ *Address/{print $3}' /etc/wireguard/wg0.conf")
        cached = read_cache(namespace, server.get("id", "")) if server.get("id") else {}
        dns = str(params.get("WG_DNS") or cached.get("dns") or "1.1.1.1").strip()
        host = validate_host(
            params.get("WG_ENDPOINT") or cached.get("endpoint") or server.get("host") or ""
        )
        port = runner.probe("awk '/^ *ListenPort/{print $3}' /etc/wireguard/wg0.conf")
        endpoint = f"{host}:{port.strip()}"
        
        templates.write_client_config(runner, name, cdir, client_ip, prefix, dns, endpoint)
        
        if is_active:
            runner.run("remove_old_peer_live",
                       f'wg set wg0 peer "{old_pub}" remove 2>/dev/null; true',
                       title="Удаление старого пира (wg set)")
            runner.run("add_new_peer_live",
                       f'wg set wg0 peer "$(cat {cdir}/publickey)" allowed-ips {allowed_ips}',
                       title="Добавление нового пира (wg set)")
                       
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
        has_keys = runner.probe(f"test -f {cdir}/publickey && echo yes || echo no") == "yes"
        if has_keys:
            runner.run("remove_peer_live",
                       f'wg set wg0 peer "$(cat {cdir}/publickey)" remove 2>/dev/null; true',
                       title="Удаление пира (wg set)")
        else:
            peer_file = f"/etc/wireguard/peers/{name}.conf"
            disabled_peer_file = f"/etc/wireguard/peers.disabled/{name}.conf"
            runner.run("remove_peer_live",
                       f'pub=$(awk \'/^[[:space:]]*PublicKey/ {{sub(/^[^=]*=/, ""); print; exit}}\' {peer_file} {disabled_peer_file} 2>/dev/null | tr -d \' \\r\\n\'); '
                       f'wg set wg0 peer "$pub" remove 2>/dev/null; true',
                       title="Удаление импортированного пира (wg set)")
                       
        runner.run("cleanup_profile_files",
                   f"rm -f /etc/wireguard/peers/{name}.conf /etc/wireguard/peers.disabled/{name}.conf; "
                   f"rm -rf {cdir}; rm -f /etc/wireguard/clients/{name}.conf",
                   title="Удаление файлов профиля")
    finally:
        ssh.close()


def toggle_profile(server: dict, name: str, enabled: bool, emit) -> None:
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    cdir = f"/etc/wireguard/clients/{name}"
    active = f"/etc/wireguard/peers/{name}.conf"
    disabled = f"/etc/wireguard/peers.disabled/{name}.conf"
    try:
        has_active = runner.probe(f"test -f {active} && echo yes || echo no") == "yes"
        has_disabled = runner.probe(f"test -f {disabled} && echo yes || echo no") == "yes"

        if enabled:
            if has_active:
                runner.emit(f"   «{name}» уже включён")
                return
            if not has_disabled:
                raise StepError("toggle_profile", -1, title=f"Профиль «{name}»",
                                detail="профиль не найден (ни в peers/, ни в peers.disabled/)")
            runner.run("enable_peer",
                       f'install -d -m 700 /etc/wireguard/peers && '
                       f'mv {disabled} {active} && '
                       f'{templates.PEER_LOADER_SCRIPT_PATH}',
                       title=f"Включение пира «{name}»")
        else:
            if has_disabled:
                runner.emit(f"   «{name}» уже выключен")
                return
            if not has_active:
                raise StepError("toggle_profile", -1, title=f"Профиль «{name}»",
                                detail="профиль не найден")
            
            has_keys = runner.probe(f"test -f {cdir}/publickey && echo yes || echo no") == "yes"
            if has_keys:
                pub_cmd = f'cat {cdir}/publickey'
            else:
                # Безопасное чтение PublicKey
                pub_cmd = f'awk \'/^[[:space:]]*PublicKey/ {{sub(/^[^=]*=/, ""); print; exit}}\' {active} | tr -d \' \\r\\n\''
                
            runner.run("disable_peer",
                       f'install -d -m 700 /etc/wireguard/peers.disabled && '
                       f'wg set wg0 peer "$({pub_cmd})" '
                       f'remove 2>/dev/null; mv {active} {disabled}',
                       title=f"Выключение пира «{name}»")
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
        if not has_client:
            raise StepError("rename_profile", -1, title=f"Профиль «{old_name}»", detail="профиль не найден")
            
        target_exists = runner.probe(
            f"test -e {new_cdir} -o -e /etc/wireguard/peers/{new_name}.conf "
            f"-o -e /etc/wireguard/peers.disabled/{new_name}.conf -o -e /etc/wireguard/clients/{new_name}.conf "
            f"&& echo yes || echo no"
        ) == "yes"
        if target_exists:
            raise StepError("rename_profile", -1, title=f"Профиль «{new_name}»", detail="имя уже занято")
            
        runner.run("rename_client_dir",
                   f"mv {old_cdir} {new_cdir}",
                   title="Переименование директории клиента")
                   
        runner.run("rename_client_conf",
                   f"test -f /etc/wireguard/clients/{old_name}.conf && "
                   f"mv /etc/wireguard/clients/{old_name}.conf /etc/wireguard/clients/{new_name}.conf || true",
                   title="Переименование конфига клиента")
                   
        old_active = f"/etc/wireguard/peers/{old_name}.conf"
        new_active = f"/etc/wireguard/peers/{new_name}.conf"
        old_disabled = f"/etc/wireguard/peers.disabled/{old_name}.conf"
        new_disabled = f"/etc/wireguard/peers.disabled/{new_name}.conf"
        
        runner.run("rename_peer_file",
                   f"if [ -f {old_active} ]; then mv {old_active} {new_active}; "
                   f"elif [ -f {old_disabled} ]; then mv {old_disabled} {new_disabled}; fi",
                   title="Переименование peers/*.conf")
                   
        runner.emit(f"   [OK] Профиль «{old_name}» переименован в «{new_name}».")
    finally:
        ssh.close()