# -*- coding: utf-8 -*-
"""Миграция классического wg0.conf ([Peer] inline) -> структуру Bot4VPS (peers/*.conf)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from core.integrator import StepError, StepRunner
from core.ssh import create_ssh_client, exec_sudo

from . import lifecycle
from .templates import postup_postdown, install_peer_loader_script


def split_wg0_peers(conf: str) -> Tuple[str, List[Dict[str, str]]]:
    lines = conf.splitlines()
    iface_lines: List[str] = []
    peers: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None
    pending_name: Optional[str] = None
    in_peer = False

    for line in lines:
        stripped = line.strip()
        low = stripped.lower()
        if low == "[interface]":
            in_peer = False
            current = None
            iface_lines.append(line)
            continue
        if low == "[peer]":
            if current and current.get("PublicKey"):
                peers.append(current)
            current = {}
            if pending_name:
                current["name"] = pending_name
                pending_name = None
            in_peer = True
            continue
        if stripped.startswith("#") and not in_peer:
            pending_name = stripped.lstrip("#").strip() or None
            iface_lines.append(line)
            continue
        if in_peer and current is not None:
            if stripped.startswith("#"):
                if "name" not in current:
                    nm = stripped.lstrip("#").strip()
                    if nm:
                        current["name"] = nm
                continue
            if "=" in stripped:
                key, _, val = stripped.partition("=")
                current[key.strip()] = val.strip()
            continue
        if not in_peer:
            pending_name = None
            iface_lines.append(line)

    if current and current.get("PublicKey"):
        peers.append(current)

    return "\n".join(iface_lines).rstrip() + "\n", peers


def safe_peer_name(raw: Optional[str], allowed_ips: str, idx: int, used: set) -> str:
    base = re.sub(r"[^A-Za-z0-9_-]", "_", (raw or "").strip())[:30]
    if not base or not re.match(r"^[A-Za-z0-9]", base):
        ip_match = re.match(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", allowed_ips or "")
        if ip_match:
            base = "client_" + ip_match.group(1).replace(".", "_")
        else:
            base = f"peer_{idx}"
            
    name = base
    n = 2
    while name in used:
        name = f"{base}_{n}"
        n += 1
    return name


def rebuild_interface_only(iface_text: str, iface: str) -> str:
    kept = []
    for line in iface_text.splitlines():
        low = line.strip().lower()
        if low.startswith("postup") or low.startswith("postdown"):
            continue
        kept.append(line)
    body = "\n".join(kept).rstrip() + "\n"
    if not body.lower().lstrip().startswith("[interface]"):
        body = "[Interface]\n" + body
    postup, postdown = postup_postdown(iface)
    body += f"PostUp = {postup}\nPostDown = {postdown}\n"
    return body


def migrate(server: dict, emit) -> int:
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    bak = f"/etc/wireguard/wg0.conf.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
    written: List[str] = []
    written_disabled: List[str] = []
    try:
        runner.run(
            "backup_wg0",
            f"test -f /etc/wireguard/wg0.conf && cp -a /etc/wireguard/wg0.conf {bak}",
            title="Резервная копия wg0.conf",
        )
        runner.emit(f"   -> {bak}")

        conf = runner.probe("cat /etc/wireguard/wg0.conf")
        if not conf.strip():
            raise StepError("read_wg0", -1, title="Чтение wg0.conf", detail="файл пуст")

        iface_text, peers = split_wg0_peers(conf)
        if not peers:
            raise StepError(
                "no_peers", -1, title="Анализ конфигурации",
                detail="встроенных [Peer] не найдено - миграция не нужна",
            )
        runner.emit(f"   найдено Peer: {len(peers)}")

        runner.run(
            "ensure_dirs",
            "install -d -m 700 /etc/wireguard/peers /etc/wireguard/peers.disabled /etc/wireguard/clients",
            title="Каталоги peers/, clients/",
        )

        # Безопасное извлечение PrivateKey: не используем -F=, чтобы не отрезать завершающий "=" Base64.
        runner.run(
            "ensure_server_keys",
            "test -s /etc/wireguard/server_private.key || "
            "awk '/^[[:space:]]*PrivateKey/ {sub(/^[^=]*=/, \"\"); print; exit}' /etc/wireguard/wg0.conf | tr -d ' \\r\\n' > /etc/wireguard/server_private.key; "
            "chmod 600 /etc/wireguard/server_private.key; "
            "test -s /etc/wireguard/server_public.key || "
            "wg pubkey < /etc/wireguard/server_private.key > /etc/wireguard/server_public.key",
            title="Проверка и создание ключей сервера"
        )

        used_names: set = set()
        for i, peer in enumerate(peers, 1):
            allowed = peer.get("AllowedIPs") or peer.get("allowedips") or "0.0.0.0/0"
            name = safe_peer_name(peer.get("name"), allowed, i, used_names)
            used_names.add(name)
            pubkey = peer.get("PublicKey") or peer.get("publickey") or ""
            
            if not pubkey:
                runner.emit(f"   [!] peer #{i}: нет PublicKey - пропуск")
                continue
                
            content = "[Peer]\n"
            mapping = {
                "publickey": "PublicKey",
                "allowedips": "AllowedIPs",
                "endpoint": "Endpoint",
                "presharedkey": "PresharedKey",
                "persistentkeepalive": "PersistentKeepalive"
            }
            for k, v in peer.items():
                if k.lower() in mapping:
                    content += f"{mapping[k.lower()]} = {v}\n"
            
            tmp = f"/tmp/bot4vps_peer_{name}.conf"
            sftp = runner.ssh.open_sftp()
            try:
                with sftp.file(tmp, "w") as f:
                    f.write(content)
            finally:
                sftp.close()
            runner.run(
                f"peer_{name}",
                f"mv {tmp} /etc/wireguard/peers/{name}.conf && "
                f"chmod 600 /etc/wireguard/peers/{name}.conf && "
                f"test -s /etc/wireguard/peers/{name}.conf",
                title=f"peers/{name}.conf",
            )
            written.append(name)

        if not written:
            raise StepError(
                "no_valid_peers", -1, title="Перенос Peer",
                detail="не удалось извлечь ни одного PublicKey",
            )

        iface = lifecycle.detect_external_iface(runner)
        new_conf = rebuild_interface_only(iface_text, iface)
        tmp_wg = "/tmp/bot4vps_wg0_migrated.conf"
        sftp = runner.ssh.open_sftp()
        try:
            with sftp.file(tmp_wg, "w") as f:
                f.write(new_conf)
        finally:
            sftp.close()
        runner.run(
            "write_wg0",
            f"mv {tmp_wg} /etc/wireguard/wg0.conf && chmod 600 /etc/wireguard/wg0.conf && "
            f"test -s /etc/wireguard/wg0.conf",
            title="Пересборка wg0.conf (только Interface)",
        )

        install_peer_loader_script(runner)

        runner.run(
            "apply_peers",
            '/usr/local/lib/bot4vps/wg-load-peers.sh',
            title="Применение пиров (wg set)",
        )
        
        live_peers_out = runner.probe("wg show wg0 peers 2>/dev/null || true")
        live_count = len([l for l in live_peers_out.splitlines() if l.strip()])
        if live_count < len(written):
            runner.emit(f"   [!] Внимание: перенесено {len(written)} пиров, но в live-интерфейсе {live_count}.")
        else:
            runner.emit(f"   [OK] Проверка: {live_count} пиров успешно работают в live-интерфейсе.")

        runner.emit("   [!] Внимание: миграция переносит только серверную часть (pubkey/allowedips).")
        runner.emit("   [!] Приватные ключи клиентов восстановить невозможно.")
        runner.emit("   [!] Для скачивания конфигов (QR/файл) необходимо создать новые профили.")

        runner.emit(f"   перенесено: {len(written)}")
        return len(written)
    except Exception:
        try:
            runner.emit("   [!] откат: восстановление wg0.conf из резервной копии")
            rm_targets = " ".join(f"/etc/wireguard/peers/{n}.conf" for n in written)
            rm_cmd = f"rm -f {rm_targets}; " if rm_targets else ""
            rm_disabled = " ".join(f"/etc/wireguard/peers.disabled/{n}.conf" for n in written_disabled)
            rm_disabled_cmd = f"rm -f {rm_disabled}; " if rm_disabled else ""
            
            exec_sudo(
                ssh, server,
                f"test -f {bak} && cp -a {bak} /etc/wireguard/wg0.conf; " + rm_cmd + rm_disabled_cmd +
                "ip link del dev wg0 2>/dev/null; systemctl restart wg-quick@wg0 2>/dev/null; true",
            )
        except Exception as e2:
            runner.emit(f"   [X] откат не удался: {e2}")
        raise
    finally:
        ssh.close()