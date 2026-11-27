#!/bin/sh
# Read the configured local controller. Keep its bearer token in the pipe.
set -eu

yaml_scalar() {
    value=$(sed -n "s/^$1:[[:blank:]]*//p" "$config" | head -n 1 | tr -d '\r')
    case "$value" in
        \"*) value=${value#\"}; value=${value%%\"*} ;;
        \'*) value=${value#\'}; value=${value%%\'*} ;;
        *) value=${value%%[[:blank:]]*} ;;
    esac
    printf '%s' "$value"
}

case "${1:-}" in
    mihomo)
        for config in /opt/clash/config.yaml /etc/mihomo/config.yaml; do
            [ ! -r "$config" ] || break
        done
        [ -r "$config" ] || exit 0
        endpoint=$(yaml_scalar external-controller)
        secret=$(yaml_scalar secret)
        ;;
    sing-box)
        config=/etc/sing-box/config.json
        [ -r "$config" ] && command -v jsonfilter >/dev/null || exit 0
        endpoint=$(jsonfilter -i "$config" -e '@.experimental.clash_api.external_controller' 2>/dev/null || true)
        secret=$(jsonfilter -i "$config" -e '@.experimental.clash_api.secret' 2>/dev/null || true)
        ;;
    *) exit 0 ;;
esac

case "$endpoint" in *:*) ;; *) exit 0 ;; esac
port=${endpoint##*:}
host=${endpoint%:*}
case "$port" in ''|*[!0-9]*) exit 0 ;; esac
[ "${#port}" -le 5 ] && [ "$port" -gt 0 ] && [ "$port" -le 65535 ] || exit 0
case "$host" in
    ''|0.0.0.0|localhost|127.0.0.1) host=127.0.0.1 ;;
    '[::]'|'[::1]') host='[::1]' ;;
    *)
        numeric=${host#\[}
        numeric=${numeric%\]}
        case "$numeric" in ''|*[!0-9A-Fa-f.:]*) exit 0 ;; esac
        ip address show 2>/dev/null | awk -v host="$numeric" '
            $1 == "inet" || $1 == "inet6" {split($2, address, "/"); if (address[1] == host) found=1}
            END {exit !found}
        ' || exit 0
        case "$numeric" in *:*) host="[$numeric]" ;; *) host=$numeric ;; esac
        ;;
esac

[ "${#secret}" -le 512 ] || exit 0
[ "$(printf '%s' "$secret" | tr -d '\r\n')" = "$secret" ] || exit 0
{
    if [ -n "$secret" ]; then printf 'Authorization: Bearer %s\n' "$secret"; fi
} | /usr/bin/curl --disable --noproxy '*' --proto '=http' --globoff --silent --fail \
    --connect-timeout 1 --max-time 1.2 --max-filesize 262144 --header @- \
    "http://$host:$port/connections"
