# -*- coding: utf-8 -*-
"""Шаблоны файлов, кладуемых установщиком 3x-ui на целевой сервер.

Содержимое повторяет РЕЗУЛЬТАТ официального скрипта 3x-ui (раскладка и
семантика — байт-в-байт совместимость маршрутов установки), но написано
самостоятельно: это конфигурационные данные fail2ban/sysctl, а не код.

Генерация jail-файлов IP Limit (3x-ipl) соответствует их
setup-fail2ban: filter ловит [LIMIT_IP] записи панели, action банивает
через iptables все порты, КРОМЕ SSH и порта панели (чтобы овэр-лимитный
клиент не закрыл админу доступ), бантайм 30 минут (их дефолт).
"""
from __future__ import annotations

# --- Пути на целевом сервере (раскладка офф-скрипта) ---------------
XUI_FOLDER = "/usr/local/x-ui"
XUI_BIN = "/usr/bin/x-ui"
XUI_UNIT = "/etc/systemd/system/x-ui.service"
XUI_ETC = "/etc/x-ui"
XUI_INSTALL_RESULT = f"{XUI_ETC}/install-result.env"
XUI_LOG_DIR = "/var/log/x-ui"

# --- fail2ban: IP Limit (3x-ipl) ------------------------------------
IPLIMIT_JAIL = "/etc/fail2ban/jail.d/3x-ipl.conf"
IPLIMIT_FILTER = "/etc/fail2ban/filter.d/3x-ipl.conf"
IPLIMIT_ACTION = "/etc/fail2ban/action.d/3x-ipl.conf"
IPLIMIT_BACKEND = "/etc/fail2ban/jail.d/3x-ipl-backend.conf"
IPLIMIT_LOG = f"{XUI_LOG_DIR}/3xipl.log"
IPLIMIT_BANNED_LOG = f"{XUI_LOG_DIR}/3xipl-banned.log"
IPLIMIT_BANTIME_MIN = 30  # дефолт их меню


def iplimit_jail_conf() -> str:
    """jail.d/3x-ipl.conf — как create_iplimit_jails у офф-скрипта."""
    return (
        "[3x-ipl]\n"
        "enabled=true\n"
        "backend=auto\n"
        "filter=3x-ipl\n"
        "action=3x-ipl\n"
        f"logpath={IPLIMIT_LOG}\n"
        "maxretry=1\n"
        "findtime=32\n"
        f"bantime={IPLIMIT_BANTIME_MIN}m\n"
    )


def iplimit_filter_conf() -> str:
    """filter.d/3x-ipl.conf — failregex на [LIMIT_IP] записи панели.

    Проценты в конфигах fail2ban интерполируются: литеральный % пишется
    как %% (проверено живым fail2ban-client -t: одиночный % в datepattern
    валит конфиг с кодом 255).
    """
    return (
        "[Definition]\n"
        "datepattern = ^%%Y/%%m/%%d %%H:%%M:%%S\n"
        "failregex   = \\[LIMIT_IP\\]\\s*Email\\s*=\\s*<F-USER>.+</F-USER>\\s*\\|\\|\\s*Disconnecting OLD IP\\s*=\\s*<ADDR>\\s*\\|\\|\\s*Timestamp\\s*=\\s*\\d+\n"
        "ignoreregex =\n"
    )


def iplimit_action_conf(exempt_ports: str) -> str:
    """action.d/3x-ipl.conf — бан всех портов кроме exempt (SSH, панель).

    exempt_ports: '22' / '22,54321' — собирает вызывающий из sshd_config
    и текущего порта панели.
    """
    return (
        "[INCLUDES]\n"
        "before = iptables-allports.conf\n"
        "\n"
        "[Definition]\n"
        "\n"
        "actionstart = <iptables> -N f2b-<name>\n"
        "              <iptables> -A f2b-<name> -j <returntype>\n"
        "              <iptables> -I <chain> -j f2b-<name>\n"
        "\n"
        "actionstop = <iptables> -D <chain> -j f2b-<name>\n"
        "             <actionflush>\n"
        "             <iptables> -X f2b-<name>\n"
        "\n"
        "actioncheck = <iptables> -n -L <chain> | grep -q 'f2b-<name>[ \\t]'\n"
        "\n"
        "actionban = <iptables> -I f2b-<name> 1 -s <ip> -p tcp -m multiport ! --dports <exemptports> -j <blocktype>\n"
        "            <iptables> -I f2b-<name> 1 -s <ip> -p udp -m multiport ! --dports <exemptports> -j <blocktype>\n"
        "            echo \"$(date +%%Y/%%m/%%d %%H:%%M:%%S)   BAN   [Email] = <F-USER> [IP] = <ip> banned for <bantime> seconds.\" >> " + IPLIMIT_BANNED_LOG + "\n"
        "\n"
        "actionunban = <iptables> -D f2b-<name> -s <ip> -p tcp -m multiport ! --dports <exemptports> -j <blocktype>\n"
        "              <iptables> -D f2b-<name> -s <ip> -p udp -m multiport ! --dports <exemptports> -j <blocktype>\n"
        "              echo \"$(date +%%Y/%%m/%%d %%H:%%M:%%S)   UNBAN   [Email] = <F-USER> [IP] = <ip> unbanned.\" >> " + IPLIMIT_BANNED_LOG + "\n"
        "\n"
        "[Init]\n"
        "name = default\n"
        "chain = INPUT\n"
        f"exemptports = {exempt_ports}\n"
    )


def iplimit_backend_conf() -> str:
    """jail.d/3x-ipl-backend.conf — только для Debian 12+/Ubuntu 22.04+
    (sshd логируется в journal): [DEFAULT] backend=systemd, как у офф-скрипта."""
    return (
        "[DEFAULT]\n"
        "backend = systemd\n"
    )


# --- BBR (этап 4: вкл/выкл из карточки) ------------------------------
BBR_SYSCTL_FILE = "/etc/sysctl.d/99-bbr-x-ui.conf"


def bbr_sysctl_conf(previous_qdisc: str, previous_cc: str) -> str:
    """Конфиг BBR с сохранением предыдущих значений в комментарии первой
    строки — их disable_bbr читает его для отката (паттерн офф-скрипта)."""
    return (
        f"#{previous_qdisc}:{previous_cc}\n"
        "net.core.default_qdisc = fq\n"
        "net.ipv4.tcp_congestion_control = bbr\n"
    )


# --- systemd unit ----------------------------------------------------
# Офф-скрипт берёт unit из релизного тарболла (x-ui.service.debian) —
# мы кладём тот же файл из тарболла (installer извлекает его оттуда).
# Шаблон здесь — только fallback, если тарболл юнита не содержит.
XUI_UNIT_FALLBACK = """\
[Unit]
Description=x-ui service
Documentation=https://github.com/MHSanaei/3x-ui
After=network.target nss-lookup.target

[Service]
User=root
WorkingDirectory=/usr/local/x-ui
ExecStart=/usr/local/x-ui/x-ui

[Install]
WantedBy=multi-user.target
"""


# --- SelfSNI / сайт-заглушка Reality ---------------------------------
# Слушатель намеренно не является пользовательским параметром: Reality Dest
# всегда направляется на этот локальный адрес, firewall для него не нужен.
FAKESITE_NGINX_CONF = "/etc/nginx/conf.d/bot4vps-selfsni.conf"
FAKESITE_WEB_ROOT = "/var/www/html"
FAKESITE_PORT = 9000
FAKESITE_OWNER_MARKER = ".bot4vps-selfsni-owner"
FAKESITE_DEPLOY_HOOK = "/etc/letsencrypt/renewal-hooks/deploy/bot4vps-selfsni-nginx"


def fakesite_nginx_conf(
    domain: str,
    certificate: str,
    certificate_key: str,
    template: str,
    created: str,
    *,
    modern_http2: bool,
) -> str:
    """Единственный nginx server-блок, которым владеет SelfSNI.

    Никаких внешних портов: Xray передаёт сюда не прошедший Reality трафик
    вместе с PROXY protocol. В nginx 1.25.1 `http2` вынесен из `listen`;
    старый синтаксис оставлен только для старых пакетов без нового directive.
    """
    listen = (
        f"listen 127.0.0.1:{FAKESITE_PORT} ssl proxy_protocol;"
        if modern_http2
        else f"listen 127.0.0.1:{FAKESITE_PORT} ssl http2 proxy_protocol;"
    )
    http2 = "    http2 on;\n" if modern_http2 else ""
    return (
        "# bot4vps-selfsni v1\n"
        f"# domain={domain}\n"
        f"# template={template}\n"
        f"# created={created}\n"
        "server {\n"
        f"    {listen}\n"
        f"{http2}"
        f"    server_name {domain};\n"
        f"    root {FAKESITE_WEB_ROOT};\n"
        "    index index.html;\n"
        "\n"
        f"    ssl_certificate {certificate};\n"
        f"    ssl_certificate_key {certificate_key};\n"
        "    ssl_protocols TLSv1.2 TLSv1.3;\n"
        "    ssl_session_cache shared:SSL:10m;\n"
        "    ssl_session_timeout 10m;\n"
        "\n"
        "    location / {\n"
        "        try_files $uri $uri/ =404;\n"
        "    }\n"
        "}\n"
    )
