#!/bin/bash
# Bot4VPS Manager — install / update / remove / status / enable-web
set -euo pipefail

REPO="https://github.com/crashdmd/Bot4VPS.git"
INSTALL_DIR="/opt/bot4vps"
SERVICE_NAME="bot4vps"
PYTHON="python3"
BRANCH="main"

# Результат open_web_port: none | ufw | firewalld | failed
FIREWALL_STATUS="none"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }


# Безопасный интерактивный ввод: работает и при curl | bash, и при обычном запуске
ask() {
    # ask "prompt" varname [default]
    local prompt="$1"
    local __var="$2"
    local __def="${3-}"
    local __reply=""
    # /dev/tty — настоящий терминал, даже если stdin = pipe
    if ! read -rp "$prompt" __reply < /dev/tty; then
        __reply=""
    fi
    if [[ -z "$__reply" && -n "$__def" ]]; then
        __reply="$__def"
    fi
    printf -v "$__var" '%s' "$__reply"
}


require_root() {
    if [[ $EUID -ne 0 ]]; then
        err "Запускайте от root (sudo)."
        exit 1
    fi
}

is_installed() {
    [[ -d "$INSTALL_DIR/.git" ]] && [[ -f "$INSTALL_DIR/bot.py" ]]
}

get_mode() {
    if [[ -f /etc/systemd/system/${SERVICE_NAME}.service ]]; then
        if grep -q "uvicorn" /etc/systemd/system/${SERVICE_NAME}.service 2>/dev/null; then
            echo "web+tg"
        else
            echo "tg-only"
        fi
    else
        echo "unknown"
    fi
}

detect_ip() {
    local ip
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    if [[ -z "$ip" ]]; then
        ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')
    fi
    echo "${ip:-<IP-сервера>}"
}

# Точечно меняет только bot_token, allowed_users, telegram_enabled
update_tg_config() {
    local token="$1"
    local user_id="$2"
    python3 - "$token" "$user_id" <<'PY'
import json
import sys
from pathlib import Path

token = sys.argv[1]
user_id = int(sys.argv[2])
path = Path("config.json")
cfg = json.loads(path.read_text(encoding="utf-8"))

cfg["bot_token"] = token
cfg["allowed_users"] = [user_id]
cfg["telegram_enabled"] = True

path.write_text(
    json.dumps(cfg, indent=4, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
PY
}

install_apt_packages() {
    if ! command -v apt-get &>/dev/null; then
        err "Автоматическая установка пакетов поддерживается только через apt-get."
        err "Установите вручную: $*"
        return 1
    fi

    info "Устанавливаю системные пакеты: $*"
    if ! apt-get update -qq; then
        err "Не удалось обновить список пакетов apt."
        return 1
    fi
    if ! DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@"; then
        err "Не удалось установить системные пакеты: $*"
        return 1
    fi
}

check_python_venv() {
    local probe_dir
    local result=0

    probe_dir=$(mktemp -d)
    "$PYTHON" -m venv "$probe_dir/venv" >/dev/null 2>&1 || result=$?
    rm -rf "$probe_dir"
    return "$result"
}

ensure_install_prerequisites() {
    if ! command -v git &>/dev/null; then
        install_apt_packages git
    fi

    if ! command -v "$PYTHON" &>/dev/null; then
        install_apt_packages python3 python3-venv
    fi

    if ! check_python_venv; then
        warn "Модуль Python venv недоступен — устанавливаю python3-venv..."
        install_apt_packages python3-venv
        if ! check_python_venv; then
            err "Не удалось создать Python virtualenv. Проверьте установку python3-venv."
            return 1
        fi
    fi
}

clone_repository() {
    if [[ -e "$INSTALL_DIR" && ! -d "$INSTALL_DIR" ]]; then
        err "Путь $INSTALL_DIR существует и не является каталогом."
        return 1
    fi

    if [[ -d "$INSTALL_DIR" && -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
        local clone_tmp
        local clone_dir
        clone_tmp=$(mktemp -d)
        clone_dir="$clone_tmp/repository"

        if ! git clone --depth 1 --branch "$BRANCH" "$REPO" "$clone_dir"; then
            rm -rf "$clone_tmp"
            err "Не удалось клонировать репозиторий."
            return 1
        fi
        if ! cp -a "$clone_dir"/. "$INSTALL_DIR"/; then
            rm -rf "$clone_tmp"
            err "Не удалось перенести код в $INSTALL_DIR."
            return 1
        fi

        rm -rf "$clone_tmp"
        return 0
    fi

    git clone --depth 1 --branch "$BRANCH" "$REPO" "$INSTALL_DIR"
}

admin_exists() {
    "$INSTALL_DIR/venv/bin/python" - <<'PY' 2>/dev/null
import sys
from core.config import get_web_config
sys.exit(0 if get_web_config().get("password_hash") else 1)
PY
}

# Drop-in с кодом первичной установки (паритет с core/setup_code.py:
# Environment=B4V_SETUP_CODE=..., права 0600). install-time копия —
# сервис на этом шаге ещё не запущен; runtime-владелец — модуль.
issue_setup_code() {
    # pipefail-безопасно: head читает конечный объём, tr и cut дочитывают
    # до EOF. Вариант «tr < /dev/urandom | head -c 20» гасил скрипт
    # молча: head закрывался после 20 байт, tr получал SIGPIPE (141),
    # set -o pipefail убивал установку прямо на этом месте (найдено
    # живым прогоном установки на чистой VPS).
    SETUP_CODE=$(head -c 1024 /dev/urandom | tr -dc 'A-Za-z0-9_-' | cut -c1-20)
    local dropin_dir="/etc/systemd/system/${SERVICE_NAME}.service.d"
    local dropin="${dropin_dir}/setup.conf"
    mkdir -p "$dropin_dir"
    printf '[Service]\nEnvironment=B4V_SETUP_CODE=%s\n' "$SETUP_CODE" > "${dropin}.tmp"
    chmod 600 "${dropin}.tmp"
    mv "${dropin}.tmp" "$dropin"
    systemctl daemon-reload
}

# Включение авторизации Web UI. Одноразовых паролей в журнал больше нет:
# если администратор ещё не задан, выдаётся код первичной установки —
# по нему Web-мастер предложит создать свой логин и пароль.
setup_web_auth() {
    local web_port="$1"
    "$INSTALL_DIR/venv/bin/python" <<'PY'
from core.config import set_web_auth
set_web_auth(True)
PY
    if admin_exists; then
        echo "  Пароль администратора уже задан — используйте его для входа."
    else
        issue_setup_code
        echo
        echo -e "${GREEN}  Код первичной установки: ${SETUP_CODE}${NC}"
        echo "  Действителен 10 минут. Откройте http://$(detect_ip):${web_port}/"
        echo "  и введите код, затем задайте свой логин и пароль администратора."
        echo "  Если код истёк — перевыпустите: bot4vps → Восстановление →"
        echo "  Код первичной установки."
    fi
}

# TLS_ARGS: аргументы ExecStart после --port N (пусто = HTTP, как раньше).
# Проставляется setup_https; enable-web без HTTPS inherits пустое значение.
TLS_ARGS=""

write_web_unit() {
    local port="$1"
    cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=Bot4VPS (Web UI + Telegram bot)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment=PYTHONPATH=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python -m uvicorn ui.web.app:app --host 0.0.0.0 --port ${port}${TLS_ARGS:+ ${TLS_ARGS}}
Restart=always
RestartSec=5
TimeoutStopSec=3
KillMode=mixed

[Install]
WantedBy=multi-user.target
EOF
}

write_tg_unit() {
    cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=Bot4VPS (Telegram only)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment=PYTHONPATH=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
}

# ─────────────────────────────────────────────
# HTTPS (модель 3x-ui: спросили → выпустили → прописали в юнит)
# ─────────────────────────────────────────────

WEB_TLS_DIR="${INSTALL_DIR}/keys/web"

# Ищет certbot: системный → venv. Не найден — пробует поставить в venv.
ensure_certbot() {
    if command -v certbot &>/dev/null; then
        command -v certbot
        return 0
    fi
    if [[ -x "${INSTALL_DIR}/venv/bin/certbot" ]]; then
        echo "${INSTALL_DIR}/venv/bin/certbot"
        return 0
    fi
    # info — в stderr: вызов «certbot=$(ensure_certbot)» захватывает stdout,
    # строка INFO в нём превращала $certbot в многострочное имя команды
    # («...venv/bin/certbot: No such file or directory» на чистых машинах
    # без системного certbot; найдено живым прогоном на чистой VPS).
    info "Ставлю certbot в venv (в requirements.txt он не входит)..." >&2
    if "${INSTALL_DIR}/venv/bin/pip" install -q certbot; then
        echo "${INSTALL_DIR}/venv/bin/certbot"
        return 0
    fi
    if apt-get -v &>/dev/null && apt-get install -y -q certbot &>/dev/null; then
        command -v certbot
        return 0
    fi
    return 1
}

# Выпускает LE-сертификат standalone и кладёт копию в keys/web/.
# Ничего не останавливает и не убивает: занятый порт 80 — понятная ошибка.
issue_letsencrypt() {
    local domain="$1"
    local email="$2"

    local certbot
    certbot=$(ensure_certbot)
    if [[ -z "$certbot" ]]; then
        err "Не удалось установить certbot."
        echo "  Установите вручную: apt install certbot — или выберите"
        echo "  самоподписанный/свой сертификат."
        return 1
    fi

    info "Выпускаю сертификат Let's Encrypt для ${domain} (порт 80)..."
    local certbot_args=(certonly --standalone -d "$domain" --non-interactive --agree-tos --keep-until-expiring)
    if [[ -n "$email" ]]; then
        certbot_args+=(-m "$email")
    else
        certbot_args+=(--register-unsafely-without-email)
    fi
    local out
    if ! out=$("$certbot" "${certbot_args[@]}" 2>&1); then
        err "Let's Encrypt не выдал сертификат."
        if echo "$out" | grep -q "Problem binding to port 80\|Address already in use"; then
            echo "  Причина: порт 80 уже занят другим сервисом — проверке LE он"
            echo "  нужен ненадолго. Посмотрите, кто его занимает:"
            echo "    ss -ltnp | grep :80"
            echo "  Существующий сервис НЕ останавливается автоматически."
        elif echo "$out" | grep -q "DNS problem\|no valid A record"; then
            echo "  Причина: домен не указывает на этот сервер. Проверьте A-запись"
            echo "  (домен должен резолвиться в публичный IP этой машины):"
            echo "    dig +short ${domain}"
        elif echo "$out" | grep -qi "rate limit\|too many certificates"; then
            echo "  Причина: Let's Encrypt ограничил выпуск для этого домена —"
            echo "  повторите через несколько часов (лимиты снимаются сами)."
        else
            echo "  Последние строки вывода certbot:"
            echo "$out" | tail -n 8 | sed 's/^/    /'
        fi
        return 1
    fi

    mkdir -p "$WEB_TLS_DIR"
    chmod 700 "${INSTALL_DIR}/keys" 2>/dev/null || true
    local live="/etc/letsencrypt/live/${domain}"
    if ! cp -f "${live}/fullchain.pem" "${WEB_TLS_DIR}/cert.pem" \
         || ! cp -f "${live}/privkey.pem" "${WEB_TLS_DIR}/key.pem"; then
        err "Let's Encrypt не положил файлы по пути ${live}"
        return 1
    fi
    chmod 600 "${WEB_TLS_DIR}/cert.pem" "${WEB_TLS_DIR}/key.pem"
    ok "Сертификат Let's Encrypt установлен (автопродление — встроено)"
}

# Самоподписанный сертификат: генерация через venv-python (cryptography).
gen_self_signed() {
    local cn="$1"
    mkdir -p "$WEB_TLS_DIR"
    if ! "${INSTALL_DIR}/venv/bin/python" "$INSTALL_DIR/core/web_tls.py" --gen-self-signed "$cn"; then
        err "Не удалось сгенерировать сертификат."
        return 1
    fi
    ok "Самоподписанный сертификат создан (${WEB_TLS_DIR})"
}

# Спрашивает про HTTPS и подготавливает TLS_ARGS + config web.tls.
# Сертификат выпускается СРАЗУ (порт 80 нужен только LE, панель ещё не
# слушает порт) — до записи юнита и старта сервиса.
setup_https() {
    local web_port="$1"
    TLS_ARGS=""

    echo
    echo -e "${CYAN}── HTTPS для Web UI ────────────────────${NC}"
    echo "  По HTTP пароль входа и кука сессии ходят по сети открытым"
    echo "  текстом. HTTPS шифрует трафик панели."
    echo
    ask "Настроить HTTPS для панели? [y/N]: " want_https "N"
    if [[ "${want_https,,}" != "y" ]]; then
        return 0
    fi

    echo
    echo "  1) Let's Encrypt — бесплатный, нужен домен, указывающий на"
    echo "     этот сервер, и свободный порт 80 (продлевается сам)"
    echo "  2) Самоподписанный — без домена, браузер будет предупреждать"
    echo "  3) Свой сертификат — пара файлов уже на сервере"
    echo
    ask "Вариант [1/2/3]: " tls_choice "1"

    case "$tls_choice" in
        1)
            local domain email
            while true; do
                ask "Домен (например panel.example.com): " domain
                domain=$(echo "$domain" | xargs)
                if [[ "$domain" =~ ^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$ ]]; then
                    break
                fi
                warn "Домен выглядит некорректно."
            done
            ask "E-mail для Let's Encrypt (Enter — без e-mail): " email ""

            if ! issue_letsencrypt "$domain" "$email"; then
                warn "Продолжаю без HTTPS — настроить можно позже:"
                echo "  Web: Настройки → Безопасность → Сеть и доступ"
                echo "  CLI: bot4vps → Безопасность → HTTPS сертификат"
                return 0
            fi
            TLS_ARGS="--ssl-certfile ${WEB_TLS_DIR}/cert.pem --ssl-keyfile ${WEB_TLS_DIR}/key.pem"
            set_tls_config_mode letsencrypt "$domain"
            WEB_SCHEME="https"
            ;;
        2)
            local cn
            cn=$(detect_ip)
            ask "Имя в сертификате (домен или IP) [${cn}]: " cn_in "$cn"
            if ! gen_self_signed "$cn_in"; then
                warn "Продолжаю без HTTPS — настроить можно позже (см. выше)."
                return 0
            fi
            TLS_ARGS="--ssl-certfile ${WEB_TLS_DIR}/cert.pem --ssl-keyfile ${WEB_TLS_DIR}/key.pem"
            set_tls_config_mode self-signed ""
            WEB_SCHEME="https"
            ;;
        3)
            local cert_path key_path
            while true; do
                ask "Путь к сертификату (PEM): " cert_path
                [[ -f "$cert_path" ]] && break
                warn "Файл не найден: $cert_path"
            done
            while true; do
                ask "Путь к закрытому ключу (PEM): " key_path
                [[ -f "$key_path" ]] && break
                warn "Файл не найден: $key_path"
            done
            if [[ "$cert_path" == *'"'* || "$key_path" == *'"'* ]]; then
                warn "Путь с двойной кавычкой не поддерживается —"
                echo "  переименуйте файл. Продолжаю без HTTPS (см. выше)."
                return 0
            fi
            if ! "${INSTALL_DIR}/venv/bin/python" - "$cert_path" "$key_path" <<'PY'
import sys
from core.web_tls import validate_pair
try:
    validate_pair(sys.argv[1], sys.argv[2])
except ValueError as e:
    print(str(e), file=sys.stderr)
    sys.exit(1)
PY
            then
                warn "Пара не прошла проверку. Продолжаю без HTTPS —"
                echo "  настроить можно позже (см. выше)."
                return 0
            fi
            # ВАЖНО: сигнатура set_tls_config_mode — mode domain cert key.
            # Раньше пути передавались со сдвигом (cert_path попадал в
            # domain): config получал {custom, domain: <путь>} без путей,
            # и enable-web затем молча включал Web без HTTPS.
            set_tls_config_mode custom "" "$cert_path" "$key_path"
            # Флаги строит ядро (core.web_tls.unit_tls_flags): пути с
            # пробелами квотируются там же, что и для enable-web.
            if ! TLS_ARGS=$("${INSTALL_DIR}/venv/bin/python" <<'PY'
from core.config import get_tls_config
from core.web_tls import unit_tls_flags
print(unit_tls_flags(get_tls_config()), end="")
PY
            ); then
                warn "Не удалось собрать TLS-флаги. Продолжаю без HTTPS —"
                echo "  настроить можно позже (см. выше)."
                return 0
            fi
            WEB_SCHEME="https"
            ;;
        *)
            warn "Неверный выбор — продолжаю без HTTPS."
            return 0
            ;;
    esac
}

# config.json -> web.tls (mode + домен/пути) из install.sh.
set_tls_config_mode() {
    local mode="$1" domain="$2" cert="${3:-}" key="${4:-}"
    "${INSTALL_DIR}/venv/bin/python" - "$mode" "$domain" "$cert" "$key" <<'PY'
import sys
from core.config import apply_tls_config
mode, domain, cert, key = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
cfg = {"mode": mode}
if domain:
    cfg["domain"] = domain
if cert and key:
    cfg["cert_path"] = cert
    cfg["key_path"] = key
apply_tls_config(cfg)
PY
}

# ─────────────────────────────────────────────
# WEB PORT VALIDATION
# ─────────────────────────────────────────────
read_web_port() {
    local default_port="${1:-8080}"
    local input_port

    while true; do
        ask "Порт Web UI [${default_port}]: " input_port "$default_port"

        if [[ "$input_port" =~ ^[0-9]+$ ]] && (( input_port >= 1 && input_port <= 65535 )); then
            echo "$input_port"
            return 0
        fi

        warn "Некорректный порт. Укажите целое число от 1 до 65535."
    done
}

# ─────────────────────────────────────────────
# FIREWALL + PORT CHECKS
# ─────────────────────────────────────────────
open_web_port() {
    local port="$1"
    FIREWALL_STATUS="none"

    if command -v ufw &>/dev/null && ufw status 2>/dev/null | grep -qi "Status: active"; then
        info "UFW активен — открываю ${port}/tcp..."
        if ufw allow "${port}/tcp" comment "Bot4VPS Web UI" >/dev/null; then
            FIREWALL_STATUS="ufw"
            ok "UFW: разрешён ${port}/tcp"
        else
            FIREWALL_STATUS="failed"
            warn "Не удалось добавить правило UFW для ${port}/tcp"
        fi
        return
    fi

    if command -v firewall-cmd &>/dev/null && systemctl is-active --quiet firewalld 2>/dev/null; then
        info "firewalld активен — открываю порт ${port}/tcp..."
        if firewall-cmd --permanent --add-port="${port}/tcp" >/dev/null 2>&1 \
           && firewall-cmd --reload >/dev/null 2>&1; then
            FIREWALL_STATUS="firewalld"
            ok "firewalld: разрешён ${port}/tcp"
        else
            FIREWALL_STATUS="failed"
            warn "Не удалось добавить правило firewalld для ${port}/tcp"
        fi
        return
    fi

    if command -v nft &>/dev/null; then
        local rules
        rules=$(nft list ruleset 2>/dev/null || true)

        if [[ -n "$rules" ]]; then
            # Не меняем runtime-only nftables: без гарантированно известной
            # persistent-конфигурации правило может исчезнуть после reboot.
            FIREWALL_STATUS="failed"
            warn "Обнаружен активный nftables, но его persistent-конфигурация не определена."
            warn "Порт ${port}/tcp не изменяю автоматически — откройте его в nftables вручную."
            return
        fi
    fi

    FIREWALL_STATUS="none"
    info "Активный firewall не обнаружен — локально порт ничем не блокируется"
}

port_is_listening() {
    local port="$1"
    if command -v ss &>/dev/null; then
        ss -lnt 2>/dev/null | grep -qE ":${port}[[:space:]]"
        return $?
    fi
    if command -v netstat &>/dev/null; then
        netstat -lnt 2>/dev/null | grep -qE ":${port}[[:space:]]"
        return $?
    fi
    return 1
}

web_local_ok() {
    # scheme: http | https (self-signed проверяем без верификации)
    local port="$1"
    local scheme="${2:-http}"
    if command -v curl &>/dev/null; then
        curl -fsS --max-time 3 -k "${scheme}://127.0.0.1:${port}/" -o /dev/null 2>/dev/null
        return $?
    fi
    port_is_listening "$port"
}

report_web_status() {
    local port="$1"
    local scheme="${2:-http}"
    local host_ip
    host_ip=$(detect_ip)

    echo
    local listening=false local_ok=false

    # На слабых машинах uvicorn поднимается дольше, чем sleep 2 после
    # старта юнита (импорт роутов, JobQueue): единичная проверка ловила
    # «не слушает порт» при полностью рабочей панели (замечено на чистой
    # VPS 1 CPU: bind на 4-й секунде). Ждём готовности до 15 с.
    local attempt
    for attempt in $(seq 1 15); do
        if port_is_listening "$port"; then
            listening=true
        fi
        if web_local_ok "$port" "$scheme"; then
            local_ok=true
        fi
        $local_ok && break
        sleep 1
    done

    if $local_ok; then
        ok "Web UI запущен"
        ok "Порт ${port} доступен локально"
    elif $listening; then
        warn "Порт ${port} слушается, но HTTP-ответ не получен"
    else
        err "Web UI не слушает порт ${port}"
        echo "  Проверьте: journalctl -u ${SERVICE_NAME} -n 50"
        return 1
    fi

    case "${FIREWALL_STATUS:-none}" in
        ufw|firewalld)
            ok "Правило firewall настроено (${FIREWALL_STATUS})"
            ;;
        failed)
            warn "Правило firewall добавить не удалось — откройте TCP ${port} вручную"
            ;;
        none)
            ok "Firewall отсутствует / не блокирует порт локально"
            ;;
    esac

    echo
    echo "  Web UI:   ${scheme}://${host_ip}:${port}/"
    echo
    if $local_ok; then
        echo -e "${YELLOW}⚠ Web UI запущен на порту ${port}, внешний доступ с этого хоста не подтверждается автоматически.${NC}"
        echo "  Если UI не открывается из браузера — проверьте firewall/security group"
        echo "  у VPS-провайдера и откройте TCP ${port} вручную."
        if [[ "$scheme" == "https" ]]; then
            echo "  Самоподписанный сертификат: браузер предупредит о нём — это ожидаемо."
        fi
    fi
}

# ─────────────────────────────────────────────
# ENABLE WEB UI  (tg-only → web+tg)
# ─────────────────────────────────────────────
do_enable_web() {
    require_root

    if ! is_installed; then
        err "Bot4VPS не установлен. Сначала: $0 install"
        exit 1
    fi

    local mode
    mode=$(get_mode)

    if [[ "$mode" == "web+tg" ]]; then
        ok "Web UI уже включён."
        local port
        port=$(grep -oP '--port \K[0-9]+' /etc/systemd/system/${SERVICE_NAME}.service 2>/dev/null || echo "8080")
        echo "  Web UI: http://$(detect_ip):${port}/"
        return
    fi

    if [[ "$mode" != "tg-only" ]]; then
        err "Не удалось определить текущий режим (нет systemd-юнита?)."
        exit 1
    fi

    echo
    echo -e "${CYAN}── Включение Web UI ───────────────────${NC}"
    echo "  Текущий режим: только Telegram"
    echo "  Данные серверов и настройки Telegram сохраняются"
    echo

    local WEB_PORT
    WEB_PORT=$(read_web_port 8080)

    info "Проверяю зависимости..."
    cd "$INSTALL_DIR"
    # shellcheck disable=SC1091
    source venv/bin/activate
    pip install -q -r requirements.txt

    info "Включаю авторизацию Web UI..."
    setup_web_auth "$WEB_PORT"

    # HTTPS: режим мог быть настроен раньше (config web.tls). Юнит
    # переписывается — TLS-флаги обязаны пережить включение Web.
    WEB_SCHEME="http"
    TLS_ARGS=$("${INSTALL_DIR}/venv/bin/python" <<'PY'
import sys
from core.config import get_tls_config
from core.web_tls import tls_asset_paths, unit_tls_flags

tls = get_tls_config()
if any(not p.is_file() for p in tls_asset_paths(tls)):
    # Управляемая пара исчезла — юнит со ssl-флагами не стартовал бы.
    print("__MISSING__", end="")
else:
    print(unit_tls_flags(tls), end="")
PY
)
    if [[ "$TLS_ARGS" == "__MISSING__" ]]; then
        warn "Сертификат HTTPS не найден — включаю Web без HTTPS."
        echo "  Перевыпустите: bot4vps → Безопасность → HTTPS сертификат."
        TLS_ARGS=""
    elif [[ -n "$TLS_ARGS" ]]; then
        WEB_SCHEME="https"
    fi

    open_web_port "$WEB_PORT"

    info "Переключаю сервис на Web + Telegram..."
    systemctl stop ${SERVICE_NAME}.service 2>/dev/null || true
    write_web_unit "$WEB_PORT"
    systemctl daemon-reload
    systemctl enable ${SERVICE_NAME}.service
    systemctl start ${SERVICE_NAME}.service
    sleep 2

    if systemctl is-active --quiet ${SERVICE_NAME}.service; then
        ok "Сервис запущен"
    else
        err "Сервис не поднялся. journalctl -u ${SERVICE_NAME} -n 40"
        return 1
    fi

    report_web_status "$WEB_PORT" "${WEB_SCHEME:-http}"
    echo "  Настройки Telegram — в Web UI (Настройки → Telegram)."
    echo "  Токен и allowed_users из config.json используются как есть."
}

# ─────────────────────────────────────────────
# INSTALL
# ─────────────────────────────────────────────
do_install() {
    require_root
    ensure_install_prerequisites

    if is_installed; then
        warn "Bot4VPS уже установлен в $INSTALL_DIR"
        ask "Переустановить? [y/N]: " ans "N"
        [[ "${ans,,}" == "y" ]] || { info "Отмена."; return; }
        do_remove --keep-data
    fi

    echo
    echo -e "${CYAN}╔══════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║     Bot4VPS — установка              ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════╝${NC}"
    echo
    echo "Выберите режим:"
    echo "  1) Только Telegram"
    echo "  2) Web + Telegram (рекомендуется)"
    echo
    ask "Ваш выбор [1/2]: " MODE "2"

    case "$MODE" in
        1) MODE_NAME="tg-only" ;;
        2) MODE_NAME="web+tg"  ;;
        *) err "Неверный выбор."; exit 1 ;;
    esac

    local WEB_PORT=8080
    if [[ "$MODE_NAME" == "web+tg" ]]; then
        WEB_PORT=$(read_web_port "$WEB_PORT")
    fi

    info "Клонирую репозиторий..."
    clone_repository
    cd "$INSTALL_DIR"

    info "Создаю venv и ставлю зависимости..."
    $PYTHON -m venv venv
    # shellcheck disable=SC1091
    source venv/bin/activate
    pip install -q --upgrade pip
    pip install -q -r requirements.txt
    ok "Зависимости установлены"

    mkdir -p scripts keys backup logs
    ok "Каталоги готовы"

    if [[ ! -f config.json ]]; then
        cp config.example.json config.json
    fi
    # В config.json попадает токен бота (tg-only) и прочие секреты:
    # cp наследует 644 у example, права ставим сразу, не полагаясь на
    # первый сохраняющий config запуск приложения.
    chmod 600 config.json

    if [[ "$MODE_NAME" == "tg-only" ]]; then
        echo
        echo -e "${CYAN}── Настройка Telegram ─────────────────${NC}"
        while true; do
            ask "Токен бота (от @BotFather): " BOT_TOKEN
            BOT_TOKEN=$(echo "$BOT_TOKEN" | xargs)
            [[ -n "$BOT_TOKEN" && "$BOT_TOKEN" != YOUR_* ]] && break
            warn "Введите настоящий токен."
        done
        while true; do
            ask "Ваш Telegram User ID: " USER_ID
            USER_ID=$(echo "$USER_ID" | xargs)
            [[ "$USER_ID" =~ ^[0-9]+$ ]] && break
            warn "Нужно целое число (@userinfobot)."
        done
        update_tg_config "$BOT_TOKEN" "$USER_ID"
        ok "Токен, User ID и telegram_enabled=true записаны в config.json"
    else
        echo
        echo -e "${CYAN}── Настройка Web UI ───────────────────${NC}"
        setup_web_auth "$WEB_PORT"
        # Сертификат — до записи юнита: TLS_ARGS попадает в ExecStart,
        # LE-проверке нужен только порт 80 (панель его не слушает).
        WEB_SCHEME="http"
        setup_https "$WEB_PORT"
    fi

    if [[ "$MODE_NAME" == "web+tg" ]]; then
        # Порт открываем ПОСЛЕ клонирования и зависимостей: упавшая
        # установка не должна оставлять правило в firewall.
        open_web_port "$WEB_PORT"
    fi

    info "Настраиваю systemd..."
    for old in bot4vps-web bot4vps-bot bot4vps; do
        systemctl disable --now "${old}.service" 2>/dev/null || true
    done

    if [[ "$MODE_NAME" == "web+tg" ]]; then
        write_web_unit "$WEB_PORT"
    else
        write_tg_unit
    fi

    systemctl daemon-reload
    systemctl enable ${SERVICE_NAME}.service

    ask "Запустить сейчас? [Y/n]: " start_now "Y"
    if [[ "${start_now,,}" == "y" ]]; then
        systemctl restart ${SERVICE_NAME}.service
        sleep 2
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then
            ok "Сервис запущен"
        else
            err "Не запустился. journalctl -u ${SERVICE_NAME} -n 30"
        fi
    fi

    echo
    ok "Установка завершена ($MODE_NAME)"
    echo "  Каталог:  $INSTALL_DIR"
    echo "  Статус:   systemctl status ${SERVICE_NAME}"
    echo "  Логи:     journalctl -u ${SERVICE_NAME} -f"
    echo "  Меню:     bot4vps (консоль управления)"
    # Команду bot4vps создаёт сам сервис при старте (ui/cli/bootstrap.py),
    # отдельного install-time шага больше нет.

    if [[ "$MODE_NAME" == "web+tg" ]]; then
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then
            # || true: сбой Web не должен обрывать установку под set -e
            # до подсказок ниже (Telegram-онбординг)
            report_web_status "$WEB_PORT" "${WEB_SCHEME:-http}" || true
        else
            echo "  Web UI:   ${WEB_SCHEME:-http}://$(detect_ip):${WEB_PORT}/"
        fi
        echo "  Настройте Telegram через Настройки → Telegram"
        echo "  Если Telegram включён, но Token/User ID отсутствуют,"
        echo "  Dashboard автоматически предложит первоначальную настройку."
    else
        echo
        echo "  Telegram-бот настроен (telegram_enabled=true)."
        echo "  Напишите боту /start"
        echo "  Позже Web UI можно включить: $0 enable-web"
    fi
}

# ─────────────────────────────────────────────
# UPDATE
# ─────────────────────────────────────────────
do_update() {
    require_root

    if ! is_installed; then
        err "Bot4VPS не установлен. Сначала: $0 install"
        exit 1
    fi

    cd "$INSTALL_DIR"

    info "Проверяю обновления..."
    git fetch --quiet origin

    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse "origin/$BRANCH" 2>/dev/null || git rev-parse origin/main)

    if [[ "$LOCAL" == "$REMOTE" ]]; then
        ok "Уже установлена последняя версия ($(git rev-parse --short HEAD))"
        return
    fi

    echo
    echo -e "${YELLOW}Доступны обновления:${NC}"
    git log --oneline --no-decorate "$LOCAL..$REMOTE"
    echo
    ask "Обновить сейчас? [Y/n]: " ans "Y"
    [[ "${ans,,}" == "y" ]] || { info "Отмена."; return; }

    info "Обновляю код..."
    # Стэш нужен только на время pull/reset. Запоминаем: создали ли МЫ
    # новый стэш (refs/stash появился/сменился) — чтобы после обновления
    # вернуть правки, а не терять их молча в stash list.
    local stash_before stash_after
    stash_before=$(git rev-parse -q --verify refs/stash 2>/dev/null || true)
    git stash push -u -m "bot4vps-manager-auto" 2>/dev/null || true
    stash_after=$(git rev-parse -q --verify refs/stash 2>/dev/null || true)

    if ! git pull --ff-only origin "$BRANCH"; then
        warn "Fast-forward не удался. Пробую reset --hard..."
        git reset --hard "origin/$BRANCH"
    fi

    if [[ -n "$stash_after" && "$stash_after" != "$stash_before" ]]; then
        if ! git stash pop; then
            warn "Локальные правки конфликтуют с обновлённым кодом и не"
            warn "возвращены автоматически. Они целы в стэше:"
            warn "  git -C $INSTALL_DIR stash list / git stash pop"
        fi
    fi

    info "Обновляю зависимости..."
    # shellcheck disable=SC1091
    source venv/bin/activate
    pip install -q --upgrade pip
    pip install -q -r requirements.txt

    if systemctl is-enabled --quiet ${SERVICE_NAME}.service 2>/dev/null; then
        info "Перезапускаю сервис..."
        systemctl restart ${SERVICE_NAME}.service
        sleep 2
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then
            ok "Сервис перезапущен"
        else
            err "Сервис не поднялся. Смотрите: journalctl -u ${SERVICE_NAME} -n 50"
        fi
    else
        warn "Сервис не включён в автозагрузку"
    fi

    ok "Обновление завершено → $(git rev-parse --short HEAD)"
}

# ─────────────────────────────────────────────
# WEB PORT / FIREWALL CLEANUP
# ─────────────────────────────────────────────
get_installed_web_port() {
    local unit="/etc/systemd/system/${SERVICE_NAME}.service"
    local port=""

    if [[ -f "$unit" ]]; then
        port=$(grep -oE -- '--port [0-9]+' "$unit" 2>/dev/null | tail -n1 | awk '{print $2}')
    fi

    if [[ "$port" =~ ^[0-9]+$ ]] && (( port >= 1 && port <= 65535 )); then
        echo "$port"
        return 0
    fi

    return 1
}

close_web_port() {
    local port="$1"
    local handled=0

    if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qE '^Status:.*active'; then
        if ufw delete allow "${port}/tcp" >/dev/null 2>&1; then
            ok "UFW: правило ${port}/tcp удалено"
        else
            warn "Не удалось удалить правило UFW для ${port}/tcp"
        fi
        handled=1
    fi

    if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
        if firewall-cmd --permanent --remove-port="${port}/tcp" >/dev/null 2>&1; then
            firewall-cmd --remove-port="${port}/tcp" >/dev/null 2>&1 || true
            firewall-cmd --reload >/dev/null 2>&1 || true
            ok "firewalld: правило ${port}/tcp удалено"
        else
            warn "Не удалось удалить правило firewalld для ${port}/tcp"
        fi
        handled=1
    fi

    if (( handled == 0 )); then
        info "UFW/firewalld не обнаружены — правило ${port}/tcp через них не закрывалось"
    fi
}

# ─────────────────────────────────────────────
# REMOVE
# ─────────────────────────────────────────────
do_remove() {
    local REMOVE_WEB_PORT=""
    REMOVE_WEB_PORT=$(get_installed_web_port 2>/dev/null || true)
    require_root
    local keep_data=false

    # Вызов из переустановки: do_remove --keep-data

    if [[ -n "$REMOVE_WEB_PORT" ]]; then
        info "Закрываю Web-порт ${REMOVE_WEB_PORT}/tcp..."
        close_web_port "$REMOVE_WEB_PORT"
    fi

    if [[ "${1:-}" == "--keep-data" ]]; then
        keep_data=true
    fi

    if ! is_installed && [[ ! -f /etc/systemd/system/${SERVICE_NAME}.service ]]; then
        warn "Bot4VPS не найден."
        return
    fi

    echo
    if $keep_data; then
        info "Удаление кода (данные сохраняются)..."
    else
        echo -e "${CYAN}── Удаление Bot4VPS ───────────────────${NC}"
        echo "  1) Только код и сервис"
        echo "     (сохранить config.json, servers.json, monitor.json, keys/,"
        echo "      scripts/, data/, backup/, logs/)"
        echo "  2) Удалить всё полностью"
        echo
        ask "Ваш выбор [1/2]: " rm_choice "1"
        case "$rm_choice" in
            1) keep_data=true ;;
            2) keep_data=false ;;
            *) err "Неверный выбор."; return ;;
        esac

        if ! $keep_data; then
            warn "Будет удалено безвозвратно:"
            echo "  • $INSTALL_DIR (код + все данные)"
            echo "  • systemd-юнит ${SERVICE_NAME}"
            if [[ -f "$INSTALL_DIR/keys/secret.key" ]]; then
                echo
                warn "Вместе с Bot4VPS будет удалён мастер-ключ шифрования."
                warn "Без сохранённого мастер-ключа вы не сможете расшифровать"
                warn "защищённые данные и резервные копии после удаления Bot4VPS."
                echo "  Сохраните копию мастер-ключа: Web → Настройки → Безопасность →"
                echo "  Мастер-ключ, либо: cat $INSTALL_DIR/keys/secret.key"
            fi
            echo
            ask "Точно удалить всё? [y/N]: " ans "N"
            [[ "${ans,,}" == "y" ]] || { info "Отмена."; return; }
        else
            info "Код и сервис будут удалены, пользовательские данные останутся."
            ask "Продолжить? [Y/n]: " ans "Y"
            [[ "${ans,,}" == "y" ]] || { info "Отмена."; return; }
        fi
    fi

    systemctl disable --now ${SERVICE_NAME}.service 2>/dev/null || true
    rm -f /etc/systemd/system/${SERVICE_NAME}.service
    rm -f /usr/local/bin/${SERVICE_NAME}
    # Drop-in с кодом первичной установки не должен переживать удаление
    # установки: код открывает мастер создания админа, его время жизни —
    # ровно до первого входа (см. core/setup_code.py).
    rm -rf /etc/systemd/system/${SERVICE_NAME}.service.d
    systemctl daemon-reload

    if $keep_data; then
        TMP=$(mktemp -d)
        # monitor.json — состояние мониторинга (как servers.json, только
        # про проверки); logs/ — журнал установки/работы
        for f in config.json servers.json monitor.json; do
            [[ -e "$INSTALL_DIR/$f" ]] && cp -a "$INSTALL_DIR/$f" "$TMP/"
        done
        for d in data keys scripts backup logs; do
            [[ -d "$INSTALL_DIR/$d" ]] && cp -a "$INSTALL_DIR/$d" "$TMP/"
        done

        rm -rf "$INSTALL_DIR"
        mkdir -p "$INSTALL_DIR"
        # "/." — и обычные, и скрытые файлы
        if [[ -n "$(ls -A "$TMP" 2>/dev/null)" ]]; then
            cp -a "$TMP"/. "$INSTALL_DIR"/
        fi
        rm -rf "$TMP"
        ok "Код и сервис удалены, данные сохранены в $INSTALL_DIR"
        echo "  Остались: config.json, servers.json, monitor.json, data/,"
        echo "  keys/, scripts/, backup/, logs/"
    else
        rm -rf "$INSTALL_DIR"
        ok "Bot4VPS полностью удалён"
    fi
}

# ─────────────────────────────────────────────
# STATUS
# ─────────────────────────────────────────────
do_status() {
    if ! is_installed; then
        echo "Bot4VPS не установлен"
        return
    fi

    cd "$INSTALL_DIR"
    echo -e "${BOLD}Bot4VPS${NC}"
    echo "  Путь:     $INSTALL_DIR"
    echo "  Версия:   $(git rev-parse --short HEAD) ($(git log -1 --format=%s))"
    echo "  Режим:    $(get_mode)"
    echo "  Сервис:   $(systemctl is-active ${SERVICE_NAME}.service 2>/dev/null || echo 'нет юнита')"
    echo

    git fetch --quiet origin 2>/dev/null || true
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse "origin/$BRANCH" 2>/dev/null || echo "$LOCAL")
    if [[ "$LOCAL" == "$REMOTE" ]]; then
        ok "Обновлений нет"
    else
        warn "Доступны обновления ($(git rev-list --count HEAD.."origin/$BRANCH") коммитов)"
        echo "  Запустите: $0 update"
    fi
}

# ─────────────────────────────────────────────
# MENU / CLI
# ─────────────────────────────────────────────
case "${1:-}" in
    install)     do_install ;;
    update)      do_update  ;;
    remove)      do_remove  ;;
    status)      do_status  ;;
    enable-web)  do_enable_web ;;
    *)
        echo
        echo -e "${CYAN}╔══════════════════════════════════════╗${NC}"
        echo -e "${CYAN}║       Bot4VPS Manager                ║${NC}"
        echo -e "${CYAN}╚══════════════════════════════════════╝${NC}"
        echo
        echo "  1) Установить"
        echo "  2) Обновить"
        echo "  3) Статус / проверить обновления"
        echo "  4) Включить Web UI"
        echo "  5) Удалить"
        echo "  0) Выход"
        echo
        ask "Выбор: " choice
        case "$choice" in
            1) do_install ;;
            2) do_update  ;;
            3) do_status  ;;
            4) do_enable_web ;;
            5) do_remove  ;;
            0) exit 0 ;;
            *) err "Неверный выбор"; exit 1 ;;
        esac
        ;;
esac
