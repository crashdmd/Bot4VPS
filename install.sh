#!/bin/bash
# Bot4VPS Manager — install / update / remove / status / enable-web
set -euo pipefail

INSTALL_DIR="/opt/bot4vps"
SERVICE_NAME="bot4vps"
PYTHON="python3"

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

# Runtime reads/writes use the service UID even in the owner-run installer.
app_python() {
    if [[ -d "$INSTALL_DIR/data/runtime" ]]; then
        /usr/sbin/runuser -u bot4vps -- /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME="$INSTALL_DIR" PYTHONPATH="$INSTALL_DIR" PYTHONDONTWRITEBYTECODE=1 "$INSTALL_DIR/venv/bin/python" "$@"
    else
        "$INSTALL_DIR/venv/bin/python" "$@"
    fi
}

is_installed() {
    [[ -f "$INSTALL_DIR/bot.py" ]] && [[ -f "$INSTALL_DIR/core/version.py" ]]
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
    app_python - "$token" "$user_id" <<'PY'
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

# finding №5 (acceptance 5.0.0): при переустановке с уже существующим
# мастер-ключом только что записанные/оставшиеся plaintext-секреты
# (прежде всего bot_token из update_tg_config) сразу шифруются штатным
# механизмом ядра — тем же, что за «Зашифровать все секреты» в UI.
# Первая установка: ключа ещё нет — не усложняем, штатный первичный flow.
encrypt_plaintext_secrets_if_key() {
    local result
    result=$(app_python <<'PY' 2>/dev/null || true
from core import secretbox

if secretbox.master_key_state().get("state") == "ok":
    outcome = secretbox.encrypt_all_plaintext_secrets()
    print("encrypted" if outcome.get("encrypted") else "none")
else:
    print("nokey")
PY
)
    case "$result" in
        encrypted) ok "Найденные секреты зашифрованы мастер-ключом" ;;
        none|nokey|*) ;;
    esac
}

# getMe-проверка токена до признания установки успешной (finding №3).
# stdout: ok | invalid | unreachable. Сетевая недоступность Telegram —
# НЕ повод блокировать установку: unreachable только предупреждает.
# Переспрашиваем токен лишь при явном отказе авторизации.
probe_tg_token() {
    local token="$1"
    app_python - "$token" <<'PY' 2>/dev/null || echo unreachable
import asyncio
import sys

from telegram import Bot
from telegram.error import InvalidToken, NetworkError, TelegramError, TimedOut


async def main() -> str:
    bot = Bot(token=sys.argv[1])
    try:
        # initialize() выполняет реальный getMe
        await asyncio.wait_for(bot.initialize(), timeout=12)
    except InvalidToken:
        return "invalid"
    except (NetworkError, TimedOut, TimeoutError, OSError):
        return "unreachable"
    except TelegramError:
        # прочие ошибки API не доказывают невалидность токена
        return "unreachable"
    try:
        await bot.shutdown()
    except Exception:
        pass
    return "ok"


print(asyncio.run(main()))
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
    if ! "$PYTHON" -c 'from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey' &>/dev/null; then
        install_apt_packages python3-cryptography
        if ! "$PYTHON" -c 'from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey' &>/dev/null; then
            err "Для проверки подписи установите python3-cryptography для $PYTHON."
            return 1
        fi
    fi
}

# BEGIN GENERATED RELEASE BOOTSTRAP
# Source: core/update/release_verify.py + bootstrap.py; tools/build_installer.py
run_install_bootstrap() {
    "$PYTHON" - "$@" <<'B4V_BOOTSTRAP_PY'
import base64, sys, types
verifier = types.ModuleType("release_verify")
sys.modules[verifier.__name__] = verifier
exec(compile(base64.b64decode("IiIi0J/RgNC+0LLQtdGA0LrQsCDQv9C+0LTQv9C40YHQsNC90L3QvtCz0L4g0YDQtdC70LjQt9CwOyDRgtCw0LrQttC1INC60L7Qv9C40YDRg9C10YLRgdGPINGA0Y/QtNC+0Lwg0YHQviBzdGFuZGFsb25lIHJ1bm5lci4KCtCa0LvRjtGHINC00L7QstC10YDQuNGPINCx0LXRgNGR0YLRgdGPINC40Lcg0YPRgdGC0LDQvdC+0LLQu9C10L3QvdC+0LPQviDQutC+0LTQsCwg0L3QuNC60L7Qs9C00LAg0LjQtyDQt9Cw0LPRgNGD0LbQtdC90L3QvtCz0L4g0YDQtdC70LjQt9CwLgrQl9Cw0LrRgNGL0YLRi9C5INC60LvRjtGHINC90YPQttC10L0g0YLQvtC70YzQutC+INC40LfQtNCw0YLQtdC70Y4g0Lgg0L3QtSDQstGF0L7QtNC40YIg0LIg0L/QvtGB0YLQsNCy0LrRgyDQv9GA0LjQu9C+0LbQtdC90LjRjy4KIiIiCmZyb20gX19mdXR1cmVfXyBpbXBvcnQgYW5ub3RhdGlvbnMKCmltcG9ydCBiYXNlNjQKaW1wb3J0IGpzb24KaW1wb3J0IHJlCmltcG9ydCBzeXMKZnJvbSBwYXRobGliIGltcG9ydCBQYXRoCmZyb20gdXJsbGliLnBhcnNlIGltcG9ydCBxdW90ZQoKZnJvbSBjcnlwdG9ncmFwaHkuZXhjZXB0aW9ucyBpbXBvcnQgSW52YWxpZFNpZ25hdHVyZQpmcm9tIGNyeXB0b2dyYXBoeS5oYXptYXQucHJpbWl0aXZlcy5hc3ltbWV0cmljLmVkMjU1MTkgaW1wb3J0IEVkMjU1MTlQdWJsaWNLZXkKClJFUE9TSVRPUlkgPSAiY3Jhc2hkbWQvQm90NFZQUyIKTUFOSUZFU1RfTkFNRSA9ICJCb3Q0VlBTLXVwZGF0ZS5qc29uIgpNQVhfTUFOSUZFU1RfQllURVMgPSAxMjggKiAxMDI0Ck1BWF9BUkNISVZFX0JZVEVTID0gNTEyICogMTAyNCAqIDEwMjQKRE9NQUlOID0gYiJCb3Q0VlBTIHVwZGF0ZSBtYW5pZmVzdCB2MVxuIgpUUlVTVEVEX0tFWVMgPSB7CiAgICAidXBkYXRlLTIwMjYtMTEiOiAiOTQwNDdlZDUyOWNmZWIzN2E3MGRlNjcyM2NmYjkxNDZmMzQ4ZGNlODEzZWNmNDJjNDFjYzA4ZWQwNTM0N2M3NyIsCn0KCgpjbGFzcyBSZWxlYXNlVHJ1c3RFcnJvcihWYWx1ZUVycm9yKToKICAgIHBhc3MKCgpkZWYgY2Fub25pY2FsX3BheWxvYWQocGF5bG9hZDogZGljdCkgLT4gYnl0ZXM6CiAgICByZXR1cm4gRE9NQUlOICsganNvbi5kdW1wcyhwYXlsb2FkLCBlbnN1cmVfYXNjaWk9RmFsc2UsIHNvcnRfa2V5cz1UcnVlLCBzZXBhcmF0b3JzPSgiLCIsICI6IiksIGFsbG93X25hbj1GYWxzZSkuZW5jb2RlKCJ1dGYtOCIpCgoKZGVmIF91bmlxdWVfcGFpcnMocGFpcnMpOgogICAgcmVzdWx0ID0ge30KICAgIGZvciBrZXksIHZhbHVlIGluIHBhaXJzOgogICAgICAgIGlmIGtleSBpbiByZXN1bHQ6CiAgICAgICAgICAgIHJhaXNlIFJlbGVhc2VUcnVzdEVycm9yKCLQntC/0LjRgdCw0L3QuNC1INGA0LXQu9C40LfQsCDRgdC+0LTQtdGA0LbQuNGCINC/0L7QstGC0L7RgNGP0Y7RidC40LXRgdGPINC/0L7Qu9GPIikKICAgICAgICByZXN1bHRba2V5XSA9IHZhbHVlCiAgICByZXR1cm4gcmVzdWx0CgoKZGVmIGRlY29kZV9lbnZlbG9wZShkYXRhOiBieXRlcykgLT4gZGljdDoKICAgIGlmIGxlbihkYXRhKSA+IE1BWF9NQU5JRkVTVF9CWVRFUzoKICAgICAgICByYWlzZSBSZWxlYXNlVHJ1c3RFcnJvcigi0J7Qv9C40YHQsNC90LjQtSDRgNC10LvQuNC30LAg0YHQu9C40YjQutC+0Lwg0LHQvtC70YzRiNC+0LUiKQogICAgdHJ5OgogICAgICAgIHZhbHVlID0ganNvbi5sb2FkcyhkYXRhLCBvYmplY3RfcGFpcnNfaG9vaz1fdW5pcXVlX3BhaXJzKQogICAgZXhjZXB0IChWYWx1ZUVycm9yLCBVbmljb2RlRXJyb3IsIFJlY3Vyc2lvbkVycm9yKSBhcyBlOgogICAgICAgIHJhaXNlIFJlbGVhc2VUcnVzdEVycm9yKCLQndC1INGD0LTQsNC70L7RgdGMINC/0YDQvtGH0LjRgtCw0YLRjCDQv9C+0LTQv9C40YHQsNC90L3QvtC1INC+0L/QuNGB0LDQvdC40LUg0YDQtdC70LjQt9CwIikgZnJvbSBlCiAgICBpZiBub3QgaXNpbnN0YW5jZSh2YWx1ZSwgZGljdCk6CiAgICAgICAgcmFpc2UgUmVsZWFzZVRydXN0RXJyb3IoItCe0LbQuNC00LDQtdGC0YHRjyDQv9C+0LTQv9C40YHQsNC90L3QvtC1INC+0L/QuNGB0LDQvdC40LUg0YDQtdC70LjQt9CwIikKICAgIHJldHVybiB2YWx1ZQoKCmRlZiBub3JtYWxpemVkX3ZlcnNpb24odmFsdWU6IHN0cikgLT4gc3RyOgogICAgaWYgbm90IGlzaW5zdGFuY2UodmFsdWUsIHN0cikgb3Igbm90IHJlLmZ1bGxtYXRjaChyInY/XGQrKD86XC5cZCspezAsMn0iLCB2YWx1ZSk6CiAgICAgICAgcmFpc2UgUmVsZWFzZVRydXN0RXJyb3IoItCd0LXQstC10YDQvdCw0Y8g0LLQtdGA0YHQuNGPINC/0L7QtNC/0LjRgdCw0L3QvdC+0LPQviDRgNC10LvQuNC30LAiKQogICAgcGFydHMgPSB2YWx1ZS5yZW1vdmVwcmVmaXgoInYiKS5zcGxpdCgiLiIpCiAgICByZXR1cm4gIi4iLmpvaW4oc3RyKGludCh4KSkgZm9yIHggaW4gcGFydHMgKyBbIjAiXSAqICgzIC0gbGVuKHBhcnRzKSkpCgoKZGVmIHZlcmlmeV9lbnZlbG9wZShlbnZlbG9wZTogZGljdCwgZXhwZWN0ZWRfdmVyc2lvbjogc3RyIHwgTm9uZSA9IE5vbmUpIC0+IGRpY3Q6CiAgICB0cnk6CiAgICAgICAgaWYgbGVuKGpzb24uZHVtcHMoZW52ZWxvcGUsIGVuc3VyZV9hc2NpaT1GYWxzZSwgYWxsb3dfbmFuPUZhbHNlKS5lbmNvZGUoInV0Zi04IikpID4gTUFYX01BTklGRVNUX0JZVEVTOgogICAgICAgICAgICByYWlzZSBSZWxlYXNlVHJ1c3RFcnJvcigi0J7Qv9C40YHQsNC90LjQtSDRgNC10LvQuNC30LAg0YHQu9C40YjQutC+0Lwg0LHQvtC70YzRiNC+0LUiKQogICAgICAgIGlmIHNldChlbnZlbG9wZSkgIT0geyJrZXlfaWQiLCAicGF5bG9hZCIsICJzaWduYXR1cmUifToKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiRW52ZWxvcGUgZmllbGRzIikKICAgICAgICBwYXlsb2FkID0gZW52ZWxvcGVbInBheWxvYWQiXQogICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKHBheWxvYWQsIGRpY3QpOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJQYXlsb2FkIikKICAgICAgICBlbmNvZGVkX2tleSA9IFRSVVNURURfS0VZUy5nZXQoZW52ZWxvcGVbImtleV9pZCJdKQogICAgICAgIGlmIG5vdCBlbmNvZGVkX2tleToKICAgICAgICAgICAgcmFpc2UgUmVsZWFzZVRydXN0RXJyb3IoItCg0LXQu9C40Lcg0L/QvtC00L/QuNGB0LDQvSDQvdC10LjQt9Cy0LXRgdGC0L3Ri9C8INC60LvRjtGH0L7QvCIpCiAgICAgICAgc2lnbmF0dXJlID0gYmFzZTY0LmI2NGRlY29kZShlbnZlbG9wZVsic2lnbmF0dXJlIl0sIHZhbGlkYXRlPVRydWUpCiAgICAgICAgRWQyNTUxOVB1YmxpY0tleS5mcm9tX3B1YmxpY19ieXRlcyhieXRlcy5mcm9taGV4KGVuY29kZWRfa2V5KSkudmVyaWZ5KHNpZ25hdHVyZSwgY2Fub25pY2FsX3BheWxvYWQocGF5bG9hZCkpCiAgICBleGNlcHQgUmVsZWFzZVRydXN0RXJyb3I6CiAgICAgICAgcmFpc2UKICAgIGV4Y2VwdCAoSW52YWxpZFNpZ25hdHVyZSwgVmFsdWVFcnJvciwgVHlwZUVycm9yLCBLZXlFcnJvciwgUmVjdXJzaW9uRXJyb3IpIGFzIGU6CiAgICAgICAgcmFpc2UgUmVsZWFzZVRydXN0RXJyb3IoItCf0L7QtNC/0LjRgdGMINGA0LXQu9C40LfQsCDQvdC10LTQtdC50YHRgtCy0LjRgtC10LvRjNC90LAuINCj0YHRgtCw0L3QvtCy0LrQsCDQt9Cw0L/RgNC10YnQtdC90LAiKSBmcm9tIGUKCiAgICBpZiAoc2V0KHBheWxvYWQpICE9IHsic2NoZW1hIiwgInJlcG9zaXRvcnkiLCAidmVyc2lvbiIsICJ0YWciLCAiY29tbWl0IiwgImFyY2hpdmUiLCAiY2hhbmdlbG9nIn0KICAgICAgICAgICAgb3IgdHlwZShwYXlsb2FkWyJzY2hlbWEiXSkgaXMgbm90IGludCBvciBwYXlsb2FkWyJzY2hlbWEiXSAhPSAxCiAgICAgICAgICAgIG9yIHBheWxvYWRbInJlcG9zaXRvcnkiXSAhPSBSRVBPU0lUT1JZKToKICAgICAgICByYWlzZSBSZWxlYXNlVHJ1c3RFcnJvcigi0J/QvtC00L/QuNGB0LDQvdC90YvQuSDRgNC10LvQuNC3INC40LzQtdC10YIg0L3QtdC/0L7QtNC00LXRgNC20LjQstCw0LXQvNGL0Lkg0YTQvtGA0LzQsNGCINC40LvQuCDRgNC10L/QvtC30LjRgtC+0YDQuNC5IikKICAgIHZlcnNpb24gPSBub3JtYWxpemVkX3ZlcnNpb24ocGF5bG9hZFsidmVyc2lvbiJdKQogICAgaWYgdmVyc2lvbiAhPSBwYXlsb2FkWyJ2ZXJzaW9uIl0gb3Igbm9ybWFsaXplZF92ZXJzaW9uKHBheWxvYWRbInRhZyJdKSAhPSB2ZXJzaW9uOgogICAgICAgIHJhaXNlIFJlbGVhc2VUcnVzdEVycm9yKCLQktC10YDRgdC40Y8g0Lgg0YLQtdCzINC/0L7QtNC/0LjRgdCw0L3QvdC+0LPQviDRgNC10LvQuNC30LAg0L3QtSDRgdC+0LLQv9Cw0LTQsNGO0YIiKQogICAgaWYgZXhwZWN0ZWRfdmVyc2lvbiBpcyBub3QgTm9uZSBhbmQgdmVyc2lvbiAhPSBub3JtYWxpemVkX3ZlcnNpb24oZXhwZWN0ZWRfdmVyc2lvbik6CiAgICAgICAgcmFpc2UgUmVsZWFzZVRydXN0RXJyb3IoItCf0L7QtNC/0LjRgdCw0L3QvdC+0LUg0L7Qv9C40YHQsNC90LjQtSDQvtGC0L3QvtGB0LjRgtGB0Y8g0Log0LTRgNGD0LPQvtC5INCy0LXRgNGB0LjQuCIpCiAgICBpZiBub3QgaXNpbnN0YW5jZShwYXlsb2FkWyJjb21taXQiXSwgc3RyKSBvciBub3QgcmUuZnVsbG1hdGNoKHIiWzAtOWEtZl17NDB9IiwgcGF5bG9hZFsiY29tbWl0Il0pOgogICAgICAgIHJhaXNlIFJlbGVhc2VUcnVzdEVycm9yKCLQoNC10LvQuNC3INC90LUg0LfQsNC60YDQtdC/0LvRkdC9INC30LAg0LrQvtC90LrRgNC10YLQvdC+0Lkg0YDQtdCy0LjQt9C40LXQuSIpCiAgICBhcmNoaXZlID0gcGF5bG9hZFsiYXJjaGl2ZSJdCiAgICBpZiAobm90IGlzaW5zdGFuY2UoYXJjaGl2ZSwgZGljdCkgb3Igc2V0KGFyY2hpdmUpICE9IHsibmFtZSIsICJzaGEyNTYiLCAic2l6ZSJ9CiAgICAgICAgICAgIG9yIGFyY2hpdmVbIm5hbWUiXSAhPSBmIkJvdDRWUFMte3ZlcnNpb259LnRhci5neiIKICAgICAgICAgICAgb3IgdHlwZShhcmNoaXZlWyJzaXplIl0pIGlzIG5vdCBpbnQgb3Igbm90IDAgPCBhcmNoaXZlWyJzaXplIl0gPD0gTUFYX0FSQ0hJVkVfQllURVMKICAgICAgICAgICAgb3Igbm90IGlzaW5zdGFuY2UoYXJjaGl2ZVsic2hhMjU2Il0sIHN0cikgb3Igbm90IHJlLmZ1bGxtYXRjaChyIlswLTlhLWZdezY0fSIsIGFyY2hpdmVbInNoYTI1NiJdKSk6CiAgICAgICAgcmFpc2UgUmVsZWFzZVRydXN0RXJyb3IoItCd0LXQutC+0YDRgNC10LrRgtC90YvQtSDRgNCw0LfQvNC10YAsINC40LzRjyDQuNC70Lgg0YXQtdGIINC/0L7QtNC/0LjRgdCw0L3QvdC+0LPQviDQsNGA0YXQuNCy0LAiKQogICAgaWYgbm90IGlzaW5zdGFuY2UocGF5bG9hZFsiY2hhbmdlbG9nIl0sIHN0cikgb3IgbGVuKHBheWxvYWRbImNoYW5nZWxvZyJdLmVuY29kZSgidXRmLTgiKSkgPiA2NCAqIDEwMjQ6CiAgICAgICAgcmFpc2UgUmVsZWFzZVRydXN0RXJyb3IoItCd0LXQutC+0YDRgNC10LrRgtC90L7QtSDQvtC/0LjRgdCw0L3QuNC1INC40LfQvNC10L3QtdC90LjQuSDRgNC10LvQuNC30LAiKQogICAgcmV0dXJuIHBheWxvYWQKCgpkZWYgbWFuaWZlc3RfdXJsKHRhZzogc3RyKSAtPiBzdHI6CiAgICBub3JtYWxpemVkX3ZlcnNpb24odGFnKQogICAgcmV0dXJuIGYiaHR0cHM6Ly9naXRodWIuY29tL3tSRVBPU0lUT1JZfS9yZWxlYXNlcy9kb3dubG9hZC97cXVvdGUodGFnLCBzYWZlPScnKX0ve01BTklGRVNUX05BTUV9IgoKCmRlZiBhcmNoaXZlX3VybChwYXlsb2FkOiBkaWN0KSAtPiBzdHI6CiAgICByZXR1cm4gZiJodHRwczovL2dpdGh1Yi5jb20ve1JFUE9TSVRPUll9L3JlbGVhc2VzL2Rvd25sb2FkL3txdW90ZShwYXlsb2FkWyd0YWcnXSwgc2FmZT0nJyl9L3twYXlsb2FkWydhcmNoaXZlJ11bJ25hbWUnXX0iCgoKZGVmIG1haW4oKSAtPiBpbnQ6CiAgICB0cnk6CiAgICAgICAgaWYgbGVuKHN5cy5hcmd2KSAhPSAzOgogICAgICAgICAgICByYWlzZSBSZWxlYXNlVHJ1c3RFcnJvcigi0J3QtSDRg9C60LDQt9Cw0L3RiyDQvtC/0LjRgdCw0L3QuNC1INGA0LXQu9C40LfQsCDQuCDQvtC20LjQtNCw0LXQvNCw0Y8g0LLQtdGA0YHQuNGPIikKICAgICAgICB3aXRoIFBhdGgoc3lzLmFyZ3ZbMV0pLm9wZW4oInJiIikgYXMgc291cmNlOgogICAgICAgICAgICBlbnZlbG9wZSA9IGRlY29kZV9lbnZlbG9wZShzb3VyY2UucmVhZChNQVhfTUFOSUZFU1RfQllURVMgKyAxKSkKICAgICAgICBwYXlsb2FkID0gdmVyaWZ5X2VudmVsb3BlKGVudmVsb3BlLCBzeXMuYXJndlsyXSkKICAgICAgICBwcmludChqc29uLmR1bXBzKHsicGF5bG9hZCI6IHBheWxvYWQsICJhcmNoaXZlX3VybCI6IGFyY2hpdmVfdXJsKHBheWxvYWQpfSwgZW5zdXJlX2FzY2lpPUZhbHNlKSkKICAgICAgICByZXR1cm4gMAogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICBwcmludCgi0J3QtSDRg9C00LDQu9C+0YHRjCDQv9C+0LTRgtCy0LXRgNC00LjRgtGMINC/0L7QtNC70LjQvdC90L7RgdGC0Ywg0YDQtdC70LjQt9CwLiDQo9GB0YLQsNC90L7QstC60LAg0LfQsNC/0YDQtdGJ0LXQvdCwIiwgZmlsZT1zeXMuc3RkZXJyKQogICAgICAgIHJldHVybiAxCgoKaWYgX19uYW1lX18gPT0gIl9fbWFpbl9fIjoKICAgIHJhaXNlIFN5c3RlbUV4aXQobWFpbigpKQo="), "<trusted release verifier>", "exec"), verifier.__dict__)
exec(compile(base64.b64decode("IiIiRnJlc2gtaW5zdGFsbCB2ZXJpZmljYXRpb24sIGVtYmVkZGVkIGluIGluc3RhbGwuc2ggd2l0aCBpdHMgdHJ1c3RlZCB2ZXJpZmllci4KCk9ubHkgc3RhbmRhcmQtbGlicmFyeSBtb2R1bGVzIGFuZCB0aGUgZGlzdHJpYnV0aW9uJ3MgcHl0aG9uMy1jcnlwdG9ncmFwaHkKYXJlIHVzZWQgYmVmb3JlIHRoZSBzaWduZWQgc291cmNlIGFuZCBpdHMgZGVwZW5kZW5jeSBsb2NrIGFyZSB0cnVzdGVkLgoiIiIKZnJvbSBfX2Z1dHVyZV9fIGltcG9ydCBhbm5vdGF0aW9ucwoKaW1wb3J0IGFyZ3BhcnNlCmZyb20gY29udGV4dGxpYiBpbXBvcnQgbnVsbGNvbnRleHQKaW1wb3J0IGhhc2hsaWIKaW1wb3J0IGpzb24KaW1wb3J0IG9zCmltcG9ydCByZQppbXBvcnQgc2h1dGlsCmltcG9ydCBzeXMKaW1wb3J0IHRhcmZpbGUKZnJvbSBwYXRobGliIGltcG9ydCBQYXRoLCBQdXJlUG9zaXhQYXRoCmZyb20gdXJsbGliLnBhcnNlIGltcG9ydCB1cmxzcGxpdApmcm9tIHVybGxpYi5yZXF1ZXN0IGltcG9ydCBIVFRQUmVkaXJlY3RIYW5kbGVyLCBSZXF1ZXN0LCBidWlsZF9vcGVuZXIKCnRyeToKICAgIGZyb20gLiBpbXBvcnQgcmVsZWFzZV92ZXJpZnkgYXMgdHJ1c3QKZXhjZXB0IEltcG9ydEVycm9yOiAgIyBTdGFuZGFsb25lIGluc3RhbGxlcjogdGhlIHRydXN0ZWQgbW9kdWxlIGlzIGVtYmVkZGVkLgogICAgaW1wb3J0IHJlbGVhc2VfdmVyaWZ5IGFzIHRydXN0CgpSRUxFQVNFU19BUEkgPSBmImh0dHBzOi8vYXBpLmdpdGh1Yi5jb20vcmVwb3Mve3RydXN0LlJFUE9TSVRPUll9L3JlbGVhc2VzP3Blcl9wYWdlPTEwMCIKSE9TVFMgPSB7ImdpdGh1Yi5jb20iLCAiYXBpLmdpdGh1Yi5jb20iLCAib2JqZWN0cy5naXRodWJ1c2VyY29udGVudC5jb20iLCAicmVsZWFzZS1hc3NldHMuZ2l0aHVidXNlcmNvbnRlbnQuY29tIn0KUFJJVkFURV9ST09UUyA9IHsiLmdpdCIsICJjb25maWcuanNvbiIsICJzZXJ2ZXJzLmpzb24iLCAibW9uaXRvci5qc29uIiwgImtleXMiLCAiZGF0YSIsICJsb2dzIiwgImJhY2t1cCIsICJ2ZW52IiwgInRlc3RzIiwgIi5sb2NhbC1idWlsZCIsICIubG9jYWwtYXJjaGl2ZXMifQpNQVhfVU5QQUNLRUQgPSAxMDI0ICogMTAyNCAqIDEwMjQKCgpkZWYgY2hlY2tfdXJsKHVybCk6CiAgICBwYXJzZWQgPSB1cmxzcGxpdCh1cmwpCiAgICBpZiAocGFyc2VkLnNjaGVtZSAhPSAiaHR0cHMiIG9yIHBhcnNlZC5ob3N0bmFtZSBub3QgaW4gSE9TVFMgb3IgcGFyc2VkLnBvcnQgbm90IGluIChOb25lLCA0NDMpCiAgICAgICAgICAgIG9yIHBhcnNlZC51c2VybmFtZSBpcyBub3QgTm9uZSBvciBwYXJzZWQucGFzc3dvcmQgaXMgbm90IE5vbmUpOgogICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoItCd0LXQtNC+0L/Rg9GB0YLQuNC80YvQuSDQsNC00YDQtdGBINC30LDQs9GA0YPQt9C60Lgg0YDQtdC70LjQt9CwIikKCgpjbGFzcyBSZWxlYXNlUmVkaXJlY3QoSFRUUFJlZGlyZWN0SGFuZGxlcik6CiAgICBkZWYgcmVkaXJlY3RfcmVxdWVzdChzZWxmLCByZXEsIGZwLCBjb2RlLCBtc2csIGhlYWRlcnMsIG5ld3VybCk6CiAgICAgICAgY2hlY2tfdXJsKG5ld3VybCkKICAgICAgICByZXR1cm4gc3VwZXIoKS5yZWRpcmVjdF9yZXF1ZXN0KHJlcSwgZnAsIGNvZGUsIG1zZywgaGVhZGVycywgbmV3dXJsKQoKCmRlZiBkb3dubG9hZCh1cmw6IHN0ciwgbGltaXQ6IGludCwgZGVzdGluYXRpb246IFBhdGggfCBOb25lID0gTm9uZSkgLT4gYnl0ZXM6CiAgICBjaGVja191cmwodXJsKQogICAgcmVxdWVzdCA9IFJlcXVlc3QodXJsLCBoZWFkZXJzPXsiVXNlci1BZ2VudCI6ICJCb3Q0VlBTIGluc3RhbGxlciIsICJBY2NlcHQiOiAiYXBwbGljYXRpb24vanNvbiIgaWYgZGVzdGluYXRpb24gaXMgTm9uZSBlbHNlICJhcHBsaWNhdGlvbi9vY3RldC1zdHJlYW0ifSkKICAgIG9wZW5lciA9IGJ1aWxkX29wZW5lcihSZWxlYXNlUmVkaXJlY3QoKSkKICAgIHRvdGFsID0gMAogICAgZGF0YSA9IGJ5dGVhcnJheSgpCiAgICB3aXRoIG9wZW5lci5vcGVuKHJlcXVlc3QsIHRpbWVvdXQ9NjApIGFzIHJlc3BvbnNlOgogICAgICAgIGNoZWNrX3VybChyZXNwb25zZS5nZXR1cmwoKSkKICAgICAgICB3aXRoIGRlc3RpbmF0aW9uLm9wZW4oInhiIikgaWYgZGVzdGluYXRpb24gZWxzZSBudWxsY29udGV4dCgpIGFzIHN0cmVhbToKICAgICAgICAgICAgd2hpbGUgYmxvY2sgOj0gcmVzcG9uc2UucmVhZChtaW4oMjU2ICogMTAyNCwgbGltaXQgKyAxIC0gdG90YWwpKToKICAgICAgICAgICAgICAgIHRvdGFsICs9IGxlbihibG9jaykKICAgICAgICAgICAgICAgIGlmIHRvdGFsID4gbGltaXQ6CiAgICAgICAgICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigi0KTQsNC50Lsg0YDQtdC70LjQt9CwINC/0YDQtdCy0YvRiNCw0LXRgiDQtNC+0L/Rg9GB0YLQuNC80YvQuSDRgNCw0LfQvNC10YAiKQogICAgICAgICAgICAgICAgaWYgc3RyZWFtIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIHN0cmVhbS53cml0ZShibG9jaykKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgZGF0YS5leHRlbmQoYmxvY2spCiAgICByZXR1cm4gYnl0ZXMoZGF0YSkKCgpkZWYgbGF0ZXN0X3RhZyhkYXRhOiBieXRlcykgLT4gc3RyOgogICAgcmVsZWFzZXMgPSBqc29uLmxvYWRzKGRhdGEpCiAgICBpZiBub3QgaXNpbnN0YW5jZShyZWxlYXNlcywgbGlzdCk6CiAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigi0J3QtSDRg9C00LDQu9C+0YHRjCDQv9GA0L7Rh9C40YLQsNGC0Ywg0YHQv9C40YHQvtC6INGB0YLQsNCx0LjQu9GM0L3Ri9GFINGA0LXQu9C40LfQvtCyIikKICAgIHRhZ3MgPSBbXQogICAgZm9yIHJlbGVhc2UgaW4gcmVsZWFzZXM6CiAgICAgICAgaWYgbm90IGlzaW5zdGFuY2UocmVsZWFzZSwgZGljdCkgb3IgcmVsZWFzZS5nZXQoImRyYWZ0Iikgb3IgcmVsZWFzZS5nZXQoInByZXJlbGVhc2UiKToKICAgICAgICAgICAgY29udGludWUKICAgICAgICB0YWcgPSByZWxlYXNlLmdldCgidGFnX25hbWUiKQogICAgICAgIHRyeToKICAgICAgICAgICAgdmVyc2lvbiA9IHRydXN0Lm5vcm1hbGl6ZWRfdmVyc2lvbih0YWcpCiAgICAgICAgZXhjZXB0IHRydXN0LlJlbGVhc2VUcnVzdEVycm9yOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIHRhZ3MuYXBwZW5kKCh0dXBsZShtYXAoaW50LCB2ZXJzaW9uLnNwbGl0KCIuIikpKSwgdGFnKSkKICAgIGlmIG5vdCB0YWdzOgogICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoItCd0LXRgiDRgdGC0LDQsdC40LvRjNC90L7Qs9C+INGA0LXQu9C40LfQsCBCb3Q0VlBTLiDQo9GB0YLQsNC90L7QstC60LAg0LjQtyBtYWluINC30LDQv9GA0LXRidC10L3QsCIpCiAgICByZXR1cm4gbWF4KHRhZ3MpWzFdCgoKZGVmIGV4dHJhY3RfdmVyaWZpZWQoYXJjaGl2ZTogUGF0aCwgZGVzdGluYXRpb246IFBhdGgsIHBheWxvYWQ6IGRpY3QpIC0+IFBhdGg6CiAgICBkaWdlc3QgPSBoYXNobGliLnNoYTI1NigpCiAgICB3aXRoIGFyY2hpdmUub3BlbigicmIiKSBhcyBzdHJlYW06CiAgICAgICAgd2hpbGUgYmxvY2sgOj0gc3RyZWFtLnJlYWQoMjU2ICogMTAyNCk6CiAgICAgICAgICAgIGRpZ2VzdC51cGRhdGUoYmxvY2spCiAgICBpZiBhcmNoaXZlLnN0YXQoKS5zdF9zaXplICE9IHBheWxvYWRbImFyY2hpdmUiXVsic2l6ZSJdIG9yIGRpZ2VzdC5oZXhkaWdlc3QoKSAhPSBwYXlsb2FkWyJhcmNoaXZlIl1bInNoYTI1NiJdOgogICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoItCg0LDQt9C80LXRgCDQuNC70LggU0hBMjU2INCw0YDRhdC40LLQsCDQvdC1INGB0L7QstC/0LDQtNCw0LXRgiDRgSDQv9C+0LTQv9C40YHQsNC90L3Ri9C8INGA0LXQu9C40LfQvtC8IikKICAgIHNvdXJjZSA9IGRlc3RpbmF0aW9uIC8gInNvdXJjZSIKICAgIHdpdGggdGFyZmlsZS5vcGVuKGFyY2hpdmUsICJyOmd6IikgYXMgdGFyOgogICAgICAgIGlmIHRhci5wYXhfaGVhZGVycy5nZXQoImNvbW1lbnQiKSAhPSBwYXlsb2FkWyJjb21taXQiXToKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiR2l0LdC60L7QvNC80LjRgiDQsNGA0YXQuNCy0LAg0L3QtSDRgdC+0LLQv9Cw0LTQsNC10YIg0YEg0L/QvtC00L/QuNGB0LDQvdC90YvQvCDRgNC10LvQuNC30L7QvCIpCiAgICAgICAgbWVtYmVycyA9IHRhci5nZXRtZW1iZXJzKCkKICAgICAgICBwcmVmaXggPSBmJ0JvdDRWUFMte3BheWxvYWRbInZlcnNpb24iXX0nCiAgICAgICAgcGF0aHMgPSBzZXQoKQogICAgICAgIHRvdGFsID0gMAogICAgICAgIGZvciBtZW1iZXIgaW4gbWVtYmVyczoKICAgICAgICAgICAgcGF0aCA9IFB1cmVQb3NpeFBhdGgobWVtYmVyLm5hbWUpCiAgICAgICAgICAgIGlmIHBhdGguaXNfYWJzb2x1dGUoKSBvciAiLi4iIGluIHBhdGgucGFydHMgb3Igbm90IHBhdGgucGFydHMgb3IgcGF0aC5wYXJ0c1swXSAhPSBwcmVmaXg6CiAgICAgICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCLQkNGA0YXQuNCyINGB0L7QtNC10YDQttC40YIg0L3QtdC00L7Qv9GD0YHRgtC40LzRi9C5INC/0YPRgtGMIikKICAgICAgICAgICAgaWYgbm90IG1lbWJlci5pc2ZpbGUoKSBhbmQgbm90IG1lbWJlci5pc2RpcigpOgogICAgICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigi0KHRgdGL0LvQutC4INC4INGB0L/QtdGG0LjQsNC70YzQvdGL0LUg0YTQsNC50LvRiyDQsiDQsNGA0YXQuNCy0LUg0LfQsNC/0YDQtdGJ0LXQvdGLIikKICAgICAgICAgICAgaWYgbGVuKHBhdGgucGFydHMpID09IDE6CiAgICAgICAgICAgICAgICBpZiBub3QgbWVtYmVyLmlzZGlyKCk6CiAgICAgICAgICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigi0J3QtdCy0LXRgNC90YvQuSDQutC+0YDQvdC10LLQvtC5INC60LDRgtCw0LvQvtCzINCw0YDRhdC40LLQsCIpCiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICByZWxhdGl2ZSA9IFB1cmVQb3NpeFBhdGgoKnBhdGgucGFydHNbMTpdKQogICAgICAgICAgICBpZiByZWxhdGl2ZS5wYXJ0c1swXSBpbiBQUklWQVRFX1JPT1RTIG9yIHJlbGF0aXZlIGluIHBhdGhzOgogICAgICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigi0JDRgNGF0LjQsiDRgdC+0LTQtdGA0LbQuNGCINGA0LDQsdC+0YfQuNC1INC00LDQvdC90YvQtSDQuNC70Lgg0L/QvtCy0YLQvtGA0Y/RjtGJ0LjQudGB0Y8g0L/Rg9GC0YwiKQogICAgICAgICAgICBwYXRocy5hZGQocmVsYXRpdmUpCiAgICAgICAgICAgIHRvdGFsICs9IG1lbWJlci5zaXplCiAgICAgICAgICAgIGlmIHRvdGFsID4gTUFYX1VOUEFDS0VEOgogICAgICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigi0KDQsNGB0L/QsNC60L7QstCw0L3QvdGL0Lkg0LDRgNGF0LjQsiDRgdC70LjRiNC60L7QvCDQsdC+0LvRjNGI0L7QuSIpCiAgICAgICAgc291cmNlLm1rZGlyKCkKICAgICAgICBmb3IgbWVtYmVyIGluIG1lbWJlcnM6CiAgICAgICAgICAgIHJlbGF0aXZlID0gUHVyZVBvc2l4UGF0aCgqUHVyZVBvc2l4UGF0aChtZW1iZXIubmFtZSkucGFydHNbMTpdKQogICAgICAgICAgICB0YXJnZXQgPSBzb3VyY2UgLyByZWxhdGl2ZQogICAgICAgICAgICBpZiBtZW1iZXIuaXNkaXIoKToKICAgICAgICAgICAgICAgIHRhcmdldC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgIGVsaWYgbWVtYmVyLmlzZmlsZSgpOgogICAgICAgICAgICAgICAgdGFyZ2V0LnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgICAgICB3aXRoIHRhci5leHRyYWN0ZmlsZShtZW1iZXIpIGFzIHN0cmVhbSwgdGFyZ2V0Lm9wZW4oInhiIikgYXMgb3V0OgogICAgICAgICAgICAgICAgICAgIHNodXRpbC5jb3B5ZmlsZW9iaihzdHJlYW0sIG91dCkKICAgICAgICAgICAgICAgIHRhcmdldC5jaG1vZCgwbzc1NSBpZiBtZW1iZXIubW9kZSAmIDBvMTExIGVsc2UgMG82NDQpCiAgICB2ZXJzaW9uX3NvdXJjZSA9IChzb3VyY2UgLyAiY29yZS92ZXJzaW9uLnB5IikucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpCiAgICBtYXRjaCA9IHJlLnNlYXJjaChyJ15BUFBfVkVSU0lPTlxzKj1ccypbXCciXShbXlwnIl0rKVtcJyJdXHMqJCcsIHZlcnNpb25fc291cmNlLCByZS5NVUxUSUxJTkUpCiAgICBpZiBtYXRjaCBpcyBOb25lIG9yIG1hdGNoLmdyb3VwKDEpICE9IHBheWxvYWRbInZlcnNpb24iXSBvciBub3QgKHNvdXJjZSAvICJib3QucHkiKS5pc19maWxlKCk6CiAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigi0JLQtdGA0YHQuNGPINC40LvQuCDRgdC+0YHRgtCw0LIg0LjRgdGF0L7QtNC90LjQutC+0LIg0L3QtSDRgdC+0LLQv9Cw0LTQsNC10YIg0YEg0YDQtdC70LjQt9C+0LwiKQogICAgIyBjb3B5dHJlZSBwcmVzZXJ2ZXMgdGhlc2UgbW9kZXMgd2hlbiBpbnN0YWxsaW5nIHVuZGVyIGEgcHJpdmF0ZSByb290CiAgICAjIHN0YWdpbmcgZGlyZWN0b3J5OyB0aGUgaW5zdGFsbGVkIHNlcnZpY2Ugc3RpbGwgbmVlZHMgdG8gdHJhdmVyc2UgY29kZS4KICAgIGZvciBkaXJlY3RvcnksIF8sIF8gaW4gb3Mud2Fsayhzb3VyY2UpOgogICAgICAgIG9zLmNobW9kKGRpcmVjdG9yeSwgMG83NTUpCiAgICByZXR1cm4gc291cmNlCgoKZGVmIHByZXBhcmUoZGVzdGluYXRpb246IFBhdGgpIC0+IGRpY3Q6CiAgICB0YWcgPSBsYXRlc3RfdGFnKGRvd25sb2FkKFJFTEVBU0VTX0FQSSwgNCAqIDEwMjQgKiAxMDI0KSkKICAgIGVudmVsb3BlID0gdHJ1c3QuZGVjb2RlX2VudmVsb3BlKGRvd25sb2FkKHRydXN0Lm1hbmlmZXN0X3VybCh0YWcpLCB0cnVzdC5NQVhfTUFOSUZFU1RfQllURVMpKQogICAgcGF5bG9hZCA9IHRydXN0LnZlcmlmeV9lbnZlbG9wZShlbnZlbG9wZSwgdGFnKQogICAgaWYgcGF5bG9hZFsidGFnIl0gIT0gdGFnOgogICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoItCf0L7QtNC/0LjRgdGMINC+0YLQvdC+0YHQuNGC0YHRjyDQuiDQtNGA0YPQs9C+0LzRgyDRgtC10LPRgyIpCiAgICBhcmNoaXZlID0gZGVzdGluYXRpb24gLyBwYXlsb2FkWyJhcmNoaXZlIl1bIm5hbWUiXQogICAgZG93bmxvYWQodHJ1c3QuYXJjaGl2ZV91cmwocGF5bG9hZCksIHBheWxvYWRbImFyY2hpdmUiXVsic2l6ZSJdLCBhcmNoaXZlKQogICAgZXh0cmFjdF92ZXJpZmllZChhcmNoaXZlLCBkZXN0aW5hdGlvbiwgcGF5bG9hZCkKICAgIHJldHVybiBwYXlsb2FkCgoKZGVmIGluc3RhbGxfc291cmNlKHNvdXJjZTogUGF0aCwgZGVzdGluYXRpb246IFBhdGgpOgogICAgaWYgZGVzdGluYXRpb24uaXNfc3ltbGluaygpIG9yIChkZXN0aW5hdGlvbi5leGlzdHMoKSBhbmQgbm90IGRlc3RpbmF0aW9uLmlzX2RpcigpKToKICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCLQmtCw0YLQsNC70L7QsyDRg9GB0YLQsNC90L7QstC60Lgg0L3QtSDQtNC+0LvQttC10L0g0LHRi9GC0Ywg0YHRgdGL0LvQutC+0Lkg0LjQu9C4INGE0LDQudC70L7QvCIpCiAgICAjIFZhbGlkYXRlIGV2ZXJ5IGRlc3RpbmF0aW9uIGJlZm9yZSBjb3B5aW5nIGV2ZW4gdGhlIGZpcnN0IHNvdXJjZSBmaWxlLgogICAgZm9yIGVudHJ5IGluIHNvdXJjZS5yZ2xvYigiKiIpOgogICAgICAgIHJlbGF0aXZlID0gZW50cnkucmVsYXRpdmVfdG8oc291cmNlKQogICAgICAgIGlmIHJlbGF0aXZlLnBhcnRzWzBdIGluIFBSSVZBVEVfUk9PVFMgb3IgZW50cnkuaXNfc3ltbGluaygpOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCLQndC10LTQvtC/0YPRgdGC0LjQvNGL0Lkg0YTQsNC50Lsg0YPRgdGC0LDQvdC+0LLQutC4IikKICAgICAgICB0YXJnZXQgPSBkZXN0aW5hdGlvbiAvIHJlbGF0aXZlCiAgICAgICAgZm9yIGNvbXBvbmVudCBpbiAodGFyZ2V0LCAqdGFyZ2V0LnBhcmVudHMpOgogICAgICAgICAgICBpZiBjb21wb25lbnQuaXNfc3ltbGluaygpOgogICAgICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigi0KHRgdGL0LvQutC4INCyINC60LDRgtCw0LvQvtCz0LUg0YPRgdGC0LDQvdC+0LLQutC4INC30LDQv9GA0LXRidC10L3RiyIpCiAgICAgICAgaWYgdGFyZ2V0LmV4aXN0cygpIGFuZCB0YXJnZXQuaXNfZGlyKCkgIT0gZW50cnkuaXNfZGlyKCk6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoItCi0LjQvyDRhNCw0LnQu9CwINCyINC60LDRgtCw0LvQvtCz0LUg0YPRgdGC0LDQvdC+0LLQutC4INC90LUg0YHQvtCy0L/QsNC00LDQtdGCIikKICAgIGRlc3RpbmF0aW9uLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHNodXRpbC5jb3B5dHJlZShzb3VyY2UsIGRlc3RpbmF0aW9uLCBkaXJzX2V4aXN0X29rPVRydWUpCgoKZGVmIG1haW4oKToKICAgIHBhcnNlciA9IGFyZ3BhcnNlLkFyZ3VtZW50UGFyc2VyKCkKICAgIHN1YiA9IHBhcnNlci5hZGRfc3VicGFyc2VycyhkZXN0PSJjb21tYW5kIiwgcmVxdWlyZWQ9VHJ1ZSkKICAgIGZldGNoID0gc3ViLmFkZF9wYXJzZXIoInByZXBhcmUiKQogICAgZmV0Y2guYWRkX2FyZ3VtZW50KCJkZXN0aW5hdGlvbiIsIHR5cGU9UGF0aCkKICAgIGluc3RhbGwgPSBzdWIuYWRkX3BhcnNlcigiaW5zdGFsbCIpCiAgICBpbnN0YWxsLmFkZF9hcmd1bWVudCgic291cmNlIiwgdHlwZT1QYXRoKQogICAgaW5zdGFsbC5hZGRfYXJndW1lbnQoImRlc3RpbmF0aW9uIiwgdHlwZT1QYXRoKQogICAgYXJncyA9IHBhcnNlci5wYXJzZV9hcmdzKCkKICAgIHRyeToKICAgICAgICBpZiBhcmdzLmNvbW1hbmQgPT0gInByZXBhcmUiOgogICAgICAgICAgICBwYXlsb2FkID0gcHJlcGFyZShhcmdzLmRlc3RpbmF0aW9uKQogICAgICAgICAgICBwcmludChmJ9Cf0YDQvtCy0LXRgNC10L0g0YHRgtCw0LHQuNC70YzQvdGL0Lkg0L/QvtC00L/QuNGB0LDQvdC90YvQuSDRgNC10LvQuNC3IHtwYXlsb2FkWyJ2ZXJzaW9uIl19ICh7cGF5bG9hZFsiY29tbWl0Il1bOjEyXX0pJykKICAgICAgICBlbHNlOgogICAgICAgICAgICBpbnN0YWxsX3NvdXJjZShhcmdzLnNvdXJjZSwgYXJncy5kZXN0aW5hdGlvbikKICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXhjOgogICAgICAgIHByaW50KGYi0KPRgdGC0LDQvdC+0LLQutCwINC+0YHRgtCw0L3QvtCy0LvQtdC90LA6IHtleGN9IiwgZmlsZT1zeXMuc3RkZXJyKQogICAgICAgIHJldHVybiAxCiAgICByZXR1cm4gMAoKCmlmIF9fbmFtZV9fID09ICJfX21haW5fXyI6CiAgICByYWlzZSBTeXN0ZW1FeGl0KG1haW4oKSkK"), "<trusted install bootstrap>", "exec"), {"__name__": "__main__", "__package__": None})
B4V_BOOTSTRAP_PY
}
# END GENERATED RELEASE BOOTSTRAP

admin_exists() {
    app_python - <<'PY' 2>/dev/null
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
    app_python <<'PY'
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
ExecStart=${INSTALL_DIR}/venv/bin/python -m uvicorn ui.web.app:app --host 0.0.0.0 --port ${port} --timeout-graceful-shutdown 10${TLS_ARGS:+ ${TLS_ARGS}}
Restart=always
RestartSec=5
TimeoutStopSec=45
KillMode=mixed

[Install]
WantedBy=multi-user.target
EOF
    if [[ -d "$INSTALL_DIR/data/runtime" ]]; then
        "$PYTHON" -I "$INSTALL_DIR/core/migration/privileged/install.py" --no-start
    fi
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
    if [[ -d "$INSTALL_DIR/data/runtime" ]]; then
        "$PYTHON" -I "$INSTALL_DIR/core/migration/privileged/install.py" --no-start
    fi
}

# ─────────────────────────────────────────────
# HTTPS (спросили → выпустили → прописали в юнит)
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
    if "${INSTALL_DIR}/venv/bin/pip" install -q --require-hashes -r "${INSTALL_DIR}/requirements-certbot.txt"; then
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

    if [[ -d "$INSTALL_DIR/data/runtime" ]]; then
        app_python - "$domain" "$email" <<'PY'
import sys
from core.web_tls import run_certbot, copy_le_certificate
ok, stdout, stderr = run_certbot("root-helper", sys.argv[2] or None, sys.argv[1])
if not ok:
    print(stderr or stdout, file=sys.stderr)
    raise SystemExit(1)
copy_le_certificate(sys.argv[1])
PY
        return
    fi

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
    if [[ ! -d "$INSTALL_DIR/data/runtime" ]]; then
        mkdir -p "$WEB_TLS_DIR"
    fi
    if ! app_python "$INSTALL_DIR/core/web_tls.py" --gen-self-signed "$cn"; then
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
    # Режим HTTPS для report_web_status: сообщение о сертификате
    # браузера зависит от происхождения сертификата, не только от схемы.
    WEB_TLS_MODE=""

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
            WEB_TLS_MODE="letsencrypt"
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
            WEB_TLS_MODE="self-signed"
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
            if ! app_python - "$cert_path" "$key_path" <<'PY'
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
            if ! TLS_ARGS=$(app_python <<'PY'
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
            WEB_TLS_MODE="custom"
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
    app_python - "$mode" "$domain" "$cert" "$key" <<'PY'
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

        # >&2: read_web_port вызывается в command substitution
        # (WEB_PORT=$(read_web_port …)) — диагностика не должна
        # попадать в захватываемое значение порта (битый systemd unit).
        warn "Некорректный порт. Укажите целое число от 1 до 65535." >&2
    done
}

# ─────────────────────────────────────────────
# FIREWALL + PORT CHECKS
# ─────────────────────────────────────────────
open_web_port() {
    local port="$1"
    FIREWALL_STATUS="none"

    if [[ -d "$INSTALL_DIR/data/runtime" ]]; then
        FIREWALL_STATUS=$(app_python - "$port" <<'PY'
import sys
from core.local_privileges import request
print(request("firewall.web", port=int(sys.argv[1]), opening=True))
PY
        ) || FIREWALL_STATUS="failed"
        return
    fi

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
    # TLS-режим (letsencrypt|self-signed|custom|proxy|пусто): от него
    # зависит сообщение о сертификате — схема лишь говорит, что панель
    # слушает TLS сама (proxy терминирует HTTPS снаружи, панель — http).
    local tls_mode="${3:-}"
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
            case "$tls_mode" in
                letsencrypt)
                    echo "  Сертификат Let's Encrypt: браузер доверяет ему — предупреждений быть не должно."
                    ;;
                self-signed)
                    echo "  Самоподписанный сертификат: браузер предупредит о нём — это ожидаемо."
                    ;;
                custom)
                    echo "  Свой сертификат: предупреждение браузера зависит от того, выдан ли он доверенным центром."
                    ;;
                *)
                    echo "  Панель работает по HTTPS."
                    ;;
            esac
        elif [[ "$tls_mode" == "proxy" ]]; then
            echo "  Панель за реверс-прокси: HTTPS терминирует прокси —"
            echo "  предупреждения браузера зависят от его сертификата."
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
    pip install --isolated --require-hashes --no-input -q -r requirements.txt

    info "Включаю авторизацию Web UI..."
    setup_web_auth "$WEB_PORT"

    # HTTPS: режим мог быть настроен раньше (config web.tls). Юнит
    # переписывается — TLS-флаги обязаны пережить включение Web.
    WEB_SCHEME="http"
    WEB_TLS_MODE=""
    if ! TLS_PROBE=$(app_python <<'PY'
import sys
from core.config import get_tls_config
from core.web_tls import tls_asset_paths, unit_tls_flags

tls = get_tls_config()
if any(not p.is_file() for p in tls_asset_paths(tls)):
    # Управляемая пара исчезла — юнит со ssl-флагами не стартовал бы.
    print("__MISSING__")
else:
    # Первая строка — режим (для сообщения о сертификате), вторая — флаги
    print(tls.get("mode") or "off")
    print(unit_tls_flags(tls), end="")
PY
); then
        warn "Не удалось прочитать настройки HTTPS — включаю Web без HTTPS."
        echo "  Перевыпустите: bot4vps → Безопасность → HTTPS сертификат."
        TLS_PROBE=""
    fi
    if [[ "$(head -n 1 <<<"$TLS_PROBE")" == "__MISSING__" ]]; then
        warn "Сертификат HTTPS не найден — включаю Web без HTTPS."
        echo "  Перевыпустите: bot4vps → Безопасность → HTTPS сертификат."
        TLS_ARGS=""
    else
        TLS_ARGS="$(tail -n +2 <<<"$TLS_PROBE")"
        if [[ -n "$TLS_ARGS" && "$(head -n 1 <<<"$TLS_PROBE")" == "proxy" ]]; then
            # TLS терминирует прокси: панель слушает плоский HTTP,
            # ssl-флагов в юните нет (только --proxy-headers).
            WEB_TLS_MODE="proxy"
        elif [[ -n "$TLS_ARGS" ]]; then
            WEB_SCHEME="https"
            WEB_TLS_MODE="$(head -n 1 <<<"$TLS_PROBE")"
        fi
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

    report_web_status "$WEB_PORT" "${WEB_SCHEME:-http}" "${WEB_TLS_MODE:-}"
    echo "  Настройки Telegram — в Web UI (Настройки → Telegram)."
    echo "  Токен и allowed_users из config.json используются как есть."
}

# ─────────────────────────────────────────────
# INSTALL
# ─────────────────────────────────────────────
do_install() {
    require_root
    ensure_install_prerequisites

    local reinstall=false
    if is_installed; then
        warn "Bot4VPS уже установлен в $INSTALL_DIR"
        ask "Переустановить? [y/N]: " ans "N"
        [[ "${ans,,}" == "y" ]] || { info "Отмена."; return; }
        reinstall=true
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

    info "Проверяю стабильный подписанный релиз..."
    local install_tmp
    install_tmp=$(mktemp -d)
    if ! run_install_bootstrap prepare "$install_tmp"; then
        rm -rf "$install_tmp"
        return 1
    fi
    if [[ "$reinstall" == true ]]; then
        if ! do_remove --keep-data; then
            rm -rf "$install_tmp"
            return 1
        fi
    fi
    if ! run_install_bootstrap install "$install_tmp/source" "$INSTALL_DIR"; then
        rm -rf "$install_tmp"
        return 1
    fi
    rm -rf "$install_tmp"
    cd "$INSTALL_DIR"

    info "Создаю venv и ставлю зависимости..."
    $PYTHON -m venv venv
    # shellcheck disable=SC1091
    source venv/bin/activate
    pip install -q --upgrade pip
    pip install -q --require-hashes -r requirements.txt
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
            [[ -n "$BOT_TOKEN" && "$BOT_TOKEN" != YOUR_* ]] || { warn "Введите настоящий токен."; continue; }
            # Прежде чем считать установку успешной, Telegram должен
            # принять токен (getMe). Сетевой сбой — не отказ токена.
            case "$(probe_tg_token "$BOT_TOKEN")" in
                ok)
                    break
                    ;;
                invalid)
                    warn "Telegram отклонил этот токен. Проверьте его у @BotFather и введите заново."
                    ;;
                *)
                    warn "Telegram API недоступен — токен проверить не удалось."
                    warn "Продолжаю без проверки: если токен неверен, бот не запустится (см. journalctl -u ${SERVICE_NAME})."
                    break
                    ;;
            esac
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

    # Конфигурация записана: если переустановка с существующим
    # мастер-ключом — сразу шифруем plaintext-секреты (finding №5).
    encrypt_plaintext_secrets_if_key

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

    info "Подготавливаю непривилегированную службу и локального помощника..."
    "$PYTHON" -I "$INSTALL_DIR/core/migration/privileged/install.py" --no-start

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
            report_web_status "$WEB_PORT" "${WEB_SCHEME:-http}" "${WEB_TLS_MODE:-}" || true
        else
            echo "  Web UI:   ${WEB_SCHEME:-http}://$(detect_ip):${WEB_PORT}/"
        fi
        # Данные пережили переустановку, но юнит — источник правды:
        # оставшийся в config HTTPS-режим сам не поднимается.
        if [[ -z "${WEB_TLS_MODE:-}" ]]; then
            local stale_tls stale_label
            stale_tls=$(app_python <<'PY' 2>/dev/null || true
from core.config import get_tls_config
mode = get_tls_config()["mode"]
print(mode if mode != "off" else "", end="")
PY
)
            case "$stale_tls" in
                letsencrypt) stale_label="Let's Encrypt" ;;
                self-signed) stale_label="самоподписанный" ;;
                custom)      stale_label="свой сертификат" ;;
                proxy)       stale_label="за реверс-прокси" ;;
                *)           stale_label="" ;;
            esac
            if [[ -n "$stale_label" ]]; then
                warn "Ранее был настроен HTTPS (${stale_label}) — сейчас панель без него."
                echo "  Включите заново: bot4vps → Безопасность → HTTPS сертификат"
            fi
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

    info "Проверяю подписанные релизы..."
    if [[ ! -f "core/update/release_verify.py" ]]; then
        err "В этой установке нет проверки подписи релизов. Сначала установите версию с поддержкой подписанных обновлений."
        return 1
    fi
    app_python -m core.update
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

    if [[ -d "$INSTALL_DIR/data/runtime" ]]; then
        app_python - "$port" <<'PY'
import sys
from core.local_privileges import request
request("firewall.web", port=int(sys.argv[1]), opening=False)
PY
        return
    fi

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
    systemctl stop bot4vps-helper.service 2>/dev/null || true
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
    echo "  Версия:   $("${INSTALL_DIR}/venv/bin/python" -c 'from core.version import APP_VERSION; print(APP_VERSION)')"
    echo "  Режим:    $(get_mode)"
    echo "  Сервис:   $(systemctl is-active ${SERVICE_NAME}.service 2>/dev/null || echo 'нет юнита')"
    echo

    app_python -m core.update --check || warn "Не удалось проверить подписанные обновления"
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
