"""Чистое планирование Restore: ни SSH, ни мутаций, ни чтения target.

Модуль отвечает ровно на два вопроса и ничего не делает:

* куда именно лёг бы каждый член архива (scope, раскладка, абсолютные пути);
* что внутри roots есть на target, но отсутствует в архиве (delete-set).

Всё, что требует соединения с target (``df``, ``find``, распаковка), появляется
на следующих этапах и получает результат этих функций как вход. Поэтому здесь
нет ни одного импорта транспорта, а инвентаризация принимается уже прочитанной.

Scope никогда не угадывается по общему родителю членов: он либо персистирован
(Catalog / Manifest), либо назван человеком (``target_root``). Из членов архива
корень вывести нельзя — корневая запись каталога выбрасывается при repack.
"""

from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
import posixpath
from dataclasses import dataclass
from pathlib import PurePosixPath

from .errors import BackupError, ErrorCode
from .manifest import _payload_prefix_for, _normalized_member_name, _reject_secret_path


MANIFEST_MEMBER_NAME = "manifest.json"
PAYLOAD_NAMESPACE = "payload"

# Раскладка A: manifest.json в корне + payload/<абсолютный путь без ведущего
# слэша>. Раскладка B: чужой tar с произвольными относительными именами,
# распаковываемый в явно указанный пользователем корень.
LAYOUT_MANIFEST_PAYLOAD = "manifest_payload"
LAYOUT_TARGET_ROOT = "target_root"

SCOPE_ORIGIN_CATALOG = "catalog"
SCOPE_ORIGIN_MANIFEST = "manifest"
SCOPE_ORIGIN_REQUEST = "request"

MAX_PREVIEW_NODES = 2000
MAX_SELECTION_PATHS = 512

SELECTION_MODE_FULL = "full"
SELECTION_MODE_SELECTED = "selected"
SELECTION_MODES = (SELECTION_MODE_FULL, SELECTION_MODE_SELECTED)

# Online Restore must never rewrite a running system's boot/runtime userland.
# The aliases are listed explicitly: policy must not depend on whether this
# particular target implements merged-/usr with symlinks.
ONLINE_RESTORE_BLOCKED_TREES = (
    "/boot",
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/bin",
    "/sbin",
    "/lib",
    "/lib32",
    "/lib64",
    "/libx32",
    "/usr/bin",
    "/usr/sbin",
    "/usr/lib",
    "/usr/lib32",
    "/usr/lib64",
    "/usr/libx32",
    "/usr/libexec",
)


def _precheck(message: str, *, details: dict | None = None) -> BackupError:
    """Любая непройденная граница — это отказ до destructive boundary."""
    return BackupError(
        ErrorCode.RESTORE_PRECHECK_FAILED,
        message,
        details=details,
    )


@dataclass(frozen=True)
class RestoreScope:
    """Разрешённый scope: откуда взяты корни и как устроен архив."""

    layout: str
    origin: str
    roots: tuple[str, ...]
    # (payload-префикс, root) для раскладки A. Порядок совпадает с roots.
    prefixes: tuple[tuple[str, str], ...] = ()
    target_root: str | None = None

    def to_dict(self) -> dict:
        return {
            "layout": self.layout,
            "origin": self.origin,
            "roots": list(self.roots),
            "target_root": self.target_root,
        }


def normalize_restore_root(value: object, *, field: str = "root") -> str:
    """Проверка 1: абсолютный нормализованный POSIX-путь, не ``/``, глубина ≥ 1.

    ``posixpath.normpath`` по стандарту POSIX сохраняет ровно два ведущих слэша,
    поэтому ``//opt/app`` остаётся отдельным путём — коллизию его payload-префикса
    с ``/opt/app`` ловит проверка 3, а не эта.
    """
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise _precheck(f"{field} должен быть непустым абсолютным POSIX path")
    if not PurePosixPath(value).is_absolute():
        raise _precheck(f"{field} должен быть абсолютным path: {value}")
    normalized = posixpath.normpath(value)
    if normalized in {"/", "//"} or len(PurePosixPath(normalized).parts) < 2:
        raise _precheck(f"Корень файловой системы не может быть {field}: {value}")
    return normalized


def reject_secret_restore_root(root: str) -> None:
    """Проверка 9: подделанный manifest не должен назначить корнем секретный путь.

    ``_reject_secret_path`` применяется только при ЗАПИСИ manifest, а путь import
    проверку структуры вообще не проходит — чужой manifest с ``/root/.ssh`` иначе
    стал бы корнем восстановления и удаления. Список «секретного» не дублируется:
    используется тот же предикат, что и при записи.
    """
    try:
        _reject_secret_path(root)
    except BackupError as exc:
        raise _precheck(f"Недопустимый корень восстановления: {root}") from exc


def validate_restore_roots(
    roots,
    *,
    storage_root: str | None = None,
    field: str = "root",
) -> tuple[str, ...]:
    """Проверки 1–4 раздела 2 плана. Возвращает нормализованные корни.

    ``storage_root`` имеет смысл только когда target — локальная файловая
    система (Bot4VPS): для серверного Restore корни живут на удалённой машине и
    к локальному хранилищу архивов отношения не имеют.
    """
    if not isinstance(roots, (list, tuple)) or not roots:
        raise _precheck("Scope восстановления пуст: корни не определены")
    normalized = [normalize_restore_root(value, field=field) for value in roots]

    for index, root in enumerate(normalized):
        for other in normalized[index + 1:]:
            if root == other:
                raise _precheck(f"Корень восстановления указан дважды: {root}")
            if _is_within(root, other) or _is_within(other, root):
                raise _precheck(f"Корни восстановления вложены друг в друга: {root} и {other}")

    prefixes: dict[str, str] = {}
    for root in normalized:
        prefix = _payload_prefix_for(root)
        if prefix in prefixes:
            raise _precheck(
                f"Корни {prefixes[prefix]} и {root} дают один payload-префикс {prefix}"
            )
        prefixes[prefix] = root

    if storage_root is not None:
        storage = normalize_restore_root(storage_root, field="storage root")
        for root in normalized:
            # Не только «root внутри storage», но и обратное: корень-предок
            # хранилища снёс бы сами архивы вместе с защитной копией.
            if _is_within(root, storage) or _is_within(storage, root):
                raise _precheck(
                    f"Корень восстановления пересекается с хранилищем архивов: {root}"
                )
    return tuple(normalized)


def _is_within(path: str, root: str) -> bool:
    """Лежит ли path внутри root (или равен ему) при строгом сравнении границ."""
    return path == root or path.startswith(root.rstrip("/") + "/")


def _online_policy_path(value: object, *, field: str) -> str:
    """Normalize a planned absolute path for conservative Linux policy matching."""
    normalized = normalize_restore_root(value, field=field)
    # POSIX preserves exactly two leading slashes, but Linux resolves them to the
    # same filesystem root.  Treating //usr as distinct here would bypass policy.
    if normalized.startswith("//"):
        normalized = "/" + normalized.lstrip("/")
    return normalized


def assert_online_restore_scope_safe(
    plan: dict,
    *,
    include_clean_roots: bool = True,
    delete_paths=(),
) -> None:
    """Refuse effective writes/deletes intersecting live boot/core userland."""
    if not isinstance(plan, dict):
        raise _precheck("План online Restore недоступен")

    planned_paths: set[str] = set()
    roots = plan.get("roots")
    entries = plan.get("entries")
    if not isinstance(roots, list) or not roots:
        raise _precheck("План online Restore не содержит write-корней")
    if not isinstance(entries, list) or not entries:
        raise _precheck("План online Restore не содержит путей")

    for index, item in enumerate(roots):
        if not isinstance(item, dict):
            raise _precheck("Некорректный write-корень плана online Restore")
        planned_paths.add(
            _online_policy_path(
                item.get("root"),
                field=f"plan.roots[{index}].root",
            )
        )
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise _precheck("Некорректный путь плана online Restore")
        planned_paths.add(
            _online_policy_path(
                entry.get("path"),
                field=f"plan.entries[{index}].path",
            )
        )
    if include_clean_roots:
        clean_roots = plan.get("clean_roots", ())
        if not isinstance(clean_roots, (list, tuple)):
            raise _precheck("Некорректные clean roots плана online Restore")
        for index, root in enumerate(clean_roots):
            planned_paths.add(
                _online_policy_path(root, field=f"plan.clean_roots[{index}]")
            )
    if not isinstance(delete_paths, (list, tuple, set)):
        raise _precheck("Некорректный delete-set плана online Restore")
    for index, path in enumerate(delete_paths):
        planned_paths.add(_online_policy_path(path, field=f"delete_paths[{index}]"))

    blocked = [
        tree
        for tree in ONLINE_RESTORE_BLOCKED_TREES
        if any(
            _is_within(path, tree) or _is_within(tree, path)
            for path in planned_paths
        )
    ]
    if blocked:
        raise _precheck(
            "Online Restore запрещён: scope затрагивает критические системные "
            f"пути: {', '.join(blocked)}",
            details={"blocked_paths": blocked},
        )


def online_restore_policy_revision() -> str:
    """Return a stable revision for the UI projection of current online policy."""
    payload = json.dumps(
        {
            "version": 1,
            "blocked_trees": ONLINE_RESTORE_BLOCKED_TREES,
            "hardlink_dependencies": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"bot4vps:restore-online-policy:v1\0" + payload).hexdigest()


def _online_restore_path_is_blocked(path: object) -> bool:
    normalized = _online_policy_path(path, field="policy path")
    return any(
        _is_within(normalized, tree) or _is_within(tree, normalized)
        for tree in ONLINE_RESTORE_BLOCKED_TREES
    )


def build_bulk_restore_policy(
    *,
    node_paths,
    node_types,
    parent_ids,
    node_member_counts,
    hardlink_dependencies=(),
) -> dict:
    """Project online selection policy over a compact parent-before-child graph.

    ``node_types`` uses the compact inventory tags (0=file, 1=directory), and
    ``node_member_counts`` is the number of physical members selected by that node.
    ``hardlink_dependencies`` contains ``(owning_directory_id, target_path)`` for
    hardlink members. A dependency outside a selected directory is part of the
    physical effective plan, so a critical target blocks that directory and all
    of its selectable ancestors.
    """
    count = len(node_paths)
    if (
        len(node_types) != count
        or len(parent_ids) != count
        or len(node_member_counts) != count
    ):
        raise _precheck("Некорректный compact graph online Restore policy")

    blocked = bytearray(count)
    for node_id, (path, node_type, parent_id, member_count) in enumerate(
        zip(node_paths, node_types, parent_ids, node_member_counts)
    ):
        if node_type not in {0, 1}:
            raise _precheck("Некорректный тип compact node online Restore policy")
        if (
            isinstance(member_count, bool)
            or not isinstance(member_count, int)
            or member_count < 0
        ):
            raise _precheck("Некорректный member count compact node online Restore policy")
        if member_count == 0:
            blocked[node_id] = 1
        if (
            isinstance(parent_id, bool)
            or not isinstance(parent_id, int)
            or parent_id < -1
            or parent_id >= node_id
        ):
            raise _precheck("Некорректный parent compact node online Restore policy")
        if parent_id == -1 and not isinstance(path, str):
            raise _precheck("Некорректный root compact node online Restore policy")
        blocked[node_id] |= int(_online_restore_path_is_blocked(path))

    for dependency in hardlink_dependencies:
        if (
            not isinstance(dependency, (list, tuple))
            or len(dependency) != 2
        ):
            raise _precheck("Некорректная hardlink dependency online Restore policy")
        owner_id, target_path = dependency
        if (
            isinstance(owner_id, bool)
            or not isinstance(owner_id, int)
            or owner_id < 0
            or owner_id >= count
            or node_types[owner_id] != 1
        ):
            raise _precheck("Hardlink dependency не относится к directory node")
        if not _online_restore_path_is_blocked(target_path):
            continue
        current = owner_id
        while current >= 0:
            blocked[current] = 1
            current = parent_ids[current]

    selectable = bytearray(1 - value for value in blocked)
    selectable_descendants = bytearray(count)
    for node_id in range(count - 1, -1, -1):
        parent_id = parent_ids[node_id]
        if parent_id >= 0 and (
            selectable[node_id] or selectable_descendants[node_id]
        ):
            selectable_descendants[parent_id] = 1

    covered = bytearray(count)
    frontier: list[int] = []
    for node_id in range(count):
        parent_id = parent_ids[node_id]
        ancestor_covers = parent_id >= 0 and covered[parent_id]
        if selectable[node_id] and not ancestor_covers:
            frontier.append(node_id)
        covered[node_id] = int(bool(ancestor_covers or selectable[node_id]))

    frontier.sort(
        key=lambda node_id: (
            len(PurePosixPath(node_paths[node_id]).parts),
            node_paths[node_id],
        )
    )
    has_selectable = bool(any(selectable))
    has_blocked = bool(any(blocked))
    has_mixed = any(
        blocked[node_id]
        and node_types[node_id] == 1
        and selectable_descendants[node_id]
        for node_id in range(count)
    )
    return {
        "selectable": selectable,
        "blocked": blocked,
        "has_selectable_descendants": selectable_descendants,
        "summary": (
            (0x01 if has_selectable else 0)
            | (0x02 if has_blocked else 0)
            | (0x04 if has_mixed else 0)
        ),
        "frontier": frontier,
    }


def _catalog_source_paths(record: object) -> list[str]:
    if not isinstance(record, dict):
        raise _precheck("Catalog-запись backup недоступна")
    projection = record.get("manifest")
    source_paths = projection.get("source_paths") if isinstance(projection, dict) else None
    if not isinstance(source_paths, list) or not source_paths:
        raise _precheck(
            "Catalog-запись не содержит source_paths: scope восстановления неизвестен"
        )
    return source_paths


def _manifest_source_paths(manifest: object) -> list[str]:
    if not isinstance(manifest, dict):
        raise _precheck("Manifest архива недоступен")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise _precheck("Manifest архива не содержит sources: scope восстановления неизвестен")
    paths = []
    for item in sources:
        if not isinstance(item, dict):
            raise _precheck("Некорректный элемент manifest sources")
        paths.append(item.get("path"))
    return paths


def build_restore_scope(
    *,
    catalog_record: dict | None = None,
    manifest: dict | None = None,
    target_root: object | None = None,
    storage_root: str | None = None,
) -> RestoreScope:
    """Разрешить scope по трём уровням: Catalog → Manifest архива → запрос.

    Уровни не совмещаются: явный ``target_root`` вместе с персистированным scope
    означал бы молчаливое перенаправление восстановления в другое место, а это уже
    релокация, а не Restore v1. Если есть и Catalog-запись, и manifest, корни
    берутся из Catalog — читать архив ради scope не требуется.
    """
    if target_root is not None and (catalog_record is not None or manifest is not None):
        raise _precheck("target_root задаётся только для архива без manifest")

    if catalog_record is not None:
        roots = validate_restore_roots(
            _catalog_source_paths(catalog_record),
            storage_root=storage_root,
            field="source_paths Catalog",
        )
        origin = SCOPE_ORIGIN_CATALOG
    elif manifest is not None:
        roots = validate_restore_roots(
            _manifest_source_paths(manifest),
            storage_root=storage_root,
            field="manifest sources[].path",
        )
        for root in roots:
            reject_secret_restore_root(root)
        origin = SCOPE_ORIGIN_MANIFEST
    elif target_root is not None:
        root = normalize_restore_root(target_root, field="target_root")
        validate_restore_roots([root], storage_root=storage_root, field="target_root")
        return RestoreScope(
            layout=LAYOUT_TARGET_ROOT,
            origin=SCOPE_ORIGIN_REQUEST,
            roots=(root,),
            target_root=root,
        )
    else:
        raise _precheck(
            "Scope восстановления не определён: нужен Catalog, manifest архива или target_root"
        )

    return RestoreScope(
        layout=LAYOUT_MANIFEST_PAYLOAD,
        origin=origin,
        roots=roots,
        prefixes=tuple((_payload_prefix_for(root), root) for root in roots),
    )


def map_restore_member(
    name: object,
    scope: RestoreScope,
) -> tuple[str, str, str] | None:
    """Map one member name without materializing a Restore entry dictionary."""
    try:
        normalized = _normalized_member_name(name)
    except BackupError as exc:
        raise _precheck(f"Небезопасное имя члена архива: {exc.safe_message}") from exc

    if scope.layout == LAYOUT_MANIFEST_PAYLOAD:
        if normalized == MANIFEST_MEMBER_NAME:
            return None
        path, root = _payload_member_target(normalized, scope)
    else:
        root = scope.target_root
        path = posixpath.normpath(posixpath.join(root, normalized))
        if not _is_within(path, root):
            raise _precheck(f"Член архива выходит за target_root: {normalized}")
    return normalized, path, root


def map_restore_members(members, scope: RestoreScope) -> list[dict]:
    """Проверка 5: сопоставить членов архива с абсолютными путями на target.

    Возвращает по одной записи на член, каждая с ``path`` (куда лёг бы член) и
    ``root`` (к какому корню он относится). Имена проходят ту же нормализацию,
    что и при верификации архива, поэтому ``..`` и абсолютные имена отвергаются.
    """
    if not isinstance(members, (list, tuple)):
        raise _precheck("Список членов архива недоступен")
    entries: list[dict] = []
    for member in members:
        if not isinstance(member, dict):
            raise _precheck("Некорректная запись члена архива")
        mapped = map_restore_member(member.get("name"), scope)
        if mapped is None:
            continue
        name, path, root = mapped
        entry = {
            "name": name,
            "type": member.get("type"),
            "size": int(member.get("size") or 0),
            "path": path,
            "root": root,
        }
        if member.get("linkname") is not None:
            entry["linkname"] = member.get("linkname")
        entries.append(entry)
    return entries


def _payload_member_target(name: str, scope: RestoreScope) -> tuple[str, str]:
    """Снять payload-префикс объявленного корня и получить абсолютный путь.

    Путь строится от самого корня, а не как ``"/" + остаток``: у корня ``//opt/app``
    префикс тот же ``payload/opt/app``, и восстановление обязано попасть ровно в
    объявленный корень.
    """
    for prefix, root in scope.prefixes:
        if name == prefix:
            return root, root
        if name.startswith(prefix + "/"):
            return posixpath.join(root, name[len(prefix) + 1:]), root
    raise _precheck(f"Член архива находится вне описанных корней: {name}")


def classify_restore_roots(scope: RestoreScope, entries: list[dict]) -> list[dict]:
    """Проверка 6: вид каждого корня (файл или каталог) должен быть однозначен.

    Старые архивы, испорченные дефектом P2, содержат ``payload/etc/app.conf/app.conf``.
    Такой корень честно классифицируется как каталог: Restore обязан работать с
    фактическим содержимым архива, а не переинтерпретировать его. Ошибка — только
    на настоящей двусмысленности: корень пришёл и файлом, и родителем других членов.
    """
    summary: list[dict] = []
    for root in scope.roots:
        own = [entry for entry in entries if entry["root"] == root]
        exact = [entry for entry in own if entry["path"] == root]
        nested = [entry for entry in own if entry["path"] != root]
        kind = "directory"
        if exact:
            if exact[0].get("type") != "directory":
                if nested:
                    raise _precheck(
                        f"Вид источника неоднозначен: {root} присутствует и как файл, "
                        "и как родитель других членов"
                    )
                kind = "file"
        item = {
            "root": root,
            "kind": kind,
            "entries": len(own),
            "bytes": sum(entry["size"] for entry in own if entry.get("type") == "file"),
        }
        if scope.layout == LAYOUT_MANIFEST_PAYLOAD:
            item["payload_prefix"] = _payload_prefix_for(root)
        summary.append(item)
    return summary


def build_restore_plan(
    *,
    members,
    catalog_record: dict | None = None,
    manifest: dict | None = None,
    target_root: object | None = None,
    storage_root: str | None = None,
) -> dict:
    """Полный план восстановления без единого обращения к target."""
    scope = build_restore_scope(
        catalog_record=catalog_record,
        manifest=manifest,
        target_root=target_root,
        storage_root=storage_root,
    )
    entries = map_restore_members(members, scope)
    if not entries:
        raise _precheck("Архив не содержит ни одного восстанавливаемого члена")
    roots = classify_restore_roots(scope, entries)
    counts = {
        "members": len(entries),
        "files": sum(1 for entry in entries if entry.get("type") == "file"),
        "directories": sum(1 for entry in entries if entry.get("type") == "directory"),
        "symlinks": sum(1 for entry in entries if entry.get("type") == "symlink"),
        "hardlinks": sum(1 for entry in entries if entry.get("type") == "hardlink"),
        "bytes": sum(entry["size"] for entry in entries if entry.get("type") == "file"),
    }
    plan = scope.to_dict()
    plan.update({"roots": roots, "entries": entries, "counts": counts})
    return plan


def normalize_selection_mode(value: object) -> str:
    mode = str(value or SELECTION_MODE_FULL).strip().lower()
    if mode not in SELECTION_MODES:
        raise _precheck("Некорректный режим выбора Restore: нужен full или selected")
    return mode


def _entry_counts(entries) -> dict:
    values = list(entries or ())
    return {
        "members": len(values),
        "files": sum(1 for entry in values if entry.get("type") == "file"),
        "directories": sum(1 for entry in values if entry.get("type") == "directory"),
        "symlinks": sum(1 for entry in values if entry.get("type") == "symlink"),
        "hardlinks": sum(1 for entry in values if entry.get("type") == "hardlink"),
        "bytes": sum(
            int(entry.get("size") or 0)
            for entry in values
            if entry.get("type") == "file"
        ),
    }


def build_restore_selection_index(plan: dict) -> dict[str, dict]:
    """Build backend-owned selectable directories and ordinary-file paths."""
    if not isinstance(plan, dict):
        raise _precheck("Полный план Restore недоступен")
    entries = plan.get("entries")
    roots = plan.get("roots")
    if not isinstance(entries, list) or not entries:
        raise _precheck("Полный план Restore не содержит членов архива")
    if not isinstance(roots, list) or not roots:
        raise _precheck("Полный план Restore не содержит корней")

    index: dict[str, dict] = {}

    def ensure_directory(path: str, root: str, *, explicit: bool = False) -> None:
        current = path
        while _is_within(current, root):
            existing = index.get(current)
            if existing is not None and existing.get("type") != "directory":
                raise _precheck(f"Вид selectable path неоднозначен: {current}")
            node = index.setdefault(
                current,
                {
                    "path": current,
                    "root": root,
                    "parent": None if current == root else posixpath.dirname(current),
                    "type": "directory",
                    "explicit": False,
                    "member_count": 0,
                    "file_count": 0,
                    "bytes": 0,
                },
            )
            if node["root"] != root:
                raise _precheck(f"Selectable path относится к нескольким корням: {current}")
            if current == path and explicit:
                node["explicit"] = True
            if current == root:
                break
            parent = posixpath.dirname(current)
            if parent == current:
                raise _precheck(f"Не удалось построить selection index для {path}")
            current = parent

    root_kinds: dict[str, str] = {}
    for item in roots:
        if not isinstance(item, dict):
            raise _precheck("Некорректный корень полного плана Restore")
        root = normalize_restore_root(item.get("root"), field="plan root")
        kind = str(item.get("kind") or "")
        if root in root_kinds:
            raise _precheck(f"Повторяющийся корень полного плана Restore: {root}")
        root_kinds[root] = kind
        if kind == "directory":
            ensure_directory(root, root, explicit=True)

    mapped_entries: list[tuple[int, dict, str, str]] = []
    entry_paths: set[str] = set()
    for entry_index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise _precheck("Некорректный член полного плана Restore")
        path = normalize_restore_root(entry.get("path"), field="plan entry path")
        root = normalize_restore_root(entry.get("root"), field="plan entry root")
        if root not in root_kinds or not _is_within(path, root):
            raise _precheck(f"Член архива находится вне корня полного плана: {path}")
        if path in entry_paths:
            raise _precheck(f"Повторяющийся mapped path полного плана Restore: {path}")
        entry_paths.add(path)
        mapped_entries.append((entry_index, entry, path, root))

        if entry.get("type") == "directory":
            ensure_directory(path, root, explicit=True)
        parent = path if entry.get("type") == "directory" else posixpath.dirname(path)
        if _is_within(parent, root) and root_kinds[root] == "directory":
            ensure_directory(parent, root)
        current = parent
        while _is_within(current, root) and current in index:
            node = index[current]
            node["member_count"] += 1
            if entry.get("type") == "file":
                node["file_count"] += 1
                node["bytes"] += int(entry.get("size") or 0)
            if current == root:
                break
            current = posixpath.dirname(current)

    for entry_index, entry, path, root in mapped_entries:
        if entry.get("type") != "file":
            continue
        if path in index:
            raise _precheck(f"Вид selectable path неоднозначен: {path}")
        parent = posixpath.dirname(path)
        index[path] = {
            "path": path,
            "root": root,
            "parent": parent if parent in index else None,
            "type": "file",
            "entry_index": entry_index,
            "size": int(entry.get("size") or 0),
        }
    return index


def normalize_selected_paths(
    values,
    *,
    selection_index: dict[str, dict],
    max_paths: int = MAX_SELECTION_PATHS,
) -> list[str]:
    if not isinstance(values, (list, tuple)) or not values:
        raise _precheck("Для выборочного Restore нужен хотя бы один элемент")
    if len(values) > max_paths:
        raise _precheck(
            f"Для выборочного Restore разрешено не более {max_paths} элементов"
        )
    normalized = [
        normalize_restore_root(value, field="selected path") for value in values
    ]
    if len(set(normalized)) != len(normalized):
        raise _precheck("Selected paths содержат повторяющийся элемент")
    unknown = [path for path in normalized if path not in selection_index]
    if unknown:
        raise _precheck(
            "Выбранный путь отсутствует в selection index или недоступен: "
            + ", ".join(unknown[:8])
        )

    selected: list[str] = []
    selected_directories: list[str] = []
    for path in sorted(
        normalized,
        key=lambda item: (len(PurePosixPath(item).parts), item),
    ):
        if any(_is_within(path, parent) for parent in selected_directories):
            continue
        item_type = selection_index[path].get("type")
        if item_type not in {"directory", "file"}:
            raise _precheck(f"Тип selected path не поддерживается: {path}")
        selected.append(path)
        if item_type == "directory":
            selected_directories.append(path)
    return selected


@dataclass(frozen=True)
class _RestorePlanningContext:
    """One immutable-by-convention index set tied to one exact full plan."""

    plan: dict
    entries: list[dict]
    roots: list[dict]
    selection_index: dict[str, dict]
    member_indices_by_name: dict[str, int]


def _build_restore_planning_context(plan: dict) -> _RestorePlanningContext:
    if not isinstance(plan, dict):
        raise _precheck("Полный план Restore недоступен")
    entries = plan.get("entries")
    roots = plan.get("roots")
    if not isinstance(entries, list) or not entries:
        raise _precheck("Полный план Restore не содержит членов архива")
    if not isinstance(roots, list) or not roots:
        raise _precheck("Полный план Restore не содержит корней")

    by_name: dict[str, int] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise _precheck("Некорректный член полного плана Restore")
        name = str(entry.get("name") or "")
        if not name or name in by_name:
            raise _precheck("Полный план Restore содержит повторяющиеся имена членов")
        by_name[name] = index
    return _RestorePlanningContext(
        plan=plan,
        entries=entries,
        roots=roots,
        selection_index=build_restore_selection_index(plan),
        member_indices_by_name=by_name,
    )


def _require_planning_context(
    plan: dict,
    context: _RestorePlanningContext | None,
) -> _RestorePlanningContext:
    if context is None:
        return _build_restore_planning_context(plan)
    if (
        context.plan is not plan
        or context.entries is not plan.get("entries")
        or context.roots is not plan.get("roots")
    ):
        raise _precheck("Planning context относится к другому плану Restore")
    return context


def _hardlink_dependency_indices(
    entries: list[dict],
    selected: set[int],
    *,
    by_name: dict[str, int] | None = None,
) -> set[int]:
    if by_name is None:
        by_name = {}
        for index, entry in enumerate(entries):
            name = str(entry.get("name") or "")
            if not name or name in by_name:
                raise _precheck("Полный план Restore содержит повторяющиеся имена членов")
            by_name[name] = index

    closed = set(selected)
    pending = list(selected)
    while pending:
        index = pending.pop()
        entry = entries[index]
        if entry.get("type") != "hardlink":
            continue
        try:
            target = _normalized_member_name(entry.get("linkname"))
        except BackupError as exc:
            raise _precheck(
                f"Некорректная hardlink dependency: {entry.get('name')}"
            ) from exc
        target_index = by_name.get(target)
        if target_index is None or target_index >= index:
            raise _precheck(
                f"Hardlink dependency отсутствует перед членом {entry.get('name')}"
            )
        target_entry = entries[target_index]
        if target_entry.get("type") != "file":
            raise _precheck(
                f"Hardlink dependency не является ordinary file: {target}"
            )
        if target_index not in closed:
            closed.add(target_index)
            pending.append(target_index)
    return closed


def _effective_root_items(
    entries: list[dict], requested_root_kinds: dict[str, str]
) -> list[dict]:
    requested_roots = list(requested_root_kinds)
    roots = list(requested_roots)
    for entry in entries:
        path = str(entry["path"])
        if not any(_is_within(path, root) for root in roots):
            roots.append(path)
    collapsed: list[str] = []
    for path in sorted(set(roots), key=lambda item: (len(PurePosixPath(item).parts), item)):
        if any(_is_within(path, root) for root in collapsed):
            continue
        collapsed.append(path)

    result = []
    for root in collapsed:
        own = [entry for entry in entries if _is_within(str(entry["path"]), root)]
        exact = next((entry for entry in own if entry["path"] == root), None)
        kind = requested_root_kinds.get(
            root,
            str((exact or {}).get("type") or "file"),
        )
        result.append({
            "root": root,
            "kind": kind,
            "entries": len(own),
            "bytes": sum(
                int(entry.get("size") or 0)
                for entry in own
                if entry.get("type") == "file"
            ),
        })
    return result


def build_effective_restore_plan(
    plan: dict,
    *,
    selection_mode: object = SELECTION_MODE_FULL,
    selected_paths=None,
    _context: _RestorePlanningContext | None = None,
) -> dict:
    """Resolve full/selected requests into one exact archive-order write plan."""
    mode = normalize_selection_mode(selection_mode)
    context = _require_planning_context(plan, _context)
    source_entries = context.entries
    source_roots = context.roots
    selection_index = context.selection_index
    if mode == SELECTION_MODE_FULL:
        if selected_paths not in (None, (), []):
            raise _precheck("Для full Restore selected_paths должны отсутствовать")
        normalized_selection: list[str] = []
        selected_indices = set(range(len(source_entries)))
        requested_root_kinds = {
            str(item["root"]): str(item.get("kind") or "") for item in source_roots
        }
        clean_roots = list(requested_root_kinds)
    else:
        normalized_selection = normalize_selected_paths(
            selected_paths,
            selection_index=selection_index,
        )
        selected_indices: set[int] = set()
        requested_root_kinds: dict[str, str] = {}
        clean_roots: list[str] = []
        for path in normalized_selection:
            item_type = str(selection_index[path]["type"])
            requested_root_kinds[path] = item_type
            if item_type == "directory":
                clean_roots.append(path)
                selected_indices.update(
                    index
                    for index, entry in enumerate(source_entries)
                    if _is_within(str(entry.get("path")), path)
                )
            else:
                selected_indices.add(int(selection_index[path]["entry_index"]))
        if not selected_indices:
            raise _precheck("Выбранные элементы не содержат членов архива")

    closed_indices = _hardlink_dependency_indices(
        source_entries,
        selected_indices,
        by_name=context.member_indices_by_name,
    )
    effective_entries = [copy.deepcopy(source_entries[index]) for index in sorted(closed_indices)]
    if not effective_entries:
        raise _precheck("Effective Restore plan пуст")
    root_items = _effective_root_items(effective_entries, requested_root_kinds)
    for entry in effective_entries:
        candidates = [
            item["root"] for item in root_items if _is_within(str(entry["path"]), item["root"])
        ]
        if not candidates:
            raise _precheck(f"Effective member не отнесён к write root: {entry['path']}")
        entry["root"] = max(candidates, key=len)

    result = {
        key: copy.deepcopy(plan.get(key))
        for key in ("layout", "origin", "target_root")
    }
    result.update({
        "selection_mode": mode,
        "selected_paths": normalized_selection,
        "roots": root_items,
        "write_roots": [item["root"] for item in root_items],
        "clean_roots": clean_roots,
        "entries": effective_entries,
        "counts": _entry_counts(effective_entries),
        "dependency_count": len(closed_indices - selected_indices),
    })
    return result


def _canonical_effective_plan(plan: dict) -> dict:
    if not isinstance(plan, dict):
        raise _precheck("Effective Restore plan недоступен")
    entries = plan.get("entries")
    roots = plan.get("roots")
    selected_paths = plan.get("selected_paths")
    clean_roots = plan.get("clean_roots")
    if (
        not isinstance(entries, list)
        or not entries
        or not isinstance(roots, list)
        or not roots
        or not isinstance(selected_paths, list)
        or not isinstance(clean_roots, list)
    ):
        raise _precheck("Effective Restore plan неполон")
    return {
        "version": 2,
        "layout": plan.get("layout"),
        "target_root": plan.get("target_root"),
        "selection_mode": normalize_selection_mode(plan.get("selection_mode")),
        "selected_paths": list(selected_paths),
        "roots": [
            {"root": item.get("root"), "kind": item.get("kind")}
            for item in roots
        ],
        "clean_roots": list(clean_roots),
        "entries": [
            {
                key: entry.get(key)
                for key in ("name", "type", "size", "path", "root", "linkname")
                if key in entry
            }
            for entry in entries
        ],
    }


def effective_restore_plan_digest(plan: dict) -> str:
    payload = json.dumps(
        _canonical_effective_plan(plan),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"bot4vps:restore-effective-plan:v2\0" + payload).hexdigest()


def restore_delete_set_digest(removals: dict | None) -> str | None:
    if removals is None:
        return None
    if not isinstance(removals, dict) or not isinstance(removals.get("delete"), list):
        raise _precheck("Delete-set Restore недоступен")
    paths = [
        _online_policy_path(path, field="delete path")
        for path in removals["delete"]
    ]
    payload = json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b"bot4vps:restore-delete-set:v1\0" + payload).hexdigest()


def build_restore_directory_tree(
    plan: dict,
    *,
    include_clean_roots: bool = False,
    include_files: bool = False,
    max_nodes: int = MAX_PREVIEW_NODES,
    _context: _RestorePlanningContext | None = None,
) -> dict:
    """Return a bounded backend-policy tree of selectable directories and files."""
    context = _require_planning_context(plan, _context)
    index = context.selection_index
    ordered_directories = sorted(
        (
            path
            for path, item in index.items()
            if item.get("type") == "directory"
        ),
        key=lambda path: (len(PurePosixPath(path).parts), path),
    )
    visible_directories = ordered_directories[:max_nodes]
    visible = set(visible_directories)
    nodes: dict[str, dict] = {}

    def policy(path: str) -> tuple[bool, list[str]]:
        try:
            effective = build_effective_restore_plan(
                plan,
                selection_mode=SELECTION_MODE_SELECTED,
                selected_paths=[path],
                _context=context,
            )
            assert_online_restore_scope_safe(
                effective,
                include_clean_roots=include_clean_roots,
            )
            return True, []
        except BackupError as exc:
            return False, list(exc.details.get("blocked_paths") or ())

    for path in visible_directories:
        item = index[path]
        selectable, blocked_paths = policy(path)
        nodes[path] = {
            "path": path,
            "name": path if item["parent"] is None else posixpath.basename(path),
            "parent": item["parent"],
            "type": "directory",
            "counts": {
                "members": item["member_count"],
                "files": item["file_count"],
                "bytes": item["bytes"],
            },
            "selectable": selectable,
            "blocked": not selectable,
            "blocked_paths": blocked_paths[:16],
            "children": [],
        }

    roots: list[dict] = []
    for path in visible_directories:
        node = nodes[path]
        parent = node["parent"]
        if parent in visible and parent in nodes:
            nodes[parent]["children"].append(node)
        else:
            roots.append(node)

    ordered_files = (
        sorted(
            (
                path
                for path, item in index.items()
                if item.get("type") == "file"
            ),
            key=lambda path: (len(PurePosixPath(path).parts), path),
        )
        if include_files
        else []
    )
    remaining = max(0, max_nodes - len(nodes))
    eligible_files = [
        path
        for path in ordered_files
        if index[path]["parent"] is None or index[path]["parent"] in visible
    ]
    visible_files = eligible_files[:remaining]
    for path in visible_files:
        item = index[path]
        selectable, blocked_paths = policy(path)
        node = {
            "path": path,
            "name": posixpath.basename(path) or path,
            "parent": item["parent"],
            "type": "file",
            "size": item["size"],
            "selectable": selectable,
            "blocked": not selectable,
            "blocked_paths": blocked_paths[:16],
            "children": [],
        }
        nodes[path] = node
        if item["parent"] in nodes:
            nodes[item["parent"]]["children"].append(node)
        else:
            roots.append(node)

    for node in nodes.values():
        node["children"].sort(
            key=lambda child: (
                child.get("type") != "directory",
                child["name"],
                child["path"],
            )
        )
    roots.sort(
        key=lambda node: (
            node.get("type") != "directory",
            node["name"],
            node["path"],
        )
    )
    node_count = len(nodes)
    available_count = len(ordered_directories) + len(ordered_files)
    return {
        "tree": roots,
        "node_count": node_count,
        "truncated": available_count > node_count,
    }


def filtered_restore_verification_plan(plan: dict, skipped: list[dict] | None) -> dict:
    """Copy ``plan`` while excluding only actual ETXTBSY verification skips.

    A hardlink cannot be verified independently after its source was skipped: tar
    may have continued, but the link's inode necessarily depends on that source.
    The validated hardlink graph is therefore closed transitively.  This helper
    never changes the original plan or archive manifest.
    """
    result = copy.deepcopy(plan)
    entries = list(result.get("entries") or ())
    requested = {
        (
            str(item.get("member_name", item.get("name"))),
            str(item.get("path")),
        )
        for item in skipped or ()
    }
    by_alias: dict[str, list[dict]] = {}
    for entry in entries:
        aliases = {
            posixpath.normpath(str(entry.get("name") or "")),
            posixpath.normpath(str(entry.get("path") or "")).lstrip("/"),
        }
        name = posixpath.normpath(str(entry.get("name") or ""))
        if name.startswith("payload/"):
            aliases.add(name[len("payload/"):])
        for alias in aliases:
            if alias and alias != ".":
                by_alias.setdefault(alias, []).append(entry)

    skipped_keys = set(requested)
    changed = True
    while changed:
        changed = False
        for entry in entries:
            if entry.get("type") != "hardlink":
                continue
            key = (str(entry.get("name")), str(entry.get("path")))
            if key in skipped_keys:
                continue
            target = posixpath.normpath(str(entry.get("linkname") or ""))
            candidates = by_alias.get(target, [])
            if any(
                (str(candidate.get("name")), str(candidate.get("path"))) in skipped_keys
                for candidate in candidates
            ):
                skipped_keys.add(key)
                changed = True

    derived = []
    direct_keys = set(requested)
    for entry in entries:
        key = (str(entry.get("name")), str(entry.get("path")))
        if key in skipped_keys and key not in direct_keys:
            derived.append({
                "member_name": str(entry.get("name")),
                "path": str(entry.get("path")),
                "type": str(entry.get("type")),
                "reason": "hardlink_dependency",
            })
    result["entries"] = [
        entry for entry in entries
        if (str(entry.get("name")), str(entry.get("path"))) not in skipped_keys
    ]
    result["verification_skips"] = list(skipped or ()) + derived
    result["verification_counts"] = {
        "planned": len(entries),
        "checked": len(result["entries"]),
        "skipped": len(skipped_keys),
    }
    return result


def planned_symlink_guard_paths(plan: dict) -> list[str]:
    """Промежуточные компоненты пути внутри корней, через которые пойдёт распаковка.

    Возвращает каждый строгий предок целевого пути члена архива, лежащий строго
    внутри своего корня. Сам корень и его родители исключены: их проверяет
    ``assert_no_symlink_components``, и дублировать её здесь нечего.

    Список нужен не архиву, а target: GNU tar безусловно доверяет символьной
    ссылке, которая уже лежит на диске в промежуточном компоненте, и пишет по ней
    за пределы корня. Проверять поэтому надо ровно эти пути — см.
    ``restore_apply.assert_no_symlink_ancestors``.
    """
    roots = {str(item["root"]) for item in plan.get("roots") or ()}
    guarded: set[str] = set()
    for entry in plan.get("entries") or ():
        root = str(entry.get("root") or "")
        if root not in roots:
            raise _precheck(
                f"Член архива не отнесён ни к одному корню плана: {entry.get('path')}"
            )
        path = posixpath.normpath(str(entry.get("path")))
        guarded.update(
            ancestor
            for ancestor in _ancestors_within_root(path, root)
            if ancestor != root
        )
    return sorted(guarded)


def parse_inventory_lines(lines) -> list[dict]:
    """Разобрать вывод ``find <root> -mindepth 1 -printf '%y\\t%s\\t%p\\n'``.

    Разбор оставлен здесь, а не в транспортном слое: он чистый и полностью
    покрывается тестами без SSH.
    """
    if isinstance(lines, str):
        lines = lines.splitlines()
    inventory: list[dict] = []
    for raw in lines:
        if not isinstance(raw, str) or not raw.strip():
            continue
        parts = raw.split("\t", 2)
        if len(parts) != 3:
            raise _precheck("Некорректная строка инвентаризации target")
        kind, size, path = parts
        if not path.startswith("/"):
            raise _precheck(f"Инвентаризация target вернула не абсолютный path: {path}")
        try:
            size_value = int(size)
        except (TypeError, ValueError):
            raise _precheck("Некорректный размер в инвентаризации target") from None
        inventory.append({
            "type": {"f": "file", "d": "directory", "l": "symlink"}.get(kind, "other"),
            "size": size_value,
            "path": posixpath.normpath(path),
        })
    return inventory


def _relative_to_root(path: str, root: str) -> str:
    return path[len(root.rstrip("/")) + 1:] if path != root else ""


def _matches_protected(relative: str, patterns) -> bool:
    """Защищён ли путь сам или любой его предок внутри корня."""
    if not relative:
        return False
    candidate = relative
    while True:
        if any(fnmatch.fnmatchcase(candidate, pattern) for pattern in patterns):
            return True
        parent = posixpath.dirname(candidate)
        if not parent or parent == candidate:
            return False
        candidate = parent


def _ancestors_within_root(path: str, root: str) -> list[str]:
    """Каталоги между root и path включительно по root, исключая сам path."""
    chain = []
    current = posixpath.dirname(path)
    while _is_within(current, root):
        chain.append(current)
        if current == root:
            break
        parent = posixpath.dirname(current)
        if parent == current:
            break
        current = parent
    return chain


def compute_delete_set(
    *,
    inventory,
    restored_paths,
    roots,
    protected_patterns=(),
) -> dict:
    """Что на target есть, а в архиве нет — при буквальной семантике снимка.

    Функция чистая: инвентаризация уже прочитана вызывающим кодом. Родительские
    каталоги корней не удаляются никогда — рассматривается только содержимое
    самих корней. Из результата убраны вложенные пути: удаление каталога уносит
    поддерево, поэтому ``rm`` достаточно дать верхние узлы.

    ``protected_patterns`` — шаблоны относительно корня (``venv/**``). Защищённый
    путь и все его предки остаются, поэтому каталог с защищённым содержимым не
    может быть удалён целиком.
    """
    normalized_roots = tuple(
        normalize_restore_root(root, field="root") for root in (roots or ())
    )
    if not normalized_roots:
        raise _precheck("Delete-set требует хотя бы один корень восстановления")
    patterns = tuple(str(pattern) for pattern in (protected_patterns or ()))

    keep: set[str] = set()
    protected: list[str] = []
    outside: list[str] = []

    def root_of(path: str) -> str | None:
        matched = [root for root in normalized_roots if _is_within(path, root)]
        return max(matched, key=len) if matched else None

    for path in restored_paths or ():
        normalized = posixpath.normpath(str(path))
        root = root_of(normalized)
        if root is None:
            continue
        keep.add(normalized)
        keep.update(_ancestors_within_root(normalized, root))

    candidates: list[str] = []
    for item in inventory or ():
        path = item["path"] if isinstance(item, dict) else str(item)
        normalized = posixpath.normpath(str(path))
        root = root_of(normalized)
        if root is None:
            outside.append(normalized)
            continue
        if normalized == root:
            # Сам корень не удаляется: удаляется только его содержимое.
            continue
        if _matches_protected(_relative_to_root(normalized, root), patterns):
            protected.append(normalized)
            keep.add(normalized)
            keep.update(_ancestors_within_root(normalized, root))
            continue
        candidates.append(normalized)

    delete = [path for path in candidates if path not in keep]
    delete_set = set(delete)
    collapsed = [
        path
        for path in delete
        if not any(ancestor in delete_set for ancestor in _ancestors_within_root(path, root_of(path)))
    ]
    return {
        "delete": sorted(collapsed),
        "delete_all": sorted(delete),
        "protected": sorted(set(protected)),
        "outside": sorted(set(outside)),
        "counts": {
            "delete": len(collapsed),
            "delete_all": len(delete),
            "protected": len(set(protected)),
            "kept": len(keep),
        },
    }


def build_preview_tree(entries, *, roots=(), max_nodes: int = MAX_PREVIEW_NODES) -> dict:
    """Дерево содержимого архива для показа человеку.

    Промежуточные каталоги создаются явно: в раскладке A запись самого корня в
    архиве отсутствует (её выбрасывает repack), и без этого дерево развалилось бы
    на плоский список. При превышении ``max_nodes`` дерево обрезается с явным
    флагом — отвечать неограниченным JSON на архив с сотнями тысяч членов нельзя.
    """
    nodes: dict[str, dict] = {}
    children: dict[str, list[dict]] = {}
    truncated = False

    def ensure(path: str, root: str, *, node_type: str, size: int) -> dict | None:
        nonlocal truncated
        existing = nodes.get(path)
        if existing is not None:
            if node_type != "directory":
                existing["type"] = node_type
                existing["size"] = size
            return existing
        if len(nodes) >= max_nodes:
            truncated = True
            return None
        node = {
            "path": path,
            "name": root if path == root else posixpath.basename(path),
            "type": node_type,
            "size": size,
            "children": [],
        }
        nodes[path] = node
        if path == root:
            children.setdefault(root, []).append(node)
            return node
        parent_path = posixpath.dirname(path)
        parent = ensure(parent_path, root, node_type="directory", size=0) if _is_within(parent_path, root) else None
        if parent is None:
            # Родитель не поместился в лимит — узел показать некуда.
            nodes.pop(path, None)
            truncated = True
            return None
        parent["children"].append(node)
        return node

    for root in roots or ():
        ensure(root, root, node_type="directory", size=0)
    for entry in sorted(entries or (), key=lambda item: item["path"]):
        root = entry.get("root")
        if root is None:
            continue
        ensure(
            entry["path"],
            root,
            node_type=entry.get("type") or "file",
            size=int(entry.get("size") or 0),
        )

    ordered_roots = list(roots or ()) or sorted(children)
    tree = [nodes[root] for root in ordered_roots if root in nodes]
    for node in nodes.values():
        node["children"].sort(key=lambda item: (item["type"] != "directory", item["name"]))
    return {"tree": tree, "node_count": len(nodes), "truncated": truncated}
