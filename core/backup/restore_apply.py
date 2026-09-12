"""Подготовка и применение Restore: работа с target по SSH.

Подготовка обязана ответить на два вопроса, которые по одному архиву не решаются:

* что фактически лежит внутри восстанавливаемых корней — иначе «чистое»
  восстановление не может назвать удаляемое до того, как что-то удалит;
* какие из затрагиваемых путей есть на target — защитная копия сохраняет только
  существующее, копировать несуществующий путь нельзя.

Применение — вторая половина модуля: доставка архива на target, удаление
рассчитанного delete-set, распаковка и проверка результата. Разбор вывода и
вычисление delete-set остаются в :mod:`restore_plan`: здесь только команды,
границы и выбор источников.
"""

from __future__ import annotations

import os
import posixpath
import re
import shlex
import tempfile
from pathlib import Path

from .errors import BackupError, ErrorCode
from .models import RESTORE_PLAN_SUMMARY_LIMIT, validate_restore_plan_summary
from .restore_plan import compute_delete_set, parse_inventory_lines, planned_symlink_guard_paths

# Режимы прямо описаны заданием: merge накладывает архив поверх target и ничего
# не удаляет; clean делает выбранный каталог точной копией архива, удаляя лишнее
# строго внутри scope.
RESTORE_MODE_MERGE = "merge"
RESTORE_MODE_CLEAN = "clean"
RESTORE_MODES = (RESTORE_MODE_MERGE, RESTORE_MODE_CLEAN)

# exec_sudo накапливает весь вывод команды в памяти, поэтому инвентаризация
# ограничена явным числом объектов, а не «сколько получится».
MAX_INVENTORY_ENTRIES = 20000

# Каждый источник защитной копии — отдельный remote tar и отдельный staging-файл,
# поэтому список источников ограничен. При превышении копия расширяется до самого
# корня: это надёжнее (сохраняется больше), просто менее точно.
MAX_PROTECTIVE_SOURCES_PER_ROOT = 16
MAX_PROTECTIVE_SOURCES = 24

# Архив доставляется на target одним файлом с именем операции: параллельных
# Restore на одном target быть не может (maintenance permit), а забытый после
# аварии файл видно по operation_id и его снимает следующий preflight.
REMOTE_STAGING_DIR = "/tmp"
REMOTE_ARCHIVE_PREFIX = "restore-"
REMOTE_ARCHIVE_SUFFIX = ".tar.gz"
REMOTE_MEMBER_LIST_SUFFIX = ".members"

# Удаление идёт пакетами: delete-set бывает на тысячи путей, а командная строка
# ограничена. Пакет меньше, чем у проверок наличия: rm получает -rf и цена
# ошибки в нём выше.
DELETE_BATCH = 100

# Опции tar, без которых распаковка Restore не выполняется. Проверяются по
# отдельному полю restore_supports: supports/usable отвечают за создание любого
# серверного backup, и подмешивать сюда их нельзя.
RESTORE_TAR_OPTIONS = {
    "overwrite": "--overwrite",
    "numeric_owner": "--numeric-owner",
    "strip_components": "--strip-components",
    "preserve_permissions": "-p",
    "null": "--null",
    "verbatim_files_from": "--verbatim-files-from",
    "files_from": "--files-from",
    "no_recursion": "--no-recursion",
}


def _precheck(message: str) -> BackupError:
    """Любая непройденная граница — отказ до изменения target."""
    return BackupError(ErrorCode.RESTORE_PRECHECK_FAILED, message)


def _apply_failure(message: str, **details) -> BackupError:
    """Отказ после начала мутации: target уже мог измениться."""
    return BackupError(
        ErrorCode.RESTORE_APPLY_FAILED,
        message,
        details=dict(details) or None,
    )


def _inside(path: str, root: str) -> bool:
    """Строго внутри корня: сам корень не считается своим содержимым."""
    prefix = root.rstrip("/") + "/"
    return path.startswith(prefix)


def normalize_restore_mode(value: object) -> str:
    if value not in RESTORE_MODES:
        raise BackupError(
            ErrorCode.INVALID_REQUEST,
            "Некорректный режим восстановления: ожидается merge или clean",
        )
    return str(value)


def _first_level_child(path: str, root: str) -> str | None:
    """Объект первого уровня внутри root, которому принадлежит path."""
    prefix = root.rstrip("/") + "/"
    if not path.startswith(prefix):
        return None
    head = path[len(prefix):].split("/", 1)[0]
    return prefix + head if head else None


def protective_sources(plan: dict, *, mode: str) -> dict:
    """Какие пути должна содержать защитная копия перед Restore.

    Гранулярность — объекты верхнего уровня внутри корней восстановления.
    ``clean`` берёт корни целиком: внутри scope может быть удалено или заменено
    всё. ``merge`` берёт только те объекты первого уровня, которые архив реально
    заменяет или добавляет: остальное merge не трогает, и сохранять его — значит
    копировать весь профиль сервера, чего требование прямо не допускает.

    Пути, которых на target нет (архив их только добавит), сохранить нельзя;
    их отсеивает :func:`existing_target_paths` по фактическому наличию.
    """
    mode = normalize_restore_mode(mode)
    roots = list(plan.get("roots") or ())
    if not roots:
        raise _precheck("План восстановления не содержит корней")
    if mode == RESTORE_MODE_CLEAN:
        return {"paths": [str(item["root"]) for item in roots], "widened": []}

    entries = list(plan.get("entries") or ())
    paths: list[str] = []
    widened: list[str] = []
    for item in roots:
        root = str(item["root"])
        if item.get("kind") == "file":
            paths.append(root)
            continue
        children: set[str] = set()
        for entry in entries:
            if entry.get("root") != root:
                continue
            child = _first_level_child(str(entry.get("path")), root)
            if child is not None:
                children.add(child)
        if not children or len(children) > MAX_PROTECTIVE_SOURCES_PER_ROOT:
            # Пустой каталог в архиве и слишком широкий корень обрабатываются
            # одинаково: сохраняется сам корень.
            if children:
                widened.append(root)
            paths.append(root)
            continue
        paths.extend(sorted(children))
    if len(paths) > MAX_PROTECTIVE_SOURCES:
        widened = [str(item["root"]) for item in roots]
        paths = list(widened)
    return {"paths": paths, "widened": widened}


def planned_removals(plan: dict, inventory, *, mode: str) -> dict | None:
    """Что Restore удалит на target. ``merge`` не удаляет ничего.

    Для merge возвращается ``None``, а не пустой список: «удалять нечего» и «мы
    ничего не считали, потому что режим не удаляет» — разные утверждения, и в UI
    они выглядят по-разному.
    """
    if normalize_restore_mode(mode) == RESTORE_MODE_MERGE:
        return None
    clean_roots = plan.get("clean_roots")
    if clean_roots is None:
        # Compatibility for physically validated plans created before effective
        # selection existed. New plans always carry an explicit clean scope.
        clean_roots = [item["root"] for item in plan.get("roots") or ()]
    if not clean_roots:
        return {
            "delete": [],
            "delete_all": [],
            "protected": [],
            "outside": [],
            "counts": {
                "delete": 0,
                "delete_all": 0,
                "protected": 0,
                "kept": 0,
            },
        }
    return compute_delete_set(
        inventory=inventory,
        restored_paths=[entry["path"] for entry in plan.get("entries") or ()],
        roots=list(clean_roots),
    )


def restore_plan_summary(
    plan: dict,
    removals: dict | None,
    *,
    mode: str,
    existing,
    limit: int = RESTORE_PLAN_SUMMARY_LIMIT,
) -> dict:
    """Сводка подготовки для пользователя: что запишется, что появится, что удалится.

    Замена и добавление разделены по фактическому состоянию target: путь, который
    на сервере уже есть, будет перезаписан, а путь, которого нет, появится. Без
    этого разделения «будут заменены» обещало бы замену там, где ничего не
    существует. Принадлежность определяется по ``existing`` — множеству
    фактически найденных на target путей, а не по догадке.

    Каталоги ни в один список не попадают: содержимое несут файлы и символьные
    ссылки, а каталог — только контейнер, и в перечне он был бы шумом. Порядок
    замен — порядок членов архива, delete приходит уже отсортированным.

    Списки урезаны до ``limit``: сводка персистится внутри записи Operation, а
    настоящий план бывает на десятки тысяч путей. Полные количества сохраняются
    в ``counts``, поэтому UI может честно сказать «и ещё N», а не молча показать
    неполный список.
    """
    normalized = normalize_restore_mode(mode)
    present = {str(path) for path in existing or ()}
    replace_all: list[str] = []
    add_all: list[str] = []
    for entry in plan.get("entries") or ():
        if entry.get("type") == "directory":
            continue
        path = str(entry["path"])
        (replace_all if path in present else add_all).append(path)
    delete_all = None if removals is None else [str(path) for path in removals.get("delete") or ()]
    summary = {
        "mode": normalized,
        "replace": replace_all[:limit],
        "add": add_all[:limit],
        "delete": None if delete_all is None else delete_all[:limit],
        "counts": {
            "replace": len(replace_all),
            "add": len(add_all),
            "delete": None if delete_all is None else len(delete_all),
        },
        "truncated": {
            "replace": len(replace_all) > limit,
            "add": len(add_all) > limit,
            "delete": delete_all is not None and len(delete_all) > limit,
        },
    }
    return validate_restore_plan_summary(summary)


def _present_paths(
    ssh,
    server: dict,
    paths,
    *,
    exec_sudo,
    failure: BackupError,
    batch: int = 500,
    timeout: int = 120,
) -> set[str]:
    """Какие из путей есть на target. Пакетно, одним ответом на пакет.

    Проверка пакетная: путей в плане бывают тысячи, и отдельная команда на
    каждый путь превратила бы работу в тысячи sudo-вызовов. Полный ``find``
    здесь не подходит — он ограничен числом объектов внутри корней и падает на
    больших каталогах, тогда как вопрос узкий: существует ли конкретный путь.

    ``test -L`` рядом с ``test -e``: битая символьная ссылка не проходит ``-e``,
    но она есть на диске и Restore её заменит.

    ``failure`` передаётся вызывающим: до мутации недоступность target — это
    precheck, после мутации — уже отказ применения, и путать их нельзя.
    """
    items = [str(path) for path in paths or ()]
    present: set[str] = set()
    size = max(1, int(batch))
    for start in range(0, len(items), size):
        chunk = items[start:start + size]
        arguments = " ".join(shlex.quote(path) for path in chunk)
        command = (
            f"for p in {arguments}; do "
            'if [ -e "$p" ] || [ -L "$p" ]; then printf "%s\\n" "$p"; fi; '
            "done"
        )
        code, out, _ = exec_sudo(ssh, server, command, timeout=timeout)
        if code != 0:
            raise failure
        present.update(line for line in out.splitlines() if line)
    return present


def existing_archive_paths(
    ssh,
    server: dict,
    paths,
    *,
    exec_sudo,
    batch: int = 500,
    timeout: int = 120,
) -> set[str]:
    """Какие из путей архива уже есть на target (до применения)."""
    return _present_paths(
        ssh,
        server,
        paths,
        exec_sudo=exec_sudo,
        failure=_precheck(
            "Не удалось проверить состав target: "
            "перечень заменяемых и добавляемых объектов не построен"
        ),
        batch=batch,
        timeout=timeout,
    )


def existing_local_paths(paths) -> set[str]:
    """То же для Bot4VPS: target — сама установка, и SSH здесь не участвует.

    ``lexists`` вместо ``exists``: битая ссылка на диске есть.
    """
    return {str(path) for path in paths or () if os.path.lexists(str(path))}


def existing_target_paths(ssh, server: dict, paths, *, exec_sudo, timeout: int = 60) -> list[str]:
    """Оставить только те пути, которые на target действительно существуют.

    ``test -L`` добавлен рядом с ``test -e``: битая символьная ссылка не проходит
    ``-e``, но она есть на диске и Restore её заменит.
    """
    present: list[str] = []
    for path in paths or ():
        quoted = shlex.quote(str(path))
        code, _, _ = exec_sudo(
            ssh,
            server,
            f"test -e {quoted} || test -L {quoted}",
            timeout=timeout,
        )
        if code == 0:
            present.append(str(path))
    return present


def read_target_inventory(
    ssh,
    server: dict,
    roots,
    *,
    exec_sudo,
    max_entries: int = MAX_INVENTORY_ENTRIES,
    timeout: int = 300,
) -> list[dict]:
    """Фактическое содержимое корней восстановления на target.

    ``head -n`` стоит в самой команде: без него вывод ``find`` целиком попал бы в
    память процесса ещё до любой проверки лимита. Переполнение диагностируется
    раньше кода возврата, потому что при закрытии pipe ``find`` завершается
    сигналом и ``pipefail`` покажет ошибку там, где на деле просто много файлов.
    """
    inventory: list[dict] = []
    limit = int(max_entries)
    if limit < 1:
        raise _precheck("Лимит инвентаризации target должен быть положительным")
    for root in roots or ():
        quoted = shlex.quote(str(root))
        code, _, _ = exec_sudo(
            ssh,
            server,
            f"test -e {quoted} || test -L {quoted}",
            timeout=60,
        )
        if code != 0:
            # Корня на target нет: удалять внутри него нечего, а сам он появится
            # при восстановлении.
            continue
        remaining = limit - len(inventory)
        command = (
            "set -o pipefail; "
            f"find {quoted} -mindepth 1 -printf '%y\\t%s\\t%p\\n' "
            f"| head -n {remaining + 1}"
        )
        code, out, _ = exec_sudo(ssh, server, command, timeout=timeout)
        lines = [line for line in out.splitlines() if line.strip()]
        if len(lines) > remaining:
            raise _precheck(
                "Внутри восстанавливаемых корней слишком много объектов "
                f"(больше {limit}): «чистое» восстановление не выполняется"
            )
        if code != 0:
            raise _precheck(
                "Не удалось прочитать содержимое target: инвентаризация не выполнена"
            )
        inventory.extend(parse_inventory_lines(lines))
    return inventory


# --------------------------------------------------------------------------- #
# Применение
# --------------------------------------------------------------------------- #


def assert_restore_capability(capability: dict) -> None:
    """tar на target обязан уметь ровно то, чем распаковывается архив.

    Проверяется отдельное поле ``restore_supports``: ``supports``/``usable``
    решают, можно ли вообще создавать серверный backup, и любое ужесточение там
    отняло бы у сервера обычные копии.
    """
    capability = capability or {}
    if capability.get("implementation") != "gnu":
        raise _precheck(
            "Для безопасного точного восстановления требуется GNU tar"
        )
    supports = dict(capability.get("restore_supports") or {})
    missing = sorted(
        option
        for key, option in RESTORE_TAR_OPTIONS.items()
        if not supports.get(key)
    )
    if missing:
        raise _precheck(
            "tar на target не поддерживает обязательные для восстановления опции: "
            + ", ".join(missing)
        )


def assert_no_symlink_components(
    ssh,
    server: dict,
    roots,
    *,
    exec_sudo,
    timeout: int = 120,
) -> None:
    """Ни один корень и ни один его родительский компонент — не symlink.

    Распаковка идёт в абсолютные пути: symlink в любом компоненте увёл бы запись
    за пределы объявленного scope, а сам корень-ссылку ``--overwrite`` заменил бы
    каталогом. Проверка одной командой на все корни: путей мало, а отдельный
    sudo-вызов на каждый компонент удлинил бы preflight без пользы.
    """
    items = [posixpath.normpath(str(root)) for root in roots or ()]
    if not items:
        raise _precheck("План восстановления не содержит корней")
    arguments = " ".join(shlex.quote(path) for path in items)
    command = (
        f"for r in {arguments}; do p=\"$r\"; while :; do "
        'if [ -L "$p" ]; then printf "%s\\n" "$p"; fi; '
        'n=$(dirname "$p"); '
        'if [ "$n" = "$p" ] || [ "$n" = "/" ]; then break; fi; p="$n"; '
        "done; done"
    )
    code, out, _ = exec_sudo(ssh, server, command, timeout=timeout)
    if code != 0:
        raise _precheck(
            "Не удалось проверить пути восстановления на target: "
            "восстановление не начато"
        )
    found = [line for line in out.splitlines() if line]
    if found:
        raise _precheck(
            "Восстановление не выполняется: путь содержит символьную ссылку — "
            + ", ".join(sorted(set(found))[:5])
        )


def assert_no_symlink_ancestors(
    ssh,
    server: dict,
    plan: dict,
    *,
    exec_sudo,
    batch: int = 500,
    timeout: int = 120,
) -> None:
    """Внутри корня ни один промежуточный компонент пути не может быть symlink.

    Проверено на GNU tar 1.35: ссылку, которую распаковка создала сама, tar
    отслеживает и писать внутрь неё отказывается, а ссылку, которая УЖЕ лежала на
    диске, проходит насквозь — запись уходит за пределы корня, код возврата 0, ни
    одного предупреждения. Ни ``--overwrite``, ни ``--unlink-first`` этого не
    меняют: они действуют на последний компонент имени, а не на промежуточные.

    Отказ безусловный и не смотрит, есть ли в архиве запись каталога для этого
    компонента. Такая запись действительно заменяет ссылку настоящим каталогом,
    но только если пришла РАНЬШЕ своих детей, а порядок членов задаёт сам архив —
    у импортированного он произвольный. Безопасность восстановления не может
    зависеть от порядка записей в чужом файле.

    ``assert_no_symlink_components`` отвечает за корни и их родителей; здесь —
    только то, что лежит строго внутри корней.
    """
    paths = planned_symlink_guard_paths(plan)
    if not paths:
        return
    found: list[str] = []
    size = max(1, int(batch))
    for start in range(0, len(paths), size):
        chunk = paths[start:start + size]
        arguments = " ".join(shlex.quote(path) for path in chunk)
        command = (
            f"for p in {arguments}; do "
            'if [ -L "$p" ]; then printf "%s\\n" "$p"; fi; '
            "done"
        )
        code, out, _ = exec_sudo(ssh, server, command, timeout=timeout)
        if code != 0:
            raise _precheck(
                "Не удалось проверить промежуточные каталоги внутри "
                "восстанавливаемых корней: восстановление не начато"
            )
        found.extend(line for line in out.splitlines() if line)
    if found:
        raise _precheck(
            "Восстановление не выполняется: внутри восстанавливаемого корня "
            "промежуточный каталог оказался символьной ссылкой — "
            + ", ".join(sorted(set(found))[:5])
        )


def free_space_bytes(ssh, server: dict, path: str, *, exec_sudo, timeout: int = 60) -> int:
    """Свободное место файловой системы, в которой окажется ``path``.

    Если самого пути ещё нет, замер идёт по ближайшему существующему родителю:
    именно он определяет файловую систему, куда tar будет писать. ``df -Pk``
    (POSIX-формат) гарантирует одну строку на файловую систему — без него длинное
    имя устройства переносится на вторую строку и разбор ломается.
    """
    quoted = shlex.quote(str(path))
    command = (
        f'p={quoted}; '
        'while [ ! -e "$p" ]; do n=$(dirname "$p"); '
        'if [ "$n" = "$p" ]; then break; fi; p="$n"; done; '
        'df -Pk "$p" | tail -n 1'
    )
    code, out, _ = exec_sudo(ssh, server, command, timeout=timeout)
    line = out.strip().splitlines()[-1] if out.strip() else ""
    fields = line.split()
    if code != 0 or len(fields) < 4:
        raise _precheck(
            f"Не удалось измерить свободное место на target для {path}"
        )
    try:
        available = int(fields[3])
    except (TypeError, ValueError):
        raise _precheck(
            f"Не удалось измерить свободное место на target для {path}"
        ) from None
    return available * 1024


def restore_space_requirements(plan: dict, *, archive_bytes: int) -> list[tuple[str, int]]:
    """Где и сколько места нужно: сами корни плюс каталог доставки архива.

    Требование по корню — распакованный объём его членов. Это заведомая оценка
    сверху: перезапись существующего файла место почти не занимает. Занижать
    нельзя — отказ по месту до мутации дешевле, чем оборванная распаковка.
    """
    requirements: list[tuple[str, int]] = [
        (str(item["root"]), int(item.get("bytes") or 0))
        for item in plan.get("roots") or ()
    ]
    requirements.append((REMOTE_STAGING_DIR, int(archive_bytes)))
    return requirements


def assert_free_space(ssh, server: dict, requirements, *, exec_sudo) -> dict:
    """Проверить свободное место по каждому требованию до начала мутации."""
    measured: dict[str, int] = {}
    for path, needed in requirements or ():
        available = free_space_bytes(ssh, server, path, exec_sudo=exec_sudo)
        measured[str(path)] = available
        if available < int(needed):
            raise _precheck(
                f"На target недостаточно свободного места для {path}: "
                f"нужно ~{int(needed) // (1024 * 1024)} МиБ, "
                f"доступно {available // (1024 * 1024)} МиБ"
            )
    return measured


def remote_archive_path(operation_id: str) -> str:
    """Куда кладётся архив на target. Имя однозначно связано с операцией."""
    name = f"{REMOTE_ARCHIVE_PREFIX}{operation_id}{REMOTE_ARCHIVE_SUFFIX}"
    return posixpath.join(REMOTE_STAGING_DIR, name)


def remote_member_list_path(operation_id: str) -> str:
    """Operation-scoped path for the trusted exact TAR member allowlist."""
    name = f"{REMOTE_ARCHIVE_PREFIX}{operation_id}{REMOTE_MEMBER_LIST_SUFFIX}"
    return posixpath.join(REMOTE_STAGING_DIR, name)


def restore_member_list_bytes(plan: dict) -> bytes:
    """Serialize only validated backend plan member names, in TAR order."""
    entries = plan.get("entries") if isinstance(plan, dict) else None
    if not isinstance(entries, list) or not entries:
        raise _precheck("Effective Restore plan не содержит TAR members")
    names: list[bytes] = []
    seen: set[str] = set()
    for entry in entries:
        name = entry.get("name") if isinstance(entry, dict) else None
        if (
            not isinstance(name, str)
            or not name
            or "\x00" in name
            or "\\" in name
            or name.startswith("/")
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or posixpath.normpath(name) != name
            or name in seen
        ):
            raise _precheck("Effective Restore plan содержит некорректный TAR member")
        try:
            encoded = name.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise _precheck(
                "Имя TAR member невозможно передать в exact allowlist"
            ) from exc
        seen.add(name)
        names.append(encoded)
    return b"\x00".join(names) + b"\x00"


def create_restore_member_list(
    plan: dict,
    operation_id: str,
    *,
    directory: str | Path | None = None,
) -> tuple[Path, int]:
    """Create a private local exact allowlist and return its path and size."""
    data = restore_member_list_bytes(plan)
    prefix = f"restore-{operation_id}-"
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=prefix,
            suffix=REMOTE_MEMBER_LIST_SUFFIX,
            dir=None if directory is None else str(directory),
            delete=False,
        ) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            path = Path(stream.name)
        path.chmod(0o600)
    except OSError as exc:
        raise BackupError(
            ErrorCode.STAGING_IO_FAILED,
            "Не удалось создать trusted member list: восстановление не начато",
        ) from exc
    return path, len(data)


def clear_stale_remote_archives(ssh, server: dict, *, exec_sudo, timeout: int = 60) -> bool:
    """Снять с target архивы прошлых Restore.

    Параллельных Restore на одном target нет (maintenance permit сериализует их),
    поэтому найденный файл — след аварийно прерванной операции. Ошибка уборки не
    останавливает восстановление: это гигиена, а не граница.
    """
    # Шаблон намеренно не в кавычках: раскрыть его обязана оболочка target, а
    # shlex.quote превратил бы его в имя файла с литеральной звёздочкой. Все
    # части строки — константы модуля, пользовательских данных в ней нет.
    patterns = [
        posixpath.join(
            REMOTE_STAGING_DIR,
            f"{REMOTE_ARCHIVE_PREFIX}*{suffix}",
        )
        for suffix in (REMOTE_ARCHIVE_SUFFIX, REMOTE_MEMBER_LIST_SUFFIX)
    ]
    try:
        code, _, _ = exec_sudo(
            ssh,
            server,
            "rm -f " + " ".join(patterns),
            timeout=timeout,
        )
    except Exception:
        return False
    return code == 0


def discard_remote_archive(ssh, server: dict, remote_path: str, *, exec_sudo, timeout: int = 60) -> bool:
    """Убрать доставленный архив. Best-effort: данные target уже восстановлены."""
    return discard_remote_restore_inputs(
        ssh,
        server,
        [remote_path],
        exec_sudo=exec_sudo,
        timeout=timeout,
    )


def discard_remote_restore_inputs(
    ssh,
    server: dict,
    remote_paths,
    *,
    exec_sudo,
    timeout: int = 60,
) -> bool:
    """Best-effort cleanup of the uploaded archive and trusted member list."""
    paths = [str(path) for path in remote_paths or () if path]
    if not paths:
        return True
    try:
        code, _, _ = exec_sudo(
            ssh,
            server,
            "rm -f -- " + " ".join(shlex.quote(path) for path in paths),
            timeout=timeout,
        )
    except Exception:
        return False
    return code == 0


def _upload_restore_input(
    ssh,
    local_path,
    remote_path: str,
    *,
    description: str,
    progress_cb=None,
) -> int:
    local = Path(local_path)
    try:
        size = local.stat().st_size
        with ssh.open_sftp() as sftp:
            callback = None
            if progress_cb is not None:
                def callback(transferred, total):  # noqa: E306 - локальный колбэк SFTP
                    try:
                        progress_cb(int(transferred), int(total or size))
                    except Exception:
                        pass
            sftp.put(str(local), str(remote_path), callback=callback)
            delivered = int(sftp.stat(str(remote_path)).st_size)
            try:
                sftp.chmod(str(remote_path), 0o600)
            except (AttributeError, OSError):
                pass
    except Exception as exc:
        raise BackupError(
            ErrorCode.SFTP_FAILED,
            f"Не удалось передать {description} на target: восстановление не начато",
            retryable=True,
        ) from exc
    if delivered != int(size):
        raise BackupError(
            ErrorCode.SFTP_FAILED,
            f"{description.capitalize()} передан на target не полностью: восстановление не начато",
            retryable=True,
        )
    return size


def upload_restore_archive(ssh, archive_path, remote_path: str, *, progress_cb=None) -> int:
    """Положить опубликованный архив на target одним файлом.

    Не поток «tar -x прямо из канала»: распаковка обязана начинаться, когда весь
    архив уже на сервере. Иначе обрыв соединения оставлял бы target изменённым
    наполовину при полностью пройденных precheck — а самая вероятная ошибка всей
    операции именно передача. Здесь она случается ДО mutation boundary.

    Размер сверяется после передачи: молча укороченный архив дал бы распаковке
    «неожиданный конец файла» уже после начала мутации.
    """
    return _upload_restore_input(
        ssh,
        archive_path,
        remote_path,
        description="архив",
        progress_cb=progress_cb,
    )


def upload_restore_member_list(ssh, list_path, remote_path: str) -> int:
    """Upload and size-verify the backend-generated exact member allowlist."""
    return _upload_restore_input(
        ssh,
        list_path,
        remote_path,
        description="trusted member list",
    )


def delete_target_paths(
    ssh,
    server: dict,
    paths,
    *,
    roots,
    exec_sudo,
    batch: int = DELETE_BATCH,
    timeout: int = 600,
    progress_cb=None,
) -> int:
    """Удалить ровно рассчитанный delete-set — и ничего кроме него.

    Транспорт повторяет границы расчёта, а не доверяет им: корень восстановления
    не удаляется никогда, путь вне корней не удаляется никогда. Расчёт и
    применение разделены во времени (между ними защитная копия), и вторая
    проверка стоит один проход по списку.
    """
    normalized_roots = [posixpath.normpath(str(root)) for root in roots or ()]
    if not normalized_roots:
        raise _apply_failure("Удаление без корней восстановления невозможно")
    items: list[str] = []
    for raw in paths or ():
        path = posixpath.normpath(str(raw))
        if not path.startswith("/") or "\x00" in path:
            raise _apply_failure(f"Некорректный путь удаления: {raw}")
        if path in normalized_roots:
            raise _apply_failure(
                f"Корень восстановления не удаляется: {path}"
            )
        if not any(_inside(path, root) for root in normalized_roots):
            raise _apply_failure(
                f"Путь удаления вне восстанавливаемых корней: {path}"
            )
        items.append(path)
    removed = 0
    size = max(1, int(batch))
    for start in range(0, len(items), size):
        chunk = items[start:start + size]
        arguments = " ".join(shlex.quote(path) for path in chunk)
        code, _, _ = exec_sudo(ssh, server, f"rm -rf -- {arguments}", timeout=timeout)
        if code != 0:
            raise _apply_failure(
                "Не удалось удалить объекты внутри восстанавливаемых корней",
                phase="delete",
                removed=removed,
                planned=len(items),
            )
        removed += len(chunk)
        if progress_cb is not None:
            try:
                progress_cb(removed, len(items))
            except Exception:
                pass
    return removed


_TAR_ETXTBSY = re.compile(
    r"^tar: (?P<member>.+): Cannot open: Text file busy$"
)
_TAR_ETXTBSY_TRAILER = "tar: Exiting with failure status due to previous errors"
_MAX_TAR_DIAGNOSTICS = 256
_MAX_TAR_DIAGNOSTIC_LENGTH = 4096
_MAX_PREFLIGHT_PROCESSES = 10000
_MAX_PREFLIGHT_MATCHES = 1000
_MAX_PREFLIGHT_OUTPUT = 8 * 1024 * 1024
_PREFLIGHT_SCAN_MARKER = "__BOT4VPS_PROC_SCAN__"
_PREFLIGHT_RACE_DISCLAIMER = (
    "Это снимок состояния: target может измениться до extraction"
)


def _normalize_proc_executable(value: object) -> str | None:
    """Normalize one readlink value without treating stderr as trusted input."""
    if not isinstance(value, str) or "\x00" in value:
        return None
    value = value.removesuffix(" (deleted)")
    if not value.startswith("/"):
        return None
    normalized = posixpath.normpath(value)
    if normalized in {"", ".", "/"} or "\x00" in normalized:
        return None
    return normalized


def _preflight_result(
    *,
    status: str,
    complete: bool,
    scanned: int,
    candidate_count: int,
    matches: list[dict],
    match_count: int | None = None,
    diagnostic: str | None = None,
    truncated: bool = False,
) -> dict:
    """Build a bounded, explicit advisory projection."""
    stored = list(matches[:_MAX_PREFLIGHT_MATCHES])
    total = len(stored) if match_count is None else max(len(stored), int(match_count))
    return {
        "status": status,
        "complete": bool(complete),
        "truncated": bool(truncated),
        "scanned": max(0, min(int(scanned), _MAX_PREFLIGHT_PROCESSES)),
        "candidate_count": max(0, min(int(candidate_count), _MAX_PREFLIGHT_PROCESSES)),
        "match_count": max(0, min(total, _MAX_PREFLIGHT_OUTPUT)),
        "stored_match_count": len(stored),
        "matches": stored,
        "diagnostic": (str(diagnostic)[:512] if diagnostic else None),
    }


def _tar_entry_aliases(entry: dict) -> set[str]:
    """Return only names that the already validated plan can represent.

    GNU tar diagnostics are normally printed after ``--strip-components`` and
    therefore use the path without the archive's leading payload component.  A
    few tar versions print the archive name instead, so the validated archive
    name is accepted too.  No path supplied by stderr is ever added to the
    trusted set.
    """
    name = posixpath.normpath(str(entry.get("name") or ""))
    path = posixpath.normpath(str(entry.get("path") or ""))
    aliases = {name, path.lstrip("/")}
    if name.startswith("payload/"):
        aliases.add(name[len("payload/"):])
    return {item for item in aliases if item and item not in {".", "/"}}


def preflight_restore_processes(
    ssh,
    server: dict,
    *,
    plan: dict,
    exec_sudo,
    limit: int = 100,
    timeout: int = 120,
) -> dict:
    """Read-only advisory scan of processes whose executable is in the plan.

    Deliberately inspects only ``/proc/<pid>/exe``.  Ordinary open data files,
    including files visible through ``/proc/<pid>/fd``, are not conflicts.  The
    scan is bounded and reports truncation rather than presenting a partial
    result as complete.
    """
    try:
        stored_limit = max(1, min(int(limit), _MAX_PREFLIGHT_MATCHES))
    except (TypeError, ValueError):
        stored_limit = 100
    candidates = {
        normalized
        for entry in plan.get("entries") or ()
        if entry.get("type") in {"file", "hardlink"}
        for normalized in [_normalize_proc_executable(entry.get("path"))]
        if normalized is not None
    }
    # The command only reads procfs and emits a bounded marker.  In particular,
    # it never follows /proc/*/fd and contains no process-control operation.
    command = (
        "scanned=0; truncated=0; for proc in /proc/[0-9]*; do "
        "[ -d \"$proc\" ] || continue; "
        "if [ $scanned -ge 10000 ]; then truncated=1; break; fi; "
        "pid=${proc##*/}; "
        "exe=$(readlink -- \"$proc/exe\" 2>/dev/null) || { scanned=$((scanned+1)); continue; }; "
        "comm=$(cat \"$proc/comm\" 2>/dev/null | tr '\\t\\n' '  '); "
        "printf '%s\\t%s\\t%s\\n' \"$pid\" \"$exe\" \"$comm\"; "
        "scanned=$((scanned+1)); done; "
        f"printf '{_PREFLIGHT_SCAN_MARKER}\\t%s\\t%s\\n' \"$scanned\" \"$truncated\""
    )
    code, out, err = exec_sudo(ssh, server, command, timeout=timeout)
    if code != 0:
        return _preflight_result(
            status="unavailable",
            complete=False,
            scanned=0,
            candidate_count=len(candidates),
            matches=[],
            diagnostic=(err or "").strip() or "Команда /proc preflight недоступна",
        )
    text = "" if out is None else str(out)
    if len(text) > _MAX_PREFLIGHT_OUTPUT:
        return _preflight_result(
            status="malformed",
            complete=False,
            scanned=0,
            candidate_count=len(candidates),
            matches=[],
            diagnostic="Слишком большой ответ /proc preflight",
        )
    lines = text.splitlines()
    metadata = None
    data_lines: list[str] = []
    malformed = False
    for line in lines:
        if "\x00" in line or "\r" in line or len(line) > 4096:
            malformed = True
            continue
        if line.startswith(_PREFLIGHT_SCAN_MARKER + "\t"):
            if metadata is not None:
                malformed = True
            else:
                metadata = line.split("\t")
            continue
        data_lines.append(line)
    if (
        metadata is None
        or len(metadata) != 3
        or metadata[0] != _PREFLIGHT_SCAN_MARKER
        or not metadata[1].isdigit()
        or metadata[2] not in {"0", "1"}
    ):
        malformed = True
    scanned = 0
    truncated = False
    if metadata is not None and len(metadata) == 3 and metadata[1].isdigit():
        scanned = int(metadata[1])
        truncated = metadata[2] == "1"
        if scanned > _MAX_PREFLIGHT_PROCESSES:
            malformed = True
            scanned = _MAX_PREFLIGHT_PROCESSES
    matches: list[dict] = []
    total_matches = 0
    seen: set[tuple[int, str]] = set()
    for line in data_lines:
        fields = line.split("\t", 2)
        if len(fields) != 3 or not fields[0].isdigit():
            malformed = True
            continue
        try:
            pid = int(fields[0])
        except ValueError:
            malformed = True
            continue
        if pid <= 0:
            malformed = True
            continue
        executable = _normalize_proc_executable(fields[1])
        if executable is None:
            malformed = True
            continue
        if executable not in candidates:
            continue
        key = (pid, executable)
        if key in seen:
            continue
        seen.add(key)
        total_matches += 1
        if len(matches) < stored_limit:
            matches.append({
                "pid": pid,
                "path": executable,
                "process": fields[2].strip()[:256] or None,
            })
    if metadata is not None and scanned < len(data_lines):
        malformed = True
    status = "malformed" if malformed else ("truncated" if truncated else "complete")
    return _preflight_result(
        status=status,
        complete=not malformed and not truncated,
        truncated=truncated,
        scanned=scanned,
        candidate_count=len(candidates),
        matches=matches,
        match_count=total_matches,
        diagnostic=None if not malformed else "Некорректный ответ /proc preflight",
    )


PREFLIGHT_RACE_DISCLAIMER = _PREFLIGHT_RACE_DISCLAIMER


def classify_restore_tar_diagnostics(
    exit_code: int,
    stderr: str | None,
    *,
    plan: dict,
) -> dict:
    """Classify one complete GNU tar result without relaxing archive safety.

    Partial success is deliberately narrow: every diagnostic must be the exact
    GNU ``Text file busy`` member error and each member must resolve uniquely to
    a validated regular-file plan entry.  The aggregate GNU trailer is the only
    additional line accepted.  Returning a structured result lets the caller
    verify every member tar did not report as skipped.
    """
    status = int(exit_code)
    # Transport uses negative values when no trustworthy remote exit status is
    # available.  Stderr cannot turn an unknown execution result into success.
    if status < 0 or status > 255:
        return {"ok": False, "reason": "unknown_exit_status", "diagnostics": []}

    text = "" if stderr is None else str(stderr)
    if len(text) > _MAX_TAR_DIAGNOSTICS * _MAX_TAR_DIAGNOSTIC_LENGTH:
        return {"ok": False, "reason": "diagnostics_truncated", "diagnostics": []}
    raw_lines = text.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines.pop()
    if any("\r" in line or len(line) > _MAX_TAR_DIAGNOSTIC_LENGTH for line in raw_lines):
        return {"ok": False, "reason": "malformed_diagnostic", "diagnostics": []}
    if len(raw_lines) > _MAX_TAR_DIAGNOSTICS:
        return {"ok": False, "reason": "too_many_diagnostics", "diagnostics": []}
    if status == 0:
        if raw_lines:
            return {"ok": False, "reason": "diagnostic_with_success_exit", "diagnostics": raw_lines[:8]}
        return {"ok": True, "skipped": [], "diagnostics": []}
    if not raw_lines:
        return {"ok": False, "reason": "missing_diagnostics", "diagnostics": []}

    members: list[str] = []
    diagnostics: list[str] = []
    for line in raw_lines:
        match = _TAR_ETXTBSY.fullmatch(line)
        if match:
            member = match.group("member")
            # Do not normalize untrusted stderr into a trusted archive member:
            # traversal, empty components and backslashes are fatal even when
            # normpath would happen to land on a validated destination.
            parts = member.split("/") if member else []
            if (
                not member
                or "\x00" in member
                or "\\" in member
                or member.startswith("/")
                or any(part in {"", ".", ".."} for part in parts)
            ):
                return {"ok": False, "reason": "invalid_member_diagnostic", "diagnostics": raw_lines[:8]}
            members.append(member)
            diagnostics.append(line)
            continue
        if line == _TAR_ETXTBSY_TRAILER:
            continue
        return {"ok": False, "reason": "unrecognized_diagnostic", "diagnostics": raw_lines[:8]}
    if not members:
        return {"ok": False, "reason": "no_etxtbsy_members", "diagnostics": raw_lines[:8]}

    by_alias: dict[str, dict[tuple[str, str], dict]] = {}
    for entry in plan.get("entries") or ():
        if entry.get("type") != "file":
            continue
        key = (str(entry.get("name")), str(entry.get("path")))
        for alias in _tar_entry_aliases(entry):
            by_alias.setdefault(alias, {})[key] = entry
    skipped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for member, diagnostic in zip(members, diagnostics):
        candidates = by_alias.get(posixpath.normpath(member), {})
        if len(candidates) != 1:
            return {
                "ok": False,
                "reason": "unresolved_or_ambiguous_member",
                "diagnostics": raw_lines[:8],
                "member": member,
            }
        entry = next(iter(candidates.values()))
        key = (str(entry.get("name")), str(entry.get("path")))
        if key in seen:
            return {
                "ok": False,
                "reason": "duplicate_member_diagnostic",
                "diagnostics": raw_lines[:8],
                "member": member,
            }
        seen.add(key)
        skipped.append({
            "member_name": str(entry["name"]),
            "path": str(entry["path"]),
            "type": "file",
            "reason": "etxtbsy",
            "diagnostic": diagnostic[:_MAX_TAR_DIAGNOSTIC_LENGTH],
        })
    return {
        "ok": True,
        "skipped": skipped,
        "diagnostics": diagnostics[:_MAX_TAR_DIAGNOSTICS],
        "tar_exit_code": status,
    }


def extract_restore_archive(
    ssh,
    server: dict,
    *,
    remote_archive: str,
    remote_member_list: str,
    roots,
    exec_sudo,
    plan: dict,
    timeout: int = 1800,
) -> dict:
    """Extract exactly the backend allowlist and return actual ETXTBSY skips."""
    normalized = [posixpath.normpath(str(root)) for root in roots or ()]
    if not normalized:
        raise _apply_failure("Распаковка без корней восстановления невозможна")
    if not isinstance(plan, dict) or not plan.get("entries"):
        raise _apply_failure("Распаковка без effective Restore plan невозможна")

    layout = plan.get("layout")
    target_root = plan.get("target_root")
    directories = {
        posixpath.dirname(root)
        for root in normalized
        if posixpath.dirname(root) not in ("", "/")
    }
    if layout == "target_root":
        target_root = posixpath.normpath(str(target_root or ""))
        if not target_root.startswith("/") or target_root in {"", ".", "/"}:
            raise _apply_failure("Некорректный target root effective Restore plan")
        directories.add(target_root)
        extraction_root = target_root
        strip_option = ""
    elif layout == "manifest_payload":
        extraction_root = "/"
        strip_option = " --strip-components=1"
    else:
        raise _apply_failure("Неизвестный layout effective Restore plan")

    if directories:
        arguments = " ".join(shlex.quote(path) for path in sorted(directories))
        code, _, _ = exec_sudo(
            ssh,
            server,
            f"mkdir -p -- {arguments}",
            timeout=120,
        )
        if code != 0:
            raise _apply_failure(
                "Не удалось создать родительские каталоги восстановления",
                phase="extract",
            )
    quoted_archive = shlex.quote(str(remote_archive))
    quoted_members = shlex.quote(str(remote_member_list))
    quoted_root = shlex.quote(extraction_root)
    command = (
        "LC_ALL=C tar -xz -p --overwrite --numeric-owner"
        f"{strip_option} -C {quoted_root} --null --verbatim-files-from "
        f"--no-recursion --files-from={quoted_members} -f {quoted_archive}"
    )
    code, _, err = exec_sudo(ssh, server, command, timeout=timeout)
    classified = classify_restore_tar_diagnostics(int(code), err, plan=plan)
    if not classified.get("ok"):
        raise _apply_failure(
            "Распаковка архива на target завершилась ошибкой",
            phase="extract",
            tar_exit_code=int(code),
            tar_error=(err or "").strip()[:500] or None,
            tar_classification=classified.get("reason"),
        )
    return classified


def verify_applied_restore(
    ssh,
    server: dict,
    *,
    plan: dict,
    removals: dict | None,
    exec_sudo,
    limit: int = 20,
) -> dict:
    """Проверка после распаковки: план записан, delete-set удалён.

    Проверяются файлы и символьные ссылки: каталог сам по себе содержимого не
    несёт, а его отсутствие видно по отсутствию членов внутри. Отчёт урезан до
    ``limit`` путей — он попадает в ``error.details`` записи операции.
    """
    expected = [
        str(entry["path"])
        for entry in plan.get("entries") or ()
        if entry.get("type") != "directory"
    ]
    failure = _apply_failure(
        "Не удалось проверить результат восстановления на target",
        phase="verify",
    )
    present = _present_paths(
        ssh,
        server,
        expected,
        exec_sudo=exec_sudo,
        failure=failure,
    )
    missing = [path for path in expected if path not in present]
    leftover: list[str] = []
    if removals is not None:
        planned = [str(path) for path in removals.get("delete") or ()]
        still = _present_paths(
            ssh,
            server,
            planned,
            exec_sudo=exec_sudo,
            failure=failure,
        )
        leftover = [path for path in planned if path in still]
    return {
        "checked": len(expected),
        "missing": missing[:limit],
        "missing_count": len(missing),
        "leftover": leftover[:limit],
        "leftover_count": len(leftover),
    }


# --------------------------------------------------------------------------- #
# Локальное применение: target — сама установка Bot4VPS (self-restore)
# --------------------------------------------------------------------------- #
#
# Те же границы, что и у SSH-вариантов выше, но транспорт — локальный
# subprocess: SSH между машиной и самой собой не нужен. Классификация tar
# и модель verification переиспользуются без изменений.

# Живое координационное состояние текущей машины. Оба файла лежат в data/backup
# и попадают в архив, но перезаписывать их локальным apply нельзя:
# maintenance_state.json — признак активного обслуживания именно текущей
# операции (удаляется при её завершении), inventory-index-jobs.json — реестр
# живых задач индексатора. Лок-файлы живут вне дерева (/run/lock/bot4vps) и в
# архив не входят; running/, disk_state, automatic_state архив тоже не содержит.
SELF_RESTORE_LIVE_STATE_FILES = ("maintenance_state.json", "inventory-index-jobs.json")


def self_restore_live_state_paths(data_root) -> set[str]:
    """Абсолютные пути live-состояния, исключаемого из локального apply."""
    root = str(data_root).rstrip("/") + "/"
    return {
        posixpath.normpath(root + name)
        for name in SELF_RESTORE_LIVE_STATE_FILES
    }


def filter_self_restore_live_state(plan: dict, data_root) -> dict:
    """Убрать из effective plan live-состояние текущей машины.

    Фильтр обязан применяться одинаково на prepare и на apply — сразу после
    ``build_effective_restore_plan`` и до вычисления digest: иначе digest и
    prepared-контракт разошлись бы между фазами. ``bytes`` корней
    пересчитывается для сводки; digest корни по байтам не включает.
    """
    excluded = self_restore_live_state_paths(data_root)
    entries = list(plan.get("entries") or ())
    kept = [
        entry
        for entry in entries
        if str(entry.get("path")) not in excluded
    ]
    if len(kept) == len(entries):
        return plan
    filtered = dict(plan)
    filtered["entries"] = kept
    sizes: dict[str, int] = {}
    for entry in kept:
        root = str(entry.get("root"))
        try:
            sizes[root] = sizes.get(root, 0) + int(entry.get("size") or 0)
        except (TypeError, ValueError):
            sizes[root] = sizes.get(root, 0)
    filtered["roots"] = [
        {**item, "bytes": sizes.get(str(item.get("root")), 0)}
        for item in (plan.get("roots") or ())
    ]
    return filtered


def assert_no_symlink_components_local(roots) -> None:
    """Локальный аналог ``assert_no_symlink_components`` без SSH.

    Нормализованные корни и их родители проверяются ``os.path.islink`` по
    каждому компоненту: symlink в пути распаковки увёл бы запись за пределы
    объявленного scope.
    """
    items = [posixpath.normpath(str(root)) for root in roots or ()]
    if not items:
        raise _precheck("План восстановления не содержит корней")
    found: set[str] = set()
    for item in items:
        current = item
        while True:
            if os.path.islink(current):
                found.add(current)
            parent = posixpath.dirname(current)
            if parent in ("", "/", current):
                break
            current = parent
    if found:
        raise _precheck(
            "Восстановление не выполняется: путь содержит символьную ссылку — "
            + ", ".join(sorted(found)[:5])
        )


def assert_no_symlink_ancestors_local(plan: dict) -> None:
    """Локальный аналог ``assert_no_symlink_ancestors`` без SSH.

    Проверяются только промежуточные компоненты членов плана СТРОГО внутри
    корней (сами корни — предыдущая функция): tar проходит существующий
    symlink насквозь и пишет за пределы корня молча, с кодом 0.
    """
    found: set[str] = set()
    for path in planned_symlink_guard_paths(plan):
        current = str(path)
        while True:
            if os.path.islink(current):
                found.add(current)
            parent = posixpath.dirname(current)
            if parent in ("", "/", current):
                break
            current = parent
        if found:
            # Первый же найденный обрывает обход: перечень полный не нужен,
            # отказ уже состоялся.
            break
    if found:
        raise _precheck(
            "Восстановление не выполняется: внутри восстанавливаемого корня "
            "промежуточный каталог оказался символьной ссылкой — "
            + ", ".join(sorted(found)[:5])
        )


def assert_free_space_local(requirements) -> dict:
    """Локальная проверка свободного места до начала мутации.

    ``shutil.disk_usage`` сам поднимается по дереву к точке монтирования,
    когда пути ещё не существует.
    """
    import shutil

    measured: dict[str, int] = {}
    for path, needed in requirements or ():
        probe = str(path)
        if not os.path.exists(probe):
            parent = posixpath.dirname(probe)
            probe = parent if parent not in ("", "/") else "/"
        try:
            available = shutil.disk_usage(probe).free
        except OSError:
            raise _precheck(
                f"Не удалось измерить свободное место для {path}"
            ) from None
        measured[str(path)] = available
        if available < int(needed):
            raise _precheck(
                f"Недостаточно свободного места для {path}: "
                f"нужно ~{int(needed) // (1024 * 1024)} МиБ, "
                f"доступно {available // (1024 * 1024)} МиБ"
            )
    return measured


def restore_space_requirements_local(plan: dict) -> list[tuple[str, int]]:
    """Требования по месту для локального apply: только корни.

    В отличие от restore по SSH, архив уже лежит локально (staging хранилища
    или расшифрованный temp вне дерева) — доставка ничего не требует.
    """
    return [
        (str(item["root"]), int(item.get("bytes") or 0))
        for item in plan.get("roots") or ()
    ]


def extract_restore_archive_local(
    archive_path,
    member_list_path,
    *,
    roots,
    plan: dict,
    timeout: int = 1800,
) -> dict:
    """Локальная распаковка ровно по trusted member list.

    Та же команда tar с теми же флагами, что и у SSH-варианта, но через
    ``subprocess`` на этой машине. Возвращается результат существующей
    ``classify_restore_tar_diagnostics``.

    Локальная семантика ETXTBSY отличается от удалённого restore: здесь
    сервис уже остановлен раннером, и занятый файл структурно невозможен
    (ELF-бинарников в дереве вне venv нет). Любой пропущенный член — отказ
    фазы мутации; классификатор используется только чтобы извлечь пути.
    """
    normalized = [posixpath.normpath(str(root)) for root in roots or ()]
    if not normalized:
        raise _apply_failure("Распаковка без корней восстановления невозможна")
    if not isinstance(plan, dict) or not plan.get("entries"):
        raise _apply_failure("Распаковка без effective Restore plan невозможна")

    import subprocess

    layout = plan.get("layout")
    target_root = plan.get("target_root")
    directories = {
        posixpath.dirname(root)
        for root in normalized
        if posixpath.dirname(root) not in ("", "/")
    }
    if layout == "target_root":
        target_root = posixpath.normpath(str(target_root or ""))
        if not target_root.startswith("/") or target_root in {"", ".", "/"}:
            raise _apply_failure("Некорректный target root effective Restore plan")
        directories.add(target_root)
        extraction_root = target_root
        strip_option: list[str] = []
    elif layout == "manifest_payload":
        extraction_root = "/"
        strip_option = ["--strip-components=1"]
    else:
        raise _apply_failure("Неизвестный layout effective Restore plan")

    for directory in sorted(directories):
        try:
            Path(directory).mkdir(parents=True, exist_ok=True)
        except OSError:
            raise _apply_failure(
                "Не удалось создать родительские каталоги восстановления",
                phase="extract",
            ) from None

    command = [
        "tar", "-xz", "-p", "--overwrite", "--numeric-owner",
        *strip_option,
        "-C", str(extraction_root),
        "--null", "--verbatim-files-from", "--no-recursion",
        f"--files-from={member_list_path}",
        "-f", str(archive_path),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env={**os.environ, "LC_ALL": "C"},
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise _apply_failure(
            "Распаковка архива не уложилась в отведённое время",
            phase="extract",
        ) from None
    except OSError as exc:
        raise _apply_failure(
            "Не удалось запустить локальную распаковку архива",
            phase="extract",
            error=str(exc)[:300],
        ) from exc

    stderr = result.stderr or ""
    classified = classify_restore_tar_diagnostics(
        int(result.returncode),
        stderr,
        plan=plan,
    )
    if not classified.get("ok"):
        raise _apply_failure(
            "Распаковка архива завершилась ошибкой",
            phase="extract",
            tar_exit_code=int(result.returncode),
            tar_error=stderr.strip()[:500] or None,
            tar_classification=classified.get("reason"),
        )
    if classified.get("skipped"):
        # Сервис остановлен: занятый файл — неожиданный процесс держит
        # дерево установки, и частичный apply оставил бы установку в
        # полустаром-полуновом состоянии. Отказ, а не skip+warning.
        busy = [str(item.get("path")) for item in classified["skipped"]]
        raise _apply_failure(
            "Занятые файлы при остановленном сервисе: восстановление "
            "не может быть применено",
            phase="extract",
            tar_exit_code=int(result.returncode),
            busy_paths=busy[:20],
            busy_count=len(busy),
        )
    return classified


def verify_applied_restore_local(
    plan: dict,
    *,
    limit: int = 20,
) -> dict:
    """Локальная проверка после распаковки: план записан на месте.

    Merge-режим Bot4VPS ничего не удаляет, поэтому leftover тривиально пуст.
    Проверяются файлы и символьные ссылки: каталог сам по себе содержимого
    не несёт (как у SSH-варианта — через ``lexists``).
    """
    expected = [
        str(entry["path"])
        for entry in plan.get("entries") or ()
        if entry.get("type") != "directory"
    ]
    missing = [path for path in expected if not os.path.lexists(path)]
    return {
        "checked": len(expected),
        "missing": missing[:limit],
        "missing_count": len(missing),
        "leftover": [],
        "leftover_count": 0,
    }
