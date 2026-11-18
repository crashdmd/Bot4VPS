"""Deploy with journalled runtime moves and restoration before reporting failure."""
from __future__ import annotations

import shlex
import uuid

from core.cancel_flags import recovery_scope
from core.integrator import StepError
from . import compose_store


def _runtime_plan(target: str, staged: str, attempt: str) -> str:
    names = ' -o '.join(f'-iname {shlex.quote(name)}' for name in sorted(compose_store.CONFIG_EXCLUDE_DIRS))
    names += " -o -iname '?*_data'"
    script = f'''set -euo pipefail
target={shlex.quote(target)}
staged={shlex.quote(staged)}
attempt={shlex.quote(attempt)}
: > "$attempt/planned"
: > "$attempt/moved"
if [ ! -d "$target" ]; then exit 0; fi
chmod --reference="$target" "$staged"
chown --reference="$target" "$staged"
cd "$target"
find . -mindepth 1 \\( \\( -type d -o -type l \\) \\( {names} \\) \\) -prune -print0 -o ! -type d -print0 > "$attempt/entries"
while IFS= read -r -d '' entry; do
    preserve=0
    if [ -L "$entry" ] || [ ! -f "$entry" ]; then
        preserve=1
    else
        size=$(stat -c %s -- "$entry")
        if [ "$size" -gt {compose_store.CONFIG_MAX_FILE_SIZE} ]; then
            preserve=1
        else
            original=$(head -c {compose_store._CONFIG_BINARY_SNIFF} -- "$entry" | wc -c)
            text=$(head -c {compose_store._CONFIG_BINARY_SNIFF} -- "$entry" | LC_ALL=C tr -d '\\000' | wc -c)
            [ "$original" = "$text" ] || preserve=1
        fi
    fi
    [ "$preserve" = 1 ] || continue
    relative=${{entry#./}}
    destination="$staged/$relative"
    if [ -e "$destination" ] || [ -L "$destination" ]; then
        printf 'Конфигурация проекта пересекается с данными: %s\\n' "$relative" >&2
        exit 1
    fi
    mkdir -p -- "${{destination%/*}}"
    prefix=${{relative%/*}}
    if [ "$prefix" != "$relative" ]; then
        while :; do
            chmod --reference="$target/$prefix" "$staged/$prefix"
            chown --reference="$target/$prefix" "$staged/$prefix"
            parent=${{prefix%/*}}
            [ "$parent" != "$prefix" ] || break
            prefix=$parent
        done
    fi
    source_device=$(stat -c %d -- "$entry")
    destination_device=$(stat -c %d -- "${{destination%/*}}")
    if [ "$source_device" != "$destination_device" ]; then
        printf 'Нельзя безопасно перенести данные с другого файлового раздела: %s\\n' "$relative" >&2
        exit 1
    fi
    printf '%s\\0' "$relative" >> "$attempt/planned"
done < "$attempt/entries"
'''
    return script


def _move_runtime(target: str, staged: str, attempt: str) -> str:
    return f'''set -euo pipefail
while IFS= read -r -d '' relative; do
    printf '%s\\0' "$relative" >> {shlex.quote(attempt + '/moved')}
    mv -T -- {shlex.quote(target)}/"$relative" {shlex.quote(staged)}/"$relative"
done < {shlex.quote(attempt + '/planned')}
'''


def _rollback(target: str, staged: str, backup: str, attempt: str) -> str:
    return f'''set -euo pipefail
target={shlex.quote(target)}
staged={shlex.quote(staged)}
backup={shlex.quote(backup)}
if [ -d "$backup" ]; then
    if [ -e "$target" ] || [ -L "$target" ]; then
        [ ! -e "$staged" ] && [ ! -L "$staged" ]
        mv -T -- "$target" "$staged"
    fi
    mv -T -- "$backup" "$target"
elif [ ! -f {shlex.quote(attempt + '/had_original')} ] && [ ! -e "$staged" ] && [ -d "$target" ]; then
    expected=$(cat {shlex.quote(attempt + '/candidate_identity')})
    actual=$(stat -c '%d:%i' -- "$target")
    [ "$expected" = "$actual" ]
    mv -T -- "$target" "$staged"
fi
if [ -f {shlex.quote(attempt + '/moved')} ]; then
    while IFS= read -r -d '' relative; do
        destination="$target/$relative"
        item="$staged/$relative"
        if [ -e "$item" ] || [ -L "$item" ]; then
            if [ -e "$destination" ] || [ -L "$destination" ]; then
                printf 'Конфликт при восстановлении данных: %s\\n' "$relative" >&2
                exit 1
            fi
            mkdir -p -- "${{destination%/*}}"
            mv -T -- "$item" "$destination"
        elif [ ! -e "$destination" ] && [ ! -L "$destination" ]; then
            printf 'Не найдены данные для восстановления: %s\\n' "$relative" >&2
            exit 1
        fi
    done < {shlex.quote(attempt + '/moved')}
fi
'''


def deploy_atomic(runner, cmd: str, stack: str, files: dict, compose_file: str,
                  target: str, upload, deployment_factory):
    """Keep live bind-mount inodes intact; never erase unfinished attempts."""
    quoted = shlex.quote(target)
    runner.run('deploy_preflight',
        f'''set -e
if [ -L {quoted} ]; then echo 'Рабочий каталог проекта является ссылкой' >&2; exit 1; fi
for previous in {shlex.quote(target + '.deploy-')}*; do
    if [ -e "$previous" ] || [ -L "$previous" ]; then
        printf 'Сохранена незавершённая попытка deploy: %s. Сначала восстановите её данные.\\n' "$previous" >&2
        exit 1
    fi
done
if [ -e {shlex.quote(target + '.old')} ] || [ -L {shlex.quote(target + '.old')} ]; then
    if [ -d {shlex.quote(target + '.old')} ] && [ ! -e {quoted} ] && [ ! -L {quoted} ]; then
        mv -T -- {shlex.quote(target + '.old')} {quoted}
    else
        echo 'Обнаружена прежняя копия проекта {target}.old. Она сохранена; сначала разберите результат предыдущего deploy.' >&2
        exit 1
    fi
fi
if [ -e {shlex.quote(target + '.new')} ] || [ -L {shlex.quote(target + '.new')} ]; then
    echo 'Обнаружен прежний staging {target}.new. Он сохранён; сначала разберите предыдущую попытку.' >&2
    exit 1
fi''', title='Проверка прежних попыток развёртывания')
    attempt = target + '.deploy-' + uuid.uuid4().hex
    staged, backup = attempt + '/candidate', attempt + '/original'
    runner.run('prepare_tmp', f'install -d -m 700 {shlex.quote(attempt)} && '
               f'if [ -d {quoted} ]; then touch {shlex.quote(attempt + "/had_original")}; fi',
               title='Создание закрытого каталога deploy')
    try:
        upload(runner, staged, files)
        runner.run('plan_runtime', _runtime_plan(target, staged, attempt),
                   title='Проверка сохранности данных проекта')
        runner.run('move_runtime', _move_runtime(target, staged, attempt),
                   title='Перенос данных с сохранением файлов живых контейнеров')
        dep = deployment_factory(stack, staged, [staged + '/' + compose_file])
        runner.run('compose_config', f'{cmd} {dep.args()} config -q',
                   title='Проверка полной новой конфигурации проекта')
        runner.run('identify_candidate', f"stat -c '%d:%i' -- {shlex.quote(staged)} > {shlex.quote(attempt + '/candidate_identity')}",
                   title='Проверка подготовленного каталога')
        runner.run('activate',
            f'if [ -d {quoted} ]; then mv -T -- {quoted} {shlex.quote(backup)}; fi && '
            f'mv -T -- {shlex.quote(staged)} {quoted}', title='Активация новой версии проекта')
    except Exception as failure:
        try:
            with recovery_scope():
                runner.run('rollback_deploy', _rollback(target, staged, backup, attempt),
                           title='Восстановление прежнего проекта и данных')
                runner.run('cleanup_failed_deploy', f'rm -rf -- {shlex.quote(attempt)}',
                           title='Очистка неудачной подготовки')
        except Exception as recovery:
            raise StepError('deploy_recovery', -1, title='Развёртывание и восстановление проекта',
                detail=f'Данные и копии сохранены в {attempt}. Восстановление не завершено: {recovery}. Исходная ошибка: {failure}') from failure
        raise
    try:
        with recovery_scope():
            runner.run('cleanup_backup', f'rm -rf -- {shlex.quote(attempt)}',
                       title='Очистка подтверждённой старой конфигурации')
    except Exception:
        runner.emit(f'   [!] Проект обновлён, но прежняя конфигурация сохранена в {attempt}')
