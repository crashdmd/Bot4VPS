"""Замена согласованной пары geo-файлов с откатом и защитой от повтора."""
import shlex


def commit_command(bin_directory, download_directory, restart, was_active):
    command = r'''
set -e
bin=@BIN@
download=@DOWNLOAD@
restart=@RESTART@
was_active=@ACTIVE@
lock="$bin/.bot4vps-geo.lock"
mkdir -m 700 -- "$lock" || { echo 'Обновление geo-файлов уже выполняется или требует восстановления. Проверьте .bot4vps-geo.lock в каталоге bin.' >&2; exit 1; }
stage=$(mktemp -d "$bin/.bot4vps-geo-XXXXXXXXXXXX") || { rmdir -- "$lock"; exit 1; }
changed=0
restart_attempted=0
finish() {
    status=$?
    trap - EXIT HUP INT TERM
    set +e
    recovery_failed=0
    if [ "$status" -ne 0 ] && [ "$changed" -eq 1 ]; then
        if [ "$restart_attempted" -eq 1 ]; then systemctl stop x-ui || recovery_failed=1; fi
        for name in geoip.dat geosite.dat; do
            if [ -f "$stage/had-$name" ]; then
                mv -f -- "$stage/$name.old" "$bin/$name" || recovery_failed=1
            else
                rm -f -- "$bin/$name" || recovery_failed=1
            fi
        done
        if [ "$restart_attempted" -eq 1 ] && [ "$was_active" -eq 1 ] && [ "$recovery_failed" -eq 0 ]; then
            systemctl start x-ui && systemctl is-active --quiet x-ui || recovery_failed=1
        fi
    fi
    if [ "$recovery_failed" -ne 0 ]; then
        echo "Не удалось восстановить geo-файлы или работу сервиса. Копии сохранены: $stage; блокировка: $lock. Повторное обновление запрещено до проверки." >&2
        exit 1
    fi
    rm -rf -- "$stage" && rmdir -- "$lock" || { echo "Не удалось очистить временные файлы: $stage; $lock" >&2; exit 1; }
    exit "$status"
}
trap finish EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
for name in geoip.dat geosite.dat; do
    [ ! -L "$bin/$name" ] || { echo "Geo-файл является символической ссылкой: $name" >&2; exit 1; }
    if [ -e "$bin/$name" ]; then
        test -f "$bin/$name"
        cp -p -- "$bin/$name" "$stage/$name.old"
        : > "$stage/had-$name"
        cp -p -- "$bin/$name" "$stage/$name.new"
        cat -- "$download/$name" > "$stage/$name.new"
    else
        install -m 644 -- "$download/$name" "$stage/$name.new"
    fi
done
changed=1
mv -f -- "$stage/geoip.dat.new" "$bin/geoip.dat"
mv -f -- "$stage/geosite.dat.new" "$bin/geosite.dat"
if [ "$restart" -eq 1 ]; then
    restart_attempted=1
    systemctl restart x-ui
    systemctl is-active --quiet x-ui
fi
'''
    return (command.replace('@BIN@', shlex.quote(bin_directory))
            .replace('@DOWNLOAD@', shlex.quote(download_directory))
            .replace('@RESTART@', '1' if restart else '0')
            .replace('@ACTIVE@', '1' if was_active else '0'))
