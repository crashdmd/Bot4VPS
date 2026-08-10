# -*- coding: utf-8 -*-
"""Установка/удаление сервиса WireGuard на сервере (без профилей клиентов)."""
from __future__ import annotations

from typing import Any, Dict

from core.integrator import StepError, StepRunner
from core.ssh import create_ssh_client, exec_sudo

from . import templates
from .validation import validate_addr, validate_iface, validate_port


def _repair_dpkg_if_needed(runner: StepRunner) -> None:
    """На «грязных» системах (прерванная установка, сторонняя панель вроде
    WGDashboard) dpkg остаётся в half-configured состоянии, и любой apt-get
    падает с exit 100 ещё до наших пакетов. Чиним, если нужно; шаг tolerant —
    не роняет установку, но стримит вывод для диагностики."""
    audit = runner.probe("dpkg --audit 2>/dev/null | grep -q . && echo broken || echo ok")
    if audit != "broken":
        return
    runner.emit("• Проверка целостности dpkg")
    runner.emit("   [!] обнаружен прерванный dpkg — запускаю dpkg --configure -a")
    exit_code, out, err = exec_sudo(
        runner.ssh, runner.server,
        "DEBIAN_FRONTEND=noninteractive dpkg --configure -a 2>&1; true",
        emit=lambda line: runner.emit("   " + line),
    )
    runner.emit(f"   dpkg --configure -a: exit {exit_code}")


def detect_external_iface(runner: StepRunner) -> str:
    iface = runner.probe(
        "ip route show default 2>/dev/null | awk '/default/ {print $5; exit}'"
    ) or "eth0"
    iface = validate_iface(iface)
    runner.emit(f"   внешний интерфейс: {iface}")
    return iface


def _verify_wg_runtime(runner: StepRunner) -> dict:
    packages = runner.probe(
        "command -v wg >/dev/null 2>&1 && wg --version | head -1 || echo missing"
    )
    conf_ok = runner.probe("test -s /etc/wireguard/wg0.conf && echo yes || echo no") == "yes"
    iface_up = runner.probe(
        "ip -o link show wg0 2>/dev/null | grep -q . && echo yes || echo no"
    ) == "yes"
    wg_show = runner.probe("wg show wg0 2>/dev/null | head -3 || true")
    active = runner.probe("systemctl is-active wg-quick@wg0 2>/dev/null || true")
    return {
        "packages": packages,
        "conf_ok": conf_ok,
        "iface_up": iface_up,
        "wg_show": wg_show,
        "active": active.strip(),
        "working": conf_ok and (iface_up or bool(wg_show.strip()) or active.strip() == "active"),
    }


def _enable_service_soft(runner: StepRunner) -> None:
    title = "Запуск и автозагрузка wg-quick@wg0"
    runner.emit(f"• {title}")
    exit_code, out, err = exec_sudo(
        runner.ssh, runner.server,
        "systemctl enable wg-quick@wg0 && systemctl restart wg-quick@wg0",
        emit=lambda line: runner.emit("   " + line),
    )
    if exit_code == 0:
        runner.completed.append("enable_service")
        return

    detail = (err.strip() or out.strip() or f"exit {exit_code}")[:500]
    runner.emit(f"   [!] systemctl вернул код {exit_code}")
    for line in detail.splitlines()[:8]:
        runner.emit(f"   {line}")

    state = _verify_wg_runtime(runner)
    runner.emit(f"   пакеты: {state['packages']}")
    runner.emit(f"   wg0.conf: {'есть' if state['conf_ok'] else 'нет'}")
    runner.emit(f"   интерфейс wg0: {'поднят' if state['iface_up'] else 'нет'}")
    runner.emit(f"   systemctl is-active: {state['active'] or '—'}")

    # Доп. признак: наш конфиг (PostUp с peers/*.conf или loader-скрипт)
    ours = runner.probe(
        "grep -Eq 'peers/[*][.]conf|/usr/local/lib/bot4vps/wg-load-peers' "
        "/etc/wireguard/wg0.conf 2>/dev/null && echo yes || echo no"
    ) == "yes"
    if state["working"] and ours:
        runner.emit(
            "   [!] wg-quick вернул ошибку, но WireGuard работает и конфиг Bot4VPS на месте. "
            "Возможен конфликт со сторонней панелью. Установку считаем успешной."
        )
        runner.completed.append("enable_service")
        return
    if state["working"] and not ours:
        runner.emit(
            "   [!] wg0 поднят, но конфиг не похож на Bot4VPS — "
            "возможно, остался старый интерфейс. Считаем ошибкой применения."
        )

    runner.failed = "enable_service"
    raise StepError("enable_service", exit_code, title=title,
                    detail=detail or "wg0 не поднят после restart")


def _purge_packages_soft(runner: StepRunner) -> None:
    """apt purge часто даёт exit 100 (зависимости/lock). Проверяем факт удаления."""
    title = "Удаление пакетов"
    runner.emit(f"• {title}")
    exit_code, out, err = exec_sudo(
        runner.ssh, runner.server,
        "DEBIAN_FRONTEND=noninteractive apt-get purge -y wireguard wireguard-tools "
        "2>&1; ec=$?; "
        "DEBIAN_FRONTEND=noninteractive apt-get autoremove -y 2>/dev/null || true; "
        "exit $ec",
        emit=lambda line: runner.emit("   " + line),
    )
    still = runner.probe(
        "dpkg -l wireguard wireguard-tools 2>/dev/null | awk '/^ii/{print $2}' || true"
    ).strip()
    if exit_code == 0 or not still:
        if exit_code != 0:
            runner.emit(
                f"   [!] apt вернул код {exit_code}, но пакеты wireguard* не установлены — OK"
            )
            if err or out:
                for line in (err or out).strip().splitlines()[-6:]:
                    runner.emit(f"   {line}")
        runner.completed.append("purge_packages")
        return

    detail = (err.strip() or out.strip() or f"exit {exit_code}")[:500]
    runner.emit(f"   [!] пакеты всё ещё установлены: {still}")
    runner.failed = "purge_packages"
    raise StepError("purge_packages", exit_code or 100, title=title, detail=detail)


def install(server: dict, params: Dict[str, Any], emit) -> StepRunner:
    port = validate_port(params.get("WG_PORT"))
    addr = validate_addr(params.get("WG_ADDR"))

    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        runner.run("check_os", "grep -Eiq '(debian|ubuntu)' /etc/os-release",
                   title="Проверка ОС (Debian/Ubuntu)")
        runner.run(
            "check_wireguard_support",
            "ip link add dev bot4vps-wg-test type wireguard; ec=$?; "
            "ip link del dev bot4vps-wg-test 2>/dev/null; exit $ec",
            title="Проверка поддержки WireGuard",
        )
        _repair_dpkg_if_needed(runner)
        runner.run("apt_update", "DEBIAN_FRONTEND=noninteractive apt-get update", title="apt update")
        runner.run("install_packages",
                   "DEBIAN_FRONTEND=noninteractive apt-get install -y "
                   "wireguard wireguard-tools iptables",
                   title="Установка пакетов (wireguard wireguard-tools iptables)")
        runner.run("ensure_dirs",
                   "install -d -m 700 /etc/wireguard /etc/wireguard/peers /etc/wireguard/clients",
                   title="Каталоги /etc/wireguard, peers/, clients/")

        runner.run("generate_keys",
                   "umask 077; test -s /etc/wireguard/server_private.key || "
                   "wg genkey > /etc/wireguard/server_private.key; "
                   "chmod 600 /etc/wireguard/server_private.key; "
                   "test -s /etc/wireguard/server_public.key || "
                   "wg pubkey < /etc/wireguard/server_private.key > /etc/wireguard/server_public.key",
                   title="Генерация ключей сервера")

        templates.install_peer_loader_script(runner)

        iface = detect_external_iface(runner)
        templates.create_server_config(runner, port, addr, iface)
        runner.run("enable_ip_forward",
                   "sysctl -w net.ipv4.ip_forward=1 && "
                   "echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-wg-ipforward.conf",
                   title="Включение net.ipv4.ip_forward=1")
        _enable_service_soft(runner)
    finally:
        ssh.close()
    return runner


def remove(server: dict, emit) -> StepRunner:
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        _repair_dpkg_if_needed(runner)
        runner.run("disable_service", "systemctl disable --now wg-quick@wg0 2>/dev/null; true",
                   title="Остановка и отключение wg-quick@wg0")
        _purge_packages_soft(runner)
        runner.run("cleanup_configs",
                   "rm -f /etc/wireguard/wg0.conf /etc/wireguard/server_private.key "
                   "/etc/wireguard/server_public.key; "
                   "rm -rf /etc/wireguard/peers /etc/wireguard/peers.disabled /etc/wireguard/clients; true",
                   title="Очистка /etc/wireguard")
    finally:
        ssh.close()
    return runner
