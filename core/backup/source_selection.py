from __future__ import annotations

import posixpath
import shlex
import stat
from pathlib import PurePosixPath
from typing import Iterable, Iterator


FORBIDDEN_SOURCE_ROOTS = frozenset({"/proc", "/sys", "/dev", "/run"})
MAX_SOURCE_PATH_LENGTH = 4096
MAX_SOURCE_COMPONENTS = 256
DEFAULT_TREE_PAGE_LIMIT = 100
MAX_TREE_PAGE_LIMIT = 200
MAX_DIRECTORY_CURSOR = 10_000
MAX_ROOT_ENTRIES = 2_048


class SourceSelectionError(ValueError):
    """Safe policy failure for an ordinary server Backup source."""


def normalize_source_path(raw_path: object, *, allow_root: bool = False) -> str:
    """Validate raw POSIX syntax before applying harmless slash normalization."""
    if not isinstance(raw_path, str) or not raw_path:
        raise SourceSelectionError("Source path должен быть непустой строкой")
    if len(raw_path) > MAX_SOURCE_PATH_LENGTH:
        raise SourceSelectionError("Source path слишком длинный")
    if not raw_path.startswith("/"):
        raise SourceSelectionError("Source path должен быть абсолютным POSIX path")
    if "\\" in raw_path:
        raise SourceSelectionError("Source path не должен содержать обратный слэш")
    if any(ord(char) < 32 or ord(char) == 127 for char in raw_path):
        raise SourceSelectionError("Source path содержит недопустимый управляющий символ")

    components = [component for component in raw_path.split("/") if component]
    if any(component in {".", ".."} for component in components):
        raise SourceSelectionError("Source path не должен содержать . или ..")
    if len(components) > MAX_SOURCE_COMPONENTS:
        raise SourceSelectionError("Source path содержит слишком много компонентов")

    normalized = "/" + "/".join(components) if components else "/"
    if normalized == "/" and not allow_root:
        raise SourceSelectionError("Корень / служит только для навигации и не может быть source")
    if normalized != "/":
        root = "/" + components[0]
        if root in FORBIDDEN_SOURCE_ROOTS:
            raise SourceSelectionError(f"Путь {root} запрещён для Backup")
    return normalized


def normalize_navigation_path(raw_path: object) -> str:
    return normalize_source_path(raw_path, allow_root=True)


def source_root(path: str) -> str:
    normalized = normalize_source_path(path)
    return "/" + normalized.lstrip("/").split("/", 1)[0]


def is_same_or_descendant(path: str, parent: str) -> bool:
    return path == parent or path.startswith(parent + "/")


def is_strict_descendant(path: str, parent: str) -> bool:
    return path != parent and is_same_or_descendant(path, parent)


def source_path_signature(records: Iterable[dict]) -> tuple[str, ...]:
    """Path multiset used to decide whether profile save needs fresh SFTP checks."""
    return tuple(sorted(str(record["path"]) for record in records))


def canonicalize_source_records(records: Iterable[dict]) -> list[dict]:
    """Merge exact duplicates, then apply deterministic selected-parent dominance."""
    merged: dict[str, list[str]] = {}
    seen_exclusions: dict[str, set[str]] = {}
    for record in records:
        path = str(record["path"])
        exclusions = merged.setdefault(path, [])
        seen = seen_exclusions.setdefault(path, set())
        for exclusion in record.get("exclusions", []):
            if exclusion in seen:
                continue
            seen.add(exclusion)
            exclusions.append(exclusion)

    canonical: list[dict] = []
    kept_paths: list[str] = []
    for path in sorted(merged):
        if any(is_same_or_descendant(path, parent) for parent in kept_paths):
            continue
        kept_paths.append(path)
        canonical.append({"path": path, "exclusions": merged[path]})
    return canonical


def _safe_entry_name(raw_name: object) -> str | None:
    if not isinstance(raw_name, str) or not raw_name or raw_name in {".", ".."}:
        return None
    if "/" in raw_name or "\\" in raw_name:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in raw_name):
        return None
    return raw_name


def _directory_entries(sftp, path: str) -> Iterator:
    iterator = getattr(sftp, "listdir_iter", None)
    if callable(iterator):
        try:
            return iter(iterator(path, read_aheads=10))
        except TypeError:
            return iter(iterator(path))
    return iter(sftp.listdir_attr(path))


def _mode(metadata, *, path: str) -> int:
    mode = getattr(metadata, "st_mode", None)
    if not isinstance(mode, int):
        raise SourceSelectionError(f"Не удалось определить тип объекта: {path}")
    return mode


def _listed_entry_metadata(sftp, path: str, entry):
    """Use READDIR attributes, falling back when a server omits the file mode."""
    mode = getattr(entry, "st_mode", None)
    if isinstance(mode, int):
        return entry, mode
    metadata = sftp.lstat(path)
    return metadata, _mode(metadata, path=path)


def _item(path: str, name: str, metadata) -> dict:
    mode = _mode(metadata, path=path)
    if stat.S_ISDIR(mode):
        kind = "directory"
    elif stat.S_ISREG(mode):
        kind = "file"
    else:
        raise SourceSelectionError(f"Неподдерживаемый тип объекта: {path}")
    return {
        "name": name,
        "path": path,
        "kind": kind,
        "selectable": True,
        "size": 0 if kind == "directory" else max(0, int(getattr(metadata, "st_size", 0) or 0)),
        "mtime": max(0, int(getattr(metadata, "st_mtime", 0) or 0)),
    }


def discover_allowed_root_items(sftp) -> list[dict]:
    """Return a complete bounded list of real, non-pseudo top-level directories."""
    items: list[dict] = []
    count = 0
    for entry in _directory_entries(sftp, "/"):
        count += 1
        if count > MAX_ROOT_ENTRIES:
            raise SourceSelectionError(
                "Корневой каталог содержит слишком много объектов; список roots неполон"
            )
        name = _safe_entry_name(getattr(entry, "filename", None))
        if name is None:
            continue
        path = "/" + name
        if path in FORBIDDEN_SOURCE_ROOTS:
            continue
        # READDIR attributes are only a navigation snapshot: profile save still
        # lstat-checks every selected prefix, and create repeats the check in tar's
        # sudo context. Avoid one synchronous round-trip per listed entry here.
        metadata, mode = _listed_entry_metadata(sftp, path, entry)
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            continue
        items.append(_item(path, name, metadata))
    items.sort(key=lambda item: (item["name"].casefold(), item["name"]))
    return items


def discover_allowed_roots(sftp) -> tuple[str, ...]:
    return tuple(item["path"] for item in discover_allowed_root_items(sftp))


def _validate_allowed_root(path: str, allowed_roots: Iterable[str]) -> None:
    root = source_root(path)
    if root not in frozenset(allowed_roots):
        raise SourceSelectionError(f"Путь не входит в разрешённый source space: {path}")


def validate_sftp_source(
    sftp,
    raw_path: object,
    *,
    allowed_roots: Iterable[str],
) -> dict:
    """lstat every prefix and accept only a real regular file or directory."""
    path = normalize_source_path(raw_path)
    _validate_allowed_root(path, allowed_roots)
    components = path.lstrip("/").split("/")
    chain: list[dict] = []
    for index in range(len(components)):
        prefix = "/" + "/".join(components[: index + 1])
        metadata = sftp.lstat(prefix)
        mode = _mode(metadata, path=prefix)
        if stat.S_ISLNK(mode):
            raise SourceSelectionError(f"Symlink не может быть source или его родителем: {prefix}")
        final = index == len(components) - 1
        if not final and not stat.S_ISDIR(mode):
            raise SourceSelectionError(f"Компонент source path не является каталогом: {prefix}")
        if final and not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise SourceSelectionError(f"Source должен быть обычным файлом или каталогом: {prefix}")
        chain.append(_item(prefix, components[index], metadata))
    return {"path": path, "kind": chain[-1]["kind"], "chain": chain}


def validate_sftp_sources(sftp, records: Iterable[dict]) -> list[dict]:
    """Validate every raw record before duplicate/selected-parent collapse."""
    roots = discover_allowed_roots(sftp)
    return [
        validate_sftp_source(sftp, record["path"], allowed_roots=roots)
        for record in records
    ]


def list_source_tree(
    sftp,
    raw_path: object = "/",
    *,
    cursor: int = 0,
    limit: int = DEFAULT_TREE_PAGE_LIMIT,
) -> dict:
    path = normalize_navigation_path(raw_path)
    if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0:
        raise SourceSelectionError("cursor должен быть неотрицательным целым числом")
    if cursor > MAX_DIRECTORY_CURSOR:
        raise SourceSelectionError("cursor превышает допустимый предел")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_TREE_PAGE_LIMIT:
        raise SourceSelectionError(f"limit должен быть от 1 до {MAX_TREE_PAGE_LIMIT}")

    root_items = discover_allowed_root_items(sftp)
    allowed_roots = tuple(item["path"] for item in root_items)
    if path == "/":
        if cursor:
            raise SourceSelectionError("Корневой список roots не использует pagination cursor")
        return {
            "path": "/",
            "parent": None,
            "items": root_items,
            "next_cursor": None,
            "truncated": False,
            "complete": True,
        }

    target = validate_sftp_source(sftp, path, allowed_roots=allowed_roots)
    if target["kind"] != "directory":
        raise SourceSelectionError("Путь не является каталогом")

    items: list[dict] = []
    raw_position = 0
    for entry in _directory_entries(sftp, path):
        if raw_position >= MAX_DIRECTORY_CURSOR:
            raise SourceSelectionError("Каталог слишком велик для безопасного просмотра")
        raw_position += 1
        if raw_position <= cursor:
            continue
        name = _safe_entry_name(getattr(entry, "filename", None))
        if name is None:
            continue
        child = posixpath.join(path, name)
        try:
            metadata, mode = _listed_entry_metadata(sftp, child, entry)
        except OSError:
            continue
        if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            continue
        items.append(_item(child, name, metadata))
        if len(items) >= limit:
            break

    items.sort(key=lambda item: (item["kind"] != "directory", item["name"].casefold(), item["name"]))
    page_filled = len(items) >= limit
    return {
        "path": path,
        "parent": str(PurePosixPath(path).parent),
        "items": items,
        "next_cursor": raw_position if page_filled else None,
        "truncated": page_filled,
        "complete": not page_filled,
    }


def locate_source_path(sftp, raw_path: object) -> dict:
    path = normalize_source_path(raw_path)
    roots = discover_allowed_roots(sftp)
    result = validate_sftp_source(sftp, path, allowed_roots=roots)
    return {"path": path, "kind": result["kind"], "chain": result["chain"]}


def build_privileged_source_probe(path: str) -> str:
    """Build a quoted fixed-output shell probe executed in the same sudo context as tar."""
    normalized = normalize_source_path(path)
    components = normalized.lstrip("/").split("/")
    statements = ["set -f"]
    for index in range(len(components)):
        prefix = "/" + "/".join(components[: index + 1])
        quoted = shlex.quote(prefix)
        final = index == len(components) - 1
        statements.append(f"if [ -L {quoted} ]; then printf '%s\\n' symlink; exit 41; fi")
        statements.append(f"if [ ! -e {quoted} ]; then printf '%s\\n' missing; exit 42; fi")
        if not final:
            statements.append(
                f"if [ ! -d {quoted} ]; then printf '%s\\n' intermediate_not_directory; exit 43; fi"
            )
            statements.append(
                f"if [ ! -x {quoted} ]; then printf '%s\\n' permission_denied; exit 44; fi"
            )
        elif index == 0:
            statements.append(
                f"if [ ! -d {quoted} ]; then printf '%s\\n' root_not_directory; exit 46; fi"
            )
    quoted = shlex.quote(normalized)
    statements.extend([
        f"if [ -d {quoted} ]; then",
        f"  if [ ! -r {quoted} ] || [ ! -x {quoted} ]; then printf '%s\\n' permission_denied; exit 44; fi",
        "  printf '%s\\n' directory",
        f"elif [ -f {quoted} ]; then",
        f"  if [ ! -r {quoted} ]; then printf '%s\\n' permission_denied; exit 44; fi",
        "  printf '%s\\n' file",
        "else",
        "  printf '%s\\n' unsupported_type; exit 45",
        "fi",
    ])
    return "\n".join(statements)


def parse_privileged_source_probe(path: str, exit_code: int, stdout: str, stderr: str) -> str:
    """Return directory/file or raise a source-specific safe policy failure."""
    normalized = normalize_source_path(path)
    result = str(stdout or "").strip().splitlines()
    token = result[-1].strip() if result else ""
    if int(exit_code) == 0 and token in {"directory", "file"}:
        return token
    if token == "permission_denied" or "permission" in str(stderr or "").lower():
        raise SourceSelectionError(f"{normalized}: нет прав на чтение")
    labels = {
        "symlink": "symlink запрещён",
        "missing": "не найден",
        "intermediate_not_directory": "родительский компонент не является каталогом",
        "unsupported_type": "неподдерживаемый тип объекта",
        "root_not_directory": "top-level root не является каталогом",
    }
    reason = labels.get(token, "не найден или недоступен")
    raise SourceSelectionError(f"{normalized}: {reason}")
