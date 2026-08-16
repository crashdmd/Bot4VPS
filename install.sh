#!/bin/bash
# Bot4VPS Manager — install / update / remove / status / enable-web
set -euo pipefail

REPO="https://github.com/crashdmd/Bot4VPS.git"
INSTALL_DIR="/opt/bot4vps"
SERVICE_NAME="bot4vps"
PYTHON="python3"
BRANCH="main"

# Результат open_web_port: none | ufw | firewalld | nftables | failed
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
ExecStart=${INSTALL_DIR}/venv/bin/python -m uvicorn ui.web.app:app --host 0.0.0.0 --port ${port}
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
# WEB PORT VALIDATION
# ─────────────────────────────────────────────
read_web_port() {
    local default_port="${1:-8080}"
    local input_port

    while true; do
        read -rp "Порт Web UI [${default_port}]: " input_port
        input_port=${input_port:-$default_port}

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
    local port="$1"
    if command -v curl &>/dev/null; then
        curl -fsS --max-time 3 "http://127.0.0.1:${port}/" -o /dev/null 2>/dev/null
        return $?
    fi
    port_is_listening "$port"
}

report_web_status() {
    local port="$1"
    local host_ip
    host_ip=$(detect_ip)

    echo
    local listening=false local_ok=false

    if port_is_listening "$port"; then
        listening=true
    fi
    if web_local_ok "$port"; then
        local_ok=true
    fi

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
        ufw|firewalld|nftables)
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
    echo "  Web UI:   http://${host_ip}:${port}/"
    echo
    if $local_ok; then
        echo -e "${YELLOW}⚠ Web UI запущен на порту ${port}, внешний доступ с этого хоста не подтверждается автоматически.${NC}"
        echo "  Если UI не открывается из браузера — проверьте firewall/security group"
        echo "  у VPS-провайдера и откройте TCP ${port} вручную."
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
    echo "  config.json и данные не изменяются"
    echo

    local WEB_PORT
    WEB_PORT=$(read_web_port 8080)

    open_web_port "$WEB_PORT"

    info "Проверяю зависимости..."
    cd "$INSTALL_DIR"
    # shellcheck disable=SC1091
    source venv/bin/activate
    pip install -q -r requirements.txt

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

    report_web_status "$WEB_PORT"
    echo "  Настройки Telegram — в Web UI (Настройки → Telegram)."
    echo "  Токен и allowed_users из config.json используются как есть."
}

# ─────────────────────────────────────────────
# INSTALL
# ─────────────────────────────────────────────
do_install() {
    require_root

    if is_installed; then
        warn "Bot4VPS уже установлен в $INSTALL_DIR"
        read -rp "Переустановить? [y/N]: " ans
        [[ "${ans,,}" == "y" ]] || { info "Отмена."; return; }
        do_remove --keep-data
    fi

    if ! command -v git &>/dev/null; then
        info "Устанавливаю git..."
        apt-get update -qq && apt-get install -y -qq git
    fi
    if ! command -v "$PYTHON" &>/dev/null; then
        err "Не найден $PYTHON"
        exit 1
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
    read -rp "Ваш выбор [1/2]: " MODE
    MODE=${MODE:-2}

    case "$MODE" in
        1) MODE_NAME="tg-only" ;;
        2) MODE_NAME="web+tg"  ;;
        *) err "Неверный выбор."; exit 1 ;;
    esac

    local WEB_PORT=8080
    if [[ "$MODE_NAME" == "web+tg" ]]; then
        WEB_PORT=$(read_web_port "$WEB_PORT")
        open_web_port "$WEB_PORT"
    fi

    info "Клонирую репозиторий..."
    git clone --depth 1 --branch "$BRANCH" "$REPO" "$INSTALL_DIR"
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

    if [[ "$MODE_NAME" == "tg-only" ]]; then
        echo
        echo -e "${CYAN}── Настройка Telegram ─────────────────${NC}"
        while true; do
            read -rp "Токен бота (от @BotFather): " BOT_TOKEN
            BOT_TOKEN=$(echo "$BOT_TOKEN" | xargs)
            [[ -n "$BOT_TOKEN" && "$BOT_TOKEN" != YOUR_* ]] && break
            warn "Введите настоящий токен."
        done
        while true; do
            read -rp "Ваш Telegram User ID: " USER_ID
            USER_ID=$(echo "$USER_ID" | xargs)
            [[ "$USER_ID" =~ ^[0-9]+$ ]] && break
            warn "Нужно целое число (@userinfobot)."
        done
        update_tg_config "$BOT_TOKEN" "$USER_ID"
        ok "Токен, User ID и telegram_enabled=true записаны в config.json"
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

    read -rp "Запустить сейчас? [Y/n]: " start_now
    start_now=${start_now:-Y}
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

    if [[ "$MODE_NAME" == "web+tg" ]]; then
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then
            report_web_status "$WEB_PORT"
        else
            echo "  Web UI:   http://$(detect_ip):${WEB_PORT}/"
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
    read -rp "Обновить сейчас? [Y/n]: " ans
    ans=${ans:-Y}
    [[ "${ans,,}" == "y" ]] || { info "Отмена."; return; }

    info "Обновляю код..."
    git stash push -u -m "bot4vps-manager-auto" 2>/dev/null || true

    if ! git pull --ff-only origin "$BRANCH"; then
        warn "Fast-forward не удался. Пробую reset --hard..."
        git reset --hard "origin/$BRANCH"
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
        echo "     (сохранить config.json, servers.json, keys/, scripts/, data/, backup/)"
        echo "  2) Удалить всё полностью"
        echo
        read -rp "Ваш выбор [1/2]: " rm_choice
        rm_choice=${rm_choice:-1}
        case "$rm_choice" in
            1) keep_data=true ;;
            2) keep_data=false ;;
            *) err "Неверный выбор."; return ;;
        esac

        if ! $keep_data; then
            warn "Будет удалено безвозвратно:"
            echo "  • $INSTALL_DIR (код + все данные)"
            echo "  • systemd-юнит ${SERVICE_NAME}"
            echo
            read -rp "Точно удалить всё? [y/N]: " ans
            [[ "${ans,,}" == "y" ]] || { info "Отмена."; return; }
        else
            info "Код и сервис будут удалены, пользовательские данные останутся."
            read -rp "Продолжить? [Y/n]: " ans
            ans=${ans:-Y}
            [[ "${ans,,}" == "y" ]] || { info "Отмена."; return; }
        fi
    fi

    systemctl disable --now ${SERVICE_NAME}.service 2>/dev/null || true
    rm -f /etc/systemd/system/${SERVICE_NAME}.service
    systemctl daemon-reload

    if $keep_data; then
        TMP=$(mktemp -d)
        for f in config.json servers.json; do
            [[ -e "$INSTALL_DIR/$f" ]] && cp -a "$INSTALL_DIR/$f" "$TMP/"
        done
        for d in data keys scripts backup; do
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
        echo "  Остались: config.json, servers.json, data/, keys/, scripts/, backup/"
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
        read -rp "Выбор: " choice
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