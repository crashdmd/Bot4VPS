# -*- coding: utf-8 -*-
"""Шаблоны конфигов WireGuard (wg0.conf сервера, clients/<name>.conf)."""
from __future__ import annotations

from typing import Tuple

from core.integrator import StepRunner

PEER_LOADER_SCRIPT_PATH = "/usr/local/lib/bot4vps/wg-load-peers.sh"

# Скрипт парсит peers/*.conf и применяет их через wg set.
# ВАЖНО: парсинг через awk '{sub(/^[^=]*=/, ""); print; exit}' используется потому,
# что Base64 ключи заканчиваются на "=". awk -F= отрезал бы этот завершающий знак.
PEER_LOADER_SCRIPT = """#!/bin/sh
# Автоматически сгенерировано Bot4VPS. Применяет peers/*.conf к live-интерфейсу.
for p in /etc/wireguard/peers/*.conf; do
    [ -f "$p" ] || continue
    pub=$(awk '/^[[:space:]]*PublicKey/ {sub(/^[^=]*=/, ""); print; exit}' "$p" | tr -d ' \\r\\n')
    aip=$(awk '/^[[:space:]]*AllowedIPs/ {sub(/^[^=]*=/, ""); print; exit}' "$p" | tr -d ' \\r\\n')
    psk=$(awk '/^[[:space:]]*PresharedKey/ {sub(/^[^=]*=/, ""); print; exit}' "$p" | tr -d ' \\r\\n')
    keep=$(awk '/^[[:space:]]*PersistentKeepalive/ {sub(/^[^=]*=/, ""); print; exit}' "$p" | tr -d ' \\r\\n')
    endp=$(awk '/^[[:space:]]*Endpoint/ {sub(/^[^=]*=/, ""); print; exit}' "$p" | tr -d ' \\r\\n')

    if [ -n "$pub" ]; then
        # Собираем аргументы без eval, через позиционные параметры
        set -- "wg" "set" "wg0" "peer" "$pub" "allowed-ips" "$aip"
        [ -n "$keep" ] && set -- "$@" "persistent-keepalive" "$keep"
        [ -n "$endp" ] && set -- "$@" "endpoint" "$endp"

        if [ -n "$psk" ]; then
            echo "$psk" | "$@" "preshared-key" "/dev/stdin" 2>/dev/null || true
        else
            "$@" 2>/dev/null || true
        fi
    fi
done
"""


def install_peer_loader_script(runner: StepRunner) -> None:
    """Устанавливает sh-скрипт парсера для использования в PostUp и live-применения."""
    runner.run("ensure_lib_dir", "install -d -m 755 /usr/local/lib/bot4vps", title="Создание /usr/local/lib/bot4vps")
    tmp_path = "/tmp/bot4vps_wg_loader.sh"
    sftp = runner.ssh.open_sftp()
    try:
        with sftp.file(tmp_path, "w") as f:
            f.write(PEER_LOADER_SCRIPT)
    finally:
        sftp.close()
    runner.run(
        "install_loader_script",
        f"mv {tmp_path} {PEER_LOADER_SCRIPT_PATH} && chmod 755 {PEER_LOADER_SCRIPT_PATH}",
        title="Установка скрипта wg-load-peers.sh"
    )


def postup_postdown(iface: str) -> Tuple[str, str]:
    """PostUp/PostDown: NAT + вызов скрипта применения пиров."""
    postup = (
        "iptables -A FORWARD -i %i -j ACCEPT; "
        f"iptables -t nat -A POSTROUTING -o {iface} -j MASQUERADE; "
        f"{PEER_LOADER_SCRIPT_PATH}"
    )
    postdown = (
        "iptables -D FORWARD -i %i -j ACCEPT; "
        f"iptables -t nat -D POSTROUTING -o {iface} -j MASQUERADE"
    )
    return postup, postdown


def _write_via_sftp_and_render(
    runner: StepRunner, tmp_path: str, template: str, step_id: str, title: str, render_cmd: str,
) -> None:
    sftp = runner.ssh.open_sftp()
    try:
        with sftp.file(tmp_path, "w") as f:
            f.write(template)
    finally:
        sftp.close()
    runner.run(step_id, render_cmd, title=title)


def create_server_config(runner: StepRunner, port: str, addr: str, iface: str) -> None:
    postup, postdown = postup_postdown(iface)
    template = (
        "[Interface]\n"
        f"Address = {addr}\n"
        f"ListenPort = {port}\n"
        "PrivateKey = __WG_SERVER_KEY__\n"
        f"PostUp = {postup}\n"
        f"PostDown = {postdown}\n"
    )
    tmp_path = "/tmp/bot4vps_wg0.tpl"
    render_cmd = (
        f'sed "s|__WG_SERVER_KEY__|$(cat /etc/wireguard/server_private.key)|" {tmp_path} '
        f"> /etc/wireguard/wg0.conf && chmod 600 /etc/wireguard/wg0.conf && "
        f"test -s /etc/wireguard/wg0.conf && rm -f {tmp_path}"
    )
    _write_via_sftp_and_render(runner, tmp_path, template, "create_wg0_conf",
                                "Создание /etc/wireguard/wg0.conf", render_cmd)


def write_client_config(
    runner: StepRunner, name: str, cdir: str,
    client_ip: str, prefix: str, dns: str, endpoint: str,
) -> None:
    template = (
        "[Interface]\n"
        "PrivateKey = __CLIENT_KEY__\n"
        f"Address = {client_ip}/{prefix}\n"
        f"DNS = {dns}\n"
        "\n"
        "[Peer]\n"
        "PublicKey = __SERVER_KEY__\n"
        f"Endpoint = {endpoint}\n"
        "AllowedIPs = 0.0.0.0/0\n"
        "PersistentKeepalive = 25\n"
    )
    tmp_path = f"/tmp/bot4vps_client_{name}.tpl"
    render_cmd = (
        f'sed -e "s|__CLIENT_KEY__|$(cat {cdir}/privatekey)|" '
        f'-e "s|__SERVER_KEY__|$(cat /etc/wireguard/server_public.key)|" '
        f"{tmp_path} > /etc/wireguard/clients/{name}.conf && "
        f"chmod 600 /etc/wireguard/clients/{name}.conf && "
        f"test -s /etc/wireguard/clients/{name}.conf && rm -f {tmp_path}"
    )
    _write_via_sftp_and_render(runner, tmp_path, template, "write_client_conf",
                                f"Конфиг клиента «{name}»", render_cmd)