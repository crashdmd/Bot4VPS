from __future__ import annotations

import base64
import hashlib
import json
import os
import posixpath
import sys
import threading
from array import array
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .errors import BackupError, ErrorCode
from .ids import validate_id
from .manifest import (
    _normalized_member_name,
    validate_managed_member_namespace,
    validate_manifest,
    validate_manifest_member_scope,
    validate_ordered_member_graph,
)
from .restore_plan import (
    LAYOUT_MANIFEST_PAYLOAD,
    MAX_SELECTION_PATHS,
    build_bulk_restore_policy,
    build_restore_scope,
    map_restore_member,
    online_restore_policy_revision,
)
from .time_utils import parse_utc_timestamp, utc_timestamp
from .validation import validate_storage_key


ARCHIVE_INVENTORY_SCHEMA_VERSION = 2
MAX_ARCHIVE_INVENTORY_LEGACY_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_INVENTORY_V2_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_INVENTORY_HEADER_BYTES = 64 * 1024
MAX_ARCHIVE_INVENTORY_QUERY_LIMIT = 200
DEFAULT_ARCHIVE_INVENTORY_QUERY_LIMIT = 100
MAX_ARCHIVE_INVENTORY_CURSOR_LENGTH = 1024
MAX_ARCHIVE_INVENTORY_CACHE_ENTRIES = 4
MAX_ARCHIVE_INVENTORY_CACHE_BYTES = 768 * 1024 * 1024
MAX_ARCHIVE_INVENTORY_SNAPSHOT_BYTES = 752 * 1024 * 1024
HEAVY_ARCHIVE_INVENTORY_BYTES = 64 * 1024 * 1024

LAYOUT_FIXED_ABSOLUTE = 0
LAYOUT_RELATIVE_TARGET_ROOT = 1

MEMBER_FILE = 0
MEMBER_DIRECTORY = 1
MEMBER_SYMLINK = 2
MEMBER_HARDLINK = 3
_MEMBER_TAG_BY_TYPE = {
    "file": MEMBER_FILE,
    "directory": MEMBER_DIRECTORY,
    "symlink": MEMBER_SYMLINK,
    "hardlink": MEMBER_HARDLINK,
}
_MEMBER_TYPE_BY_TAG = {value: key for key, value in _MEMBER_TAG_BY_TYPE.items()}

NODE_FILE = 0
NODE_DIRECTORY = 1
NODE_FLAG_EXPLICIT = 0x01
NODE_FLAG_SELECTABLE = 0x02
NODE_FLAG_BLOCKED = 0x04
NODE_FLAG_HAS_SELECTABLE_DESCENDANTS = 0x08
NODE_FLAGS_ALL = (
    NODE_FLAG_EXPLICIT
    | NODE_FLAG_SELECTABLE
    | NODE_FLAG_BLOCKED
    | NODE_FLAG_HAS_SELECTABLE_DESCENDANTS
)

POLICY_FIXED = 0
POLICY_RELATIVE = 1
POLICY_SUMMARY_HAS_SELECTABLE = 0x01
POLICY_SUMMARY_HAS_BLOCKED = 0x02
POLICY_SUMMARY_HAS_MIXED = 0x04
POLICY_SUMMARY_ALL = (
    POLICY_SUMMARY_HAS_SELECTABLE
    | POLICY_SUMMARY_HAS_BLOCKED
    | POLICY_SUMMARY_HAS_MIXED
)

_TOP_LEVEL_KEYS = {"header", "manifest", "members", "view", "policy_projection"}
_HEADER_KEYS = {
    "schema_version",
    "created_at",
    "revision",
    "source",
    "archive",
    "layout",
    "policy_revision",
}
_ARCHIVE_KEYS = {"sha256", "bytes", "format"}
_VIEW_KEYS = {"root_count", "nodes"}
_HEX_DIGITS = frozenset("0123456789abcdef")

# Mutable builder row. Rows are finalized in place into the persisted codec.
_T_PATH = 0
_T_PARENT = 1
_T_TYPE = 2
_T_EXPLICIT = 3
_T_MEMBER = 4
_T_OWN_MEMBERS = 5
_T_OWN_FILES = 6
_T_OWN_BYTES = 7
_T_FIRST_CHILD = 8
_T_CHILD_COUNT = 9


class _NodeColumn:
    """Sequence view over one compact node column without materializing a list."""

    def __init__(self, nodes: list[list], index: int):
        self._nodes = nodes
        self._index = index

    def __len__(self) -> int:
        return len(self._nodes)

    def __getitem__(self, index: int):
        return self._nodes[index][self._index]

    def __iter__(self):
        index = self._index
        for node in self._nodes:
            yield node[index]


class _PolicyMemberCountColumn:
    """Physical selection cardinality for compact file/directory nodes."""

    def __init__(self, nodes: list[list]):
        self._nodes = nodes

    def __len__(self) -> int:
        return len(self._nodes)

    def __getitem__(self, index: int) -> int:
        node = self._nodes[index]
        return 1 if node[2] == NODE_FILE else node[5]

    def __iter__(self):
        for node in self._nodes:
            yield 1 if node[2] == NODE_FILE else node[5]


def _invalid(message: str) -> BackupError:
    return BackupError(ErrorCode.ARCHIVE_INVALID, message)


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in _HEX_DIGITS for char in value)
    )


def _validate_source(source: object) -> dict:
    if not isinstance(source, dict):
        raise _invalid("Некорректный source archive inventory")
    kind = source.get("kind")
    try:
        if kind == "managed":
            backup_type = source.get("type")
            expected = {
                "kind",
                "backup_id",
                "type",
                "artifact_version",
                "storage_key",
            }
            if backup_type == "server":
                expected.add("server_id")
            if set(source) != expected or backup_type not in {"server", "bot4vps"}:
                raise _invalid("Некорректный managed source archive inventory")
            validate_id(source.get("backup_id"), field="inventory backup_id")
            if backup_type == "server":
                validate_id(source.get("server_id"), field="inventory server_id")
            version = source.get("artifact_version")
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                raise _invalid("Некорректный artifact_version archive inventory")
            storage_key = validate_storage_key(
                source.get("storage_key"),
                error_code=ErrorCode.ARCHIVE_INVALID,
            )
            expected_key = (
                f"servers/{source['server_id']}/{source['backup_id']}.tar.gz"
                if backup_type == "server"
                else f"bot4vps/{source['backup_id']}.tar.gz"
            )
            if storage_key != expected_key:
                raise _invalid("Storage key archive inventory не является canonical")
        elif kind == "imported":
            if set(source) != {"kind", "entry_key", "destination"}:
                raise _invalid("Некорректный imported source archive inventory")
            validate_id(source.get("entry_key"), field="inventory entry_key")
            destination = source.get("destination")
            if not isinstance(destination, dict):
                raise _invalid("Некорректный destination archive inventory")
            scope = destination.get("scope")
            expected = {"scope", "server_id"} if scope == "server" else {"scope"}
            if scope not in {"server", "bot4vps"} or set(destination) != expected:
                raise _invalid("Некорректный destination archive inventory")
            if scope == "server":
                validate_id(
                    destination.get("server_id"),
                    field="inventory destination.server_id",
                )
        else:
            raise _invalid("Неизвестный source kind archive inventory")
    except ValueError as exc:
        raise _invalid("Некорректная identity archive inventory") from exc
    return source


def _validate_archive_binding(archive: object) -> dict:
    if not isinstance(archive, dict) or set(archive) != _ARCHIVE_KEYS:
        raise _invalid("Некорректная archive binding inventory")
    if not _is_digest(archive.get("sha256")):
        raise _invalid("Некорректный SHA-256 archive inventory")
    if not _is_nonnegative_int(archive.get("bytes")):
        raise _invalid("Некорректный размер archive inventory")
    if archive.get("format") not in {"tar", "tar.gz"}:
        raise _invalid("Некорректный format archive inventory")
    return archive


def _validate_created_at(value: object) -> str:
    try:
        parsed = parse_utc_timestamp(value)
    except (TypeError, ValueError) as exc:
        raise _invalid("Некорректный created_at archive inventory") from exc
    if utc_timestamp(parsed) != value:
        raise _invalid("created_at archive inventory не canonical")
    return value


def _validate_compact_members(members: object) -> list[list]:
    if not isinstance(members, list) or not members:
        raise _invalid("Archive inventory не содержит ordered members")
    for row in members:
        if not isinstance(row, list) or len(row) not in {3, 4}:
            raise _invalid("Некорректная compact member row")
        name, member_tag, size = row[:3]
        if not isinstance(name, str) or member_tag not in _MEMBER_TYPE_BY_TAG:
            raise _invalid("Некорректные name/type compact member")
        if not _is_nonnegative_int(size):
            raise _invalid("Некорректный размер compact member")
        linked = member_tag in {MEMBER_SYMLINK, MEMBER_HARDLINK}
        if linked != (len(row) == 4):
            raise _invalid("Длина compact member row не соответствует type")
        if linked and not isinstance(row[3], str):
            raise _invalid("Некорректная link target compact member")

    validate_ordered_member_graph(
        members,
        name_of=lambda row: row[0],
        type_of=lambda row: _MEMBER_TYPE_BY_TAG[row[1]],
        linkname_of=lambda row: row[3] if len(row) == 4 else None,
    )
    return members


def _validate_manifest_source_binding(
    *,
    manifest: dict,
    source: dict,
    archive: dict,
) -> None:
    if source.get("kind") != "managed":
        return
    if (
        manifest.get("backup_id") != source.get("backup_id")
        or manifest.get("type") != source.get("type")
        or manifest.get("archive", {}).get("format") != archive.get("format")
    ):
        raise _invalid("Managed inventory не соответствует Manifest identity")
    if source.get("type") == "server" and (
        manifest.get("source", {}).get("server_id") != source.get("server_id")
    ):
        raise _invalid("Managed inventory не соответствует Manifest server identity")


def _validate_fixed_member_scope(members: list[list], manifest: dict) -> None:
    validate_managed_member_namespace(members, name_of=lambda row: row[0])
    validate_manifest_member_scope(
        members,
        manifest=manifest,
        name_of=lambda row: row[0],
        type_of=lambda row: _MEMBER_TYPE_BY_TAG[row[1]],
    )


def compact_member_rows(
    members: list[dict],
    *,
    consume: bool = False,
) -> list[list]:
    """Encode validated member dictionaries, optionally consuming their owned list."""
    if not isinstance(members, list) or not members:
        raise _invalid("Список members для archive inventory пуст")
    for member in members:
        if not isinstance(member, dict):
            raise _invalid("Некорректный member для archive inventory")
        member_type = member.get("type")
        expected = {"name", "type", "size"}
        if member_type in {"symlink", "hardlink"}:
            expected.add("linkname")
        if set(member) != expected or member_type not in _MEMBER_TAG_BY_TYPE:
            raise _invalid("Member не соответствует compact inventory codec")
        if not _is_nonnegative_int(member.get("size")):
            raise _invalid("Некорректный размер member archive inventory")

    validate_ordered_member_graph(
        members,
        name_of=lambda member: member.get("name"),
        type_of=lambda member: member.get("type"),
        linkname_of=lambda member: member.get("linkname"),
        set_name=lambda member, normalized: member.__setitem__("name", normalized),
    )

    rows = members if consume else [None] * len(members)
    for index in range(len(members)):
        member = members[index]
        member_type = member["type"]
        row = [
            member["name"],
            _MEMBER_TAG_BY_TYPE[member_type],
            member["size"],
        ]
        if member_type in {"symlink", "hardlink"}:
            row.append(member["linkname"])
        rows[index] = row
    return rows


def expand_archive_inventory_members(
    inventory: dict,
    *,
    validate: bool = True,
    consume_members: bool = False,
) -> list[dict]:
    """Expand compact rows only for legacy physical-preview consumers."""
    if validate:
        inventory = validate_archive_inventory(inventory)
    members = inventory.get("members") if isinstance(inventory, dict) else None
    if not isinstance(members, list):
        raise _invalid("Archive inventory не содержит compact members")

    # Validate the complete codec before consuming the caller-owned list. A
    # failed v2 build can therefore roll compact rows back into v1 metadata
    # without retaining a second full member list on the successful path.
    for row in members:
        if not isinstance(row, list) or len(row) not in {3, 4}:
            raise _invalid("Некорректная compact member row")
        member_type = _MEMBER_TYPE_BY_TAG.get(row[1])
        if member_type is None:
            raise _invalid("Некорректный type compact member")
        if (member_type in {"symlink", "hardlink"}) != (len(row) == 4):
            raise _invalid("Длина compact member row не соответствует type")

    expanded = members if consume_members else [None] * len(members)
    for index in range(len(members)):
        row = members[index]
        member_type = _MEMBER_TYPE_BY_TAG[row[1]]
        member = {
            "name": row[0],
            "type": member_type,
            "size": row[2],
        }
        if len(row) == 4:
            member["linkname"] = row[3]
        expanded[index] = member
    return expanded


def _relative_member_path(name: object) -> str:
    try:
        return _normalized_member_name(name)
    except BackupError as exc:
        raise _invalid("Небезопасный relative member path archive inventory") from exc


def _parent_path(path: str, layout: int) -> str | None:
    if layout == LAYOUT_RELATIVE_TARGET_ROOT:
        return None if path == "" else posixpath.dirname(path)
    parent = posixpath.dirname(path)
    return None if parent == path else parent


def _node_order_key(row: list) -> tuple:
    path = row[_T_PATH]
    name = posixpath.basename(path) or path
    return (row[_T_TYPE] != NODE_DIRECTORY, name.casefold(), name, path)


def _classify_fixed_roots(members: list[list], scope) -> dict[str, str]:
    states = {root: [None, False, 0] for root in scope.roots}
    mapped_count = 0
    for row in members:
        mapped = map_restore_member(row[0], scope)
        if mapped is None:
            continue
        _name, path, root = mapped
        mapped_count += 1
        state = states[root]
        if path == root:
            state[0] = _MEMBER_TYPE_BY_TAG[row[1]]
            state[2] += 1
        else:
            state[1] = True
    if mapped_count == 0:
        raise _invalid("Archive inventory не содержит восстанавливаемых members")

    kinds: dict[str, str] = {}
    for root, (exact_type, nested, exact_count) in states.items():
        if exact_count > 1:
            raise _invalid("Корень archive inventory имеет duplicate mapped path")
        if exact_type is not None and exact_type != "directory":
            if nested:
                raise _invalid("Вид корня archive inventory неоднозначен")
            kinds[root] = "file"
        else:
            kinds[root] = "directory"
    return kinds


def _build_compact_view(
    members: list[list],
    *,
    manifest: dict | None,
    layout: int,
) -> tuple[int, list[list], list]:
    scope = build_restore_scope(manifest=manifest) if layout == LAYOUT_FIXED_ABSOLUTE else None
    root_kinds = (
        _classify_fixed_roots(members, scope)
        if scope is not None
        else {"": "directory"}
    )

    nodes: list[list] = []
    path_to_id: dict[str, int] = {}

    def add_node(
        path: str,
        parent_id: int,
        node_type: int,
        *,
        explicit: bool = False,
        member_index: int = -1,
        size: int = 0,
    ) -> int:
        node_id = len(nodes)
        path_to_id[path] = node_id
        nodes.append([
            path,
            parent_id,
            node_type,
            explicit,
            member_index,
            0,
            0,
            size if node_type == NODE_FILE else 0,
            -1,
            0,
        ])
        return node_id

    def ensure_directory(path: str, root: str) -> int:
        existing = path_to_id.get(path)
        if existing is not None:
            if nodes[existing][_T_TYPE] != NODE_DIRECTORY:
                raise _invalid("Вид path archive inventory неоднозначен")
            return existing

        chain: list[str] = []
        current = path
        while current not in path_to_id:
            chain.append(current)
            if current == root:
                break
            parent = _parent_path(current, layout)
            if parent is None:
                raise _invalid("Directory path выходит за compact root")
            current = parent
        parent_id = path_to_id.get(current, -1)
        if chain and chain[-1] == current and current in path_to_id:
            chain.pop()
        for value in reversed(chain):
            node_parent = -1 if value == root else parent_id
            parent_id = add_node(value, node_parent, NODE_DIRECTORY)
        result = path_to_id.get(path)
        if result is None:
            raise _invalid("Не удалось построить compact directory hierarchy")
        return result

    for root, kind in root_kinds.items():
        if kind == "directory":
            add_node(root, -1, NODE_DIRECTORY)

    def mapped_row(row: list):
        if scope is not None:
            return map_restore_member(row[0], scope)
        path = _relative_member_path(row[0])
        return row[0], path, ""

    for member_index, row in enumerate(members):
        mapped = mapped_row(row)
        if mapped is None:
            continue
        _name, path, root = mapped

        member_type = _MEMBER_TYPE_BY_TAG[row[1]]
        root_kind = root_kinds[root]
        if member_type == "directory":
            if root_kind != "directory":
                raise _invalid("Directory member относится к file root")
            node_id = ensure_directory(path, root)
            node = nodes[node_id]
            if node[_T_EXPLICIT] or node[_T_MEMBER] != -1:
                raise _invalid("Duplicate explicit directory archive inventory")
            node[_T_EXPLICIT] = True
            node[_T_MEMBER] = member_index
        elif member_type == "file":
            if path in path_to_id:
                raise _invalid("Вид file path archive inventory неоднозначен")
            parent = _parent_path(path, layout)
            if path == root and root_kind == "file":
                parent_id = -1
            else:
                if parent is None or root_kind != "directory":
                    raise _invalid("File member не относится к directory root")
                parent_id = ensure_directory(parent, root)
            add_node(
                path,
                parent_id,
                NODE_FILE,
                explicit=True,
                member_index=member_index,
                size=row[2],
            )
        else:
            parent = _parent_path(path, layout)
            if path != root or root_kind == "directory":
                if parent is None:
                    parent = root
                ensure_directory(parent, root)

    if not nodes:
        return 0, [], []

    # Attribute every physical member after the hierarchy is complete. A hardlink
    # may share a path with an implicit directory created by a later member; the
    # physical selected-subtree contract includes that exact-path hardlink.
    hardlink_dependencies: list[tuple[int, str]] = []
    for row in members:
        mapped = mapped_row(row)
        if mapped is None:
            continue
        _name, path, root = mapped
        member_type = _MEMBER_TYPE_BY_TAG[row[1]]
        node_id = path_to_id.get(path, -1)
        owner_id = -1
        if member_type == "directory":
            owner_id = node_id
        elif member_type == "file":
            parent_id = nodes[node_id][_T_PARENT]
            if parent_id >= 0:
                owner_id = parent_id
        else:
            if node_id >= 0 and nodes[node_id][_T_TYPE] == NODE_DIRECTORY:
                owner_id = node_id
            else:
                parent = _parent_path(path, layout)
                if parent is not None:
                    owner_id = path_to_id.get(parent, -1)

        if owner_id >= 0:
            owner = nodes[owner_id]
            owner[_T_OWN_MEMBERS] += 1
            if member_type == "file":
                owner[_T_OWN_FILES] += 1
                owner[_T_OWN_BYTES] += row[2]
            elif member_type == "hardlink":
                if scope is not None:
                    target_mapped = map_restore_member(row[3], scope)
                    if target_mapped is None:
                        raise _invalid("Hardlink target указывает на manifest")
                    target_path = target_mapped[1]
                else:
                    target_path = _relative_member_path(row[3])
                hardlink_dependencies.append((owner_id, target_path))

    for node_id in range(len(nodes) - 1, -1, -1):
        node = nodes[node_id]
        if node[_T_TYPE] != NODE_DIRECTORY:
            continue
        parent_id = node[_T_PARENT]
        if parent_id >= 0:
            parent = nodes[parent_id]
            if parent[_T_TYPE] != NODE_DIRECTORY:
                raise _invalid("Directory parent archive inventory не является directory")
            parent[_T_OWN_MEMBERS] += node[_T_OWN_MEMBERS]
            parent[_T_OWN_FILES] += node[_T_OWN_FILES]
            parent[_T_OWN_BYTES] += node[_T_OWN_BYTES]

    children: dict[int, list[int]] = {}
    roots: list[int] = []
    for node_id, node in enumerate(nodes):
        parent_id = node[_T_PARENT]
        if parent_id < 0:
            roots.append(node_id)
        else:
            children.setdefault(parent_id, []).append(node_id)
    roots.sort(key=lambda node_id: _node_order_key(nodes[node_id]))
    for child_ids in children.values():
        child_ids.sort(key=lambda node_id: _node_order_key(nodes[node_id]))

    order = list(roots)
    cursor = 0
    while cursor < len(order):
        old_id = order[cursor]
        direct = children.get(old_id, ())
        nodes[old_id][_T_FIRST_CHILD] = len(order) if direct else -1
        nodes[old_id][_T_CHILD_COUNT] = len(direct)
        order.extend(direct)
        cursor += 1
    if len(order) != len(nodes):
        raise _invalid("Compact hierarchy содержит недостижимые nodes")

    old_to_new = array("q", [-1]) * len(nodes)
    for new_id, old_id in enumerate(order):
        old_to_new[old_id] = new_id
    nodes = [nodes[old_id] for old_id in order]

    for node in nodes:
        old_parent = node[_T_PARENT]
        node[_T_PARENT] = -1 if old_parent < 0 else old_to_new[old_parent]
        if node[_T_FIRST_CHILD] >= 0:
            node[_T_FIRST_CHILD] = old_to_new[order[node[_T_FIRST_CHILD]]]

    mapped_dependencies = [
        (old_to_new[owner_id], target_path)
        for owner_id, target_path in hardlink_dependencies
    ]

    if layout == LAYOUT_FIXED_ABSOLUTE:
        policy = build_bulk_restore_policy(
            node_paths=_NodeColumn(nodes, _T_PATH),
            node_types=_NodeColumn(nodes, _T_TYPE),
            parent_ids=_NodeColumn(nodes, _T_PARENT),
            node_member_counts=_PolicyMemberCountColumn(nodes),
            hardlink_dependencies=mapped_dependencies,
        )
    else:
        policy = None

    for node_id, node in enumerate(nodes):
        explicit = NODE_FLAG_EXPLICIT if node[_T_EXPLICIT] else 0
        policy_flags = 0
        if policy is not None:
            if policy["selectable"][node_id]:
                policy_flags |= NODE_FLAG_SELECTABLE
            if policy["blocked"][node_id]:
                policy_flags |= NODE_FLAG_BLOCKED
            if policy["has_selectable_descendants"][node_id]:
                policy_flags |= NODE_FLAG_HAS_SELECTABLE_DESCENDANTS
        flags = explicit | policy_flags
        if node[_T_TYPE] == NODE_FILE:
            node[:] = [
                node[_T_PATH],
                node[_T_PARENT],
                NODE_FILE,
                flags,
                node[_T_MEMBER],
                node[_T_OWN_BYTES],
            ]
        else:
            node[:] = [
                node[_T_PATH],
                node[_T_PARENT],
                NODE_DIRECTORY,
                flags,
                node[_T_MEMBER],
                node[_T_OWN_MEMBERS],
                node[_T_OWN_FILES],
                node[_T_OWN_BYTES],
                node[_T_FIRST_CHILD],
                node[_T_CHILD_COUNT],
            ]

    root_count = len(roots)
    if policy is None:
        projection = [POLICY_RELATIVE]
    else:
        frontier = policy["frontier"]
        projection = [
            POLICY_FIXED,
            policy["summary"],
            len(frontier),
            list(frontier) if len(frontier) <= MAX_SELECTION_PATHS else None,
        ]
    return root_count, nodes, projection


def _revision_payload(
    *,
    source: dict,
    archive: dict,
    layout: int,
    manifest: dict | None,
    members: list[list],
    root_count: int,
    nodes: list[list],
    policy_projection: list,
    policy_revision: str,
):
    return [
        ARCHIVE_INVENTORY_SCHEMA_VERSION,
        source,
        archive,
        layout,
        manifest,
        members,
        root_count,
        nodes,
        policy_projection,
        policy_revision,
    ]


def inventory_revision(
    *,
    source: dict,
    archive: dict,
    layout: int,
    manifest: dict | None,
    members: list[list],
    root_count: int,
    nodes: list[list],
    policy_projection: list,
    policy_revision: str,
) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(b"bot4vps:archive-inventory:v2\0")
    encoder = json.JSONEncoder(
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload = _revision_payload(
        source=source,
        archive=archive,
        layout=layout,
        manifest=manifest,
        members=members,
        root_count=root_count,
        nodes=nodes,
        policy_projection=policy_projection,
        policy_revision=policy_revision,
    )
    for chunk in encoder.iterencode(payload):
        digest.update(chunk.encode("utf-8"))
    return digest.hexdigest()


def build_archive_inventory(
    *,
    members: list[dict],
    manifest: dict | None,
    source: dict,
    archive: dict,
    created_at: str | None = None,
    consume_members: bool = False,
) -> dict:
    """Build v2 directly from one owned ordered member graph, without a full plan."""
    source = dict(_validate_source(source))
    archive = dict(_validate_archive_binding(archive))
    if manifest is not None:
        manifest = validate_manifest(manifest)
        layout = LAYOUT_FIXED_ABSOLUTE
        _validate_manifest_source_binding(
            manifest=manifest,
            source=source,
            archive=archive,
        )
    else:
        if source.get("kind") != "imported":
            raise _invalid("Managed archive inventory требует Manifest")
        layout = LAYOUT_RELATIVE_TARGET_ROOT

    compact_members = compact_member_rows(members, consume=consume_members)
    if layout == LAYOUT_FIXED_ABSOLUTE:
        _validate_fixed_member_scope(compact_members, manifest)
    root_count, nodes, policy_projection = _build_compact_view(
        compact_members,
        manifest=manifest,
        layout=layout,
    )
    policy_revision = online_restore_policy_revision()
    revision = inventory_revision(
        source=source,
        archive=archive,
        layout=layout,
        manifest=manifest,
        members=compact_members,
        root_count=root_count,
        nodes=nodes,
        policy_projection=policy_projection,
        policy_revision=policy_revision,
    )
    return {
        "header": {
            "schema_version": ARCHIVE_INVENTORY_SCHEMA_VERSION,
            "created_at": _validate_created_at(created_at or utc_timestamp()),
            "revision": revision,
            "source": source,
            "archive": archive,
            "layout": layout,
            "policy_revision": policy_revision,
        },
        "manifest": manifest,
        "members": compact_members,
        "view": {"root_count": root_count, "nodes": nodes},
        "policy_projection": policy_projection,
    }


def _validate_node_path(path: object, *, layout: int, root: bool) -> str:
    if not isinstance(path, str):
        raise _invalid("Некорректный path compact node")
    if layout == LAYOUT_RELATIVE_TARGET_ROOT and path == "":
        if not root:
            raise _invalid("Relative target root допустим только как root node")
        return path
    if layout == LAYOUT_RELATIVE_TARGET_ROOT:
        normalized = _relative_member_path(path)
        if normalized != path:
            raise _invalid("Relative compact node path не canonical")
        return path
    try:
        from .restore_plan import normalize_restore_root

        normalized = normalize_restore_root(path, field="inventory node path")
    except BackupError as exc:
        raise _invalid("Некорректный absolute compact node path") from exc
    if normalized != path:
        raise _invalid("Absolute compact node path не canonical")
    return path


def _mapped_member_path(row: list, *, layout: int, scope):
    if layout == LAYOUT_FIXED_ABSOLUTE:
        return map_restore_member(row[0], scope)
    return row[0], _relative_member_path(row[0]), ""


def _validate_nodes_and_policy(
    *,
    members: list[list],
    manifest: dict | None,
    layout: int,
    root_count: int,
    nodes: object,
    policy_projection: object,
) -> list[list]:
    if not isinstance(nodes, list):
        raise _invalid("Compact inventory nodes должен быть array")
    if not _is_nonnegative_int(root_count) or root_count > len(nodes):
        raise _invalid("Некорректный root_count compact inventory")

    path_to_id: dict[str, int] = {}
    first_child = array("q", [-1]) * len(nodes)
    actual_children = array("q", [0]) * len(nodes)
    previous_parent = -1
    for node_id, row in enumerate(nodes):
        if not isinstance(row, list) or len(row) not in {6, 10}:
            raise _invalid("Некорректная compact node row")
        path, parent_id, node_type, flags, member_index = row[:5]
        expected_length = 6 if node_type == NODE_FILE else 10 if node_type == NODE_DIRECTORY else 0
        if len(row) != expected_length:
            raise _invalid("Длина compact node row не соответствует type")
        if (
            not isinstance(parent_id, int)
            or isinstance(parent_id, bool)
            or parent_id < -1
            or parent_id >= node_id
        ):
            raise _invalid("Некорректный parent_id compact node")
        is_root = node_id < root_count
        if is_root != (parent_id == -1):
            raise _invalid("Root compact nodes не образуют contiguous prefix")
        _validate_node_path(path, layout=layout, root=is_root)
        if path in path_to_id:
            raise _invalid("Duplicate compact node path")
        path_to_id[path] = node_id
        if not isinstance(flags, int) or isinstance(flags, bool) or flags & ~NODE_FLAGS_ALL:
            raise _invalid("Некорректные flags compact node")
        if layout == LAYOUT_RELATIVE_TARGET_ROOT and flags & ~NODE_FLAG_EXPLICIT:
            raise _invalid("Relative inventory содержит persisted policy flags")
        if not isinstance(member_index, int) or isinstance(member_index, bool):
            raise _invalid("Некорректный member_index compact node")
        if parent_id >= 0:
            if nodes[parent_id][2] != NODE_DIRECTORY:
                raise _invalid("Parent compact node не является directory")
            if parent_id < previous_parent:
                raise _invalid("Direct children compact nodes не contiguous")
            previous_parent = parent_id
            if first_child[parent_id] < 0:
                first_child[parent_id] = node_id
            actual_children[parent_id] += 1

        if node_type == NODE_FILE:
            if not _is_nonnegative_int(row[5]):
                raise _invalid("Некорректный size compact file node")
        else:
            if not all(_is_nonnegative_int(value) for value in row[5:8]):
                raise _invalid("Некорректные aggregates compact directory")
            declared_first, declared_count = row[8:10]
            if (
                not isinstance(declared_first, int)
                or isinstance(declared_first, bool)
                or not _is_nonnegative_int(declared_count)
                or (declared_count == 0) != (declared_first == -1)
                or (declared_count > 0 and declared_first < 0)
            ):
                raise _invalid("Некорректный child range compact directory")

    for node_id, row in enumerate(nodes):
        if row[2] != NODE_DIRECTORY:
            continue
        expected_first = first_child[node_id]
        expected_count = actual_children[node_id]
        if row[8] != expected_first or row[9] != expected_count:
            raise _invalid("Child range compact directory не соответствует hierarchy")
        if expected_count:
            previous_key = None
            for child_id in range(expected_first, expected_first + expected_count):
                if child_id >= len(nodes) or nodes[child_id][1] != node_id:
                    raise _invalid("Child range compact directory не contiguous")
                child = nodes[child_id]
                name = posixpath.basename(child[0]) or child[0]
                key = (child[2] != NODE_DIRECTORY, name.casefold(), name, child[0])
                if previous_key is not None and key <= previous_key:
                    raise _invalid("Direct children compact directory не sorted")
                previous_key = key

    scope = build_restore_scope(manifest=manifest) if layout == LAYOUT_FIXED_ABSOLUTE else None
    expected_nodes = bytearray(len(nodes))
    expected_directory_members = array("q", [-1]) * len(nodes)
    expected_file_members = array("q", [-1]) * len(nodes)
    own_members = array("q", [0]) * len(nodes)
    own_files = array("q", [0]) * len(nodes)
    own_bytes = array("q", [0]) * len(nodes)
    hardlink_dependencies: list[tuple[int, str]] = []

    def mark_ancestors(node_id: int) -> None:
        current = node_id
        while current >= 0 and not expected_nodes[current]:
            expected_nodes[current] = 1
            current = nodes[current][1]

    if scope is not None:
        for root, kind in _classify_fixed_roots(members, scope).items():
            if kind != "directory":
                continue
            node_id = path_to_id.get(root)
            if (
                node_id is None
                or node_id >= root_count
                or nodes[node_id][2] != NODE_DIRECTORY
            ):
                raise _invalid("Directory root отсутствует в compact hierarchy")
            mark_ancestors(node_id)

    for member_index, row in enumerate(members):
        mapped = _mapped_member_path(row, layout=layout, scope=scope)
        if mapped is None:
            continue
        _name, path, root = mapped
        member_type = _MEMBER_TYPE_BY_TAG[row[1]]
        node_id = path_to_id.get(path, -1)
        owner_id = -1
        if member_type == "directory":
            if node_id < 0 or nodes[node_id][2] != NODE_DIRECTORY:
                raise _invalid("Directory member отсутствует в compact hierarchy")
            if expected_directory_members[node_id] >= 0:
                raise _invalid("Duplicate mapped directory compact member")
            expected_directory_members[node_id] = member_index
            owner_id = node_id
            mark_ancestors(node_id)
        elif member_type == "file":
            if node_id < 0 or nodes[node_id][2] != NODE_FILE:
                raise _invalid("File member отсутствует в compact hierarchy")
            if expected_file_members[node_id] >= 0:
                raise _invalid("Duplicate mapped file compact member")
            expected_file_members[node_id] = member_index
            expected_nodes[node_id] = 1
            parent_id = nodes[node_id][1]
            if parent_id >= 0:
                owner_id = parent_id
                mark_ancestors(parent_id)
        else:
            if node_id >= 0 and nodes[node_id][2] == NODE_DIRECTORY:
                owner_id = node_id
            else:
                parent = _parent_path(path, layout)
                if parent is not None:
                    owner_id = path_to_id.get(parent, -1)
            if owner_id >= 0:
                if nodes[owner_id][2] != NODE_DIRECTORY:
                    raise _invalid("Link member owner не является directory")
                mark_ancestors(owner_id)
            if member_type == "hardlink" and owner_id >= 0:
                target = _mapped_member_path(
                    [row[3], MEMBER_FILE, 0],
                    layout=layout,
                    scope=scope,
                )
                if target is None:
                    raise _invalid("Hardlink target указывает на manifest")
                hardlink_dependencies.append((owner_id, target[1]))

        if owner_id >= 0:
            own_members[owner_id] += 1
            if member_type == "file":
                own_files[owner_id] += 1
                own_bytes[owner_id] += row[2]

    if layout == LAYOUT_RELATIVE_TARGET_ROOT and nodes:
        root_id = path_to_id.get("")
        if root_id is None or root_id >= root_count:
            raise _invalid("Relative inventory не содержит target-root node")
        mark_ancestors(root_id)

    for node_id, row in enumerate(nodes):
        if not expected_nodes[node_id]:
            raise _invalid("Compact hierarchy содержит лишний node")
        explicit = bool(row[3] & NODE_FLAG_EXPLICIT)
        if row[2] == NODE_FILE:
            member_index = expected_file_members[node_id]
            if member_index < 0 or row[4] != member_index or not explicit:
                raise _invalid("File node member reference не соответствует members")
            if row[5] != members[member_index][2]:
                raise _invalid("File node size не соответствует member")
        else:
            member_index = expected_directory_members[node_id]
            if member_index >= 0:
                if row[4] != member_index or not explicit:
                    raise _invalid("Explicit directory reference не соответствует member")
            elif row[4] != -1 or explicit:
                raise _invalid("Implicit directory содержит member reference")

    for node_id in range(len(nodes) - 1, -1, -1):
        row = nodes[node_id]
        if row[2] != NODE_DIRECTORY:
            continue
        if row[5] != own_members[node_id] or row[6] != own_files[node_id] or row[7] != own_bytes[node_id]:
            raise _invalid("Directory aggregates не соответствуют physical members")
        parent_id = row[1]
        if parent_id >= 0:
            own_members[parent_id] += own_members[node_id]
            own_files[parent_id] += own_files[node_id]
            own_bytes[parent_id] += own_bytes[node_id]

    if layout == LAYOUT_FIXED_ABSOLUTE:
        policy = build_bulk_restore_policy(
            node_paths=_NodeColumn(nodes, 0),
            node_types=_NodeColumn(nodes, 2),
            parent_ids=_NodeColumn(nodes, 1),
            node_member_counts=_PolicyMemberCountColumn(nodes),
            hardlink_dependencies=hardlink_dependencies,
        )
        for node_id, row in enumerate(nodes):
            expected_flags = row[3] & NODE_FLAG_EXPLICIT
            if policy["selectable"][node_id]:
                expected_flags |= NODE_FLAG_SELECTABLE
            if policy["blocked"][node_id]:
                expected_flags |= NODE_FLAG_BLOCKED
            if policy["has_selectable_descendants"][node_id]:
                expected_flags |= NODE_FLAG_HAS_SELECTABLE_DESCENDANTS
            if row[3] != expected_flags:
                raise _invalid("Persisted policy flags не соответствуют current policy")
        frontier = policy["frontier"]
        expected_projection = [
            POLICY_FIXED,
            policy["summary"],
            len(frontier),
            list(frontier) if len(frontier) <= MAX_SELECTION_PATHS else None,
        ]
    else:
        expected_projection = [POLICY_RELATIVE]
    if policy_projection != expected_projection:
        raise _invalid("Policy projection archive inventory не соответствует hierarchy")
    return nodes


def validate_archive_inventory(
    value: object,
    *,
    expected_source: dict | None = None,
    expected_archive: dict | None = None,
) -> dict:
    """Deep-validate one parsed v2 document without expanding compact members."""
    if not isinstance(value, dict) or set(value) != _TOP_LEVEL_KEYS:
        raise _invalid("Archive inventory не соответствует закрытой schema v2")
    header = value.get("header")
    if not isinstance(header, dict) or set(header) != _HEADER_KEYS:
        raise _invalid("Header archive inventory не соответствует schema v2")
    if header.get("schema_version") != ARCHIVE_INVENTORY_SCHEMA_VERSION:
        raise _invalid("Версия archive inventory не поддерживается")
    _validate_created_at(header.get("created_at"))
    if not _is_digest(header.get("revision")):
        raise _invalid("Некорректный revision archive inventory")
    source = _validate_source(header.get("source"))
    archive = _validate_archive_binding(header.get("archive"))
    if expected_source is not None and source != expected_source:
        raise _invalid("Source binding archive inventory не совпадает")
    if expected_archive is not None and archive != expected_archive:
        raise _invalid("Archive binding inventory не совпадает")
    layout = header.get("layout")
    if layout not in {LAYOUT_FIXED_ABSOLUTE, LAYOUT_RELATIVE_TARGET_ROOT}:
        raise _invalid("Некорректный layout archive inventory")
    policy_revision = header.get("policy_revision")
    if policy_revision != online_restore_policy_revision():
        raise _invalid("Policy revision archive inventory устарела")

    manifest = value.get("manifest")
    if layout == LAYOUT_FIXED_ABSOLUTE:
        if not isinstance(manifest, dict):
            raise _invalid("Fixed archive inventory не содержит Manifest")
        validate_manifest(manifest)
        _validate_manifest_source_binding(
            manifest=manifest,
            source=source,
            archive=archive,
        )
    elif manifest is not None:
        raise _invalid("Relative archive inventory не должен содержать Manifest")
    if source.get("kind") == "managed" and layout != LAYOUT_FIXED_ABSOLUTE:
        raise _invalid("Managed archive inventory не может быть relative")

    members = _validate_compact_members(value.get("members"))
    if layout == LAYOUT_FIXED_ABSOLUTE:
        _validate_fixed_member_scope(members, manifest)
    view = value.get("view")
    if not isinstance(view, dict) or set(view) != _VIEW_KEYS:
        raise _invalid("View archive inventory не соответствует schema v2")
    nodes = _validate_nodes_and_policy(
        members=members,
        manifest=manifest,
        layout=layout,
        root_count=view.get("root_count"),
        nodes=view.get("nodes"),
        policy_projection=value.get("policy_projection"),
    )
    expected_revision = inventory_revision(
        source=source,
        archive=archive,
        layout=layout,
        manifest=manifest,
        members=members,
        root_count=view["root_count"],
        nodes=nodes,
        policy_projection=value["policy_projection"],
        policy_revision=policy_revision,
    )
    if header["revision"] != expected_revision:
        raise _invalid("Revision archive inventory не соответствует содержимому")
    return value


class _ProjectedPathColumn:
    """Absolute path view for a relative hierarchy without retaining duplicates."""

    def __init__(self, nodes: list[list], target_root: str):
        self._nodes = nodes
        self._target_root = target_root

    def __len__(self) -> int:
        return len(self._nodes)

    def __getitem__(self, index: int) -> str:
        path = self._nodes[index][0]
        return self._target_root if path == "" else posixpath.join(self._target_root, path)

    def __iter__(self):
        target_root = self._target_root
        for node in self._nodes:
            path = node[0]
            yield target_root if path == "" else posixpath.join(target_root, path)


@dataclass(frozen=True)
class ArchiveInventorySnapshot:
    revision: str
    layout: int
    source: dict
    archive: dict
    root_count: int
    nodes: list[list]
    path_to_id: dict[str, int]
    policy_summary: int
    frontier_count: int
    frontier_ids: tuple[int, ...] | None
    relative_hardlinks: tuple[tuple[int, str], ...]
    retained_bytes: int


@dataclass(frozen=True)
class ArchiveInventoryProjection:
    snapshot: ArchiveInventorySnapshot
    target_root: str | None
    policy_flags: bytearray | None
    policy_summary: int
    frontier_count: int
    frontier_ids: tuple[int, ...] | None
    retained_bytes: int

    @property
    def revision(self) -> str:
        return self.snapshot.revision


@dataclass(frozen=True)
class ArchiveInventoryView:
    """Target-independent presentation view over one validated snapshot."""

    snapshot: ArchiveInventorySnapshot

    @property
    def revision(self) -> str:
        return self.snapshot.revision

    @property
    def root_count(self) -> int:
        if self.snapshot.layout == LAYOUT_RELATIVE_TARGET_ROOT:
            root = self.snapshot.nodes[0]
            return root[9]
        return self.snapshot.root_count


@dataclass
class _CacheFlight:
    event: threading.Event
    result: object | None = None
    error: BaseException | None = None


def _inventory_query_error(reason: str, message: str) -> BackupError:
    return BackupError(
        ErrorCode.INVALID_REQUEST,
        message,
        details={"inventory_error": reason},
    )


def _inventory_resource_error(message: str) -> BackupError:
    return BackupError(
        ErrorCode.STORAGE_BACKEND_ERROR,
        message,
        retryable=True,
        details={"inventory_error": "resource_limit"},
    )


def _estimate_small_value(value: object) -> int:
    if isinstance(value, dict):
        return value.__sizeof__() + sum(
            sys.getsizeof(key) + _estimate_small_value(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return value.__sizeof__() + sum(_estimate_small_value(item) for item in value)
    return sys.getsizeof(value)


def _estimate_snapshot_bytes(
    *,
    nodes: list[list],
    path_to_id: dict[str, int],
    source: dict,
    archive: dict,
    frontier_ids: tuple[int, ...] | None,
    relative_hardlinks: tuple[tuple[int, str], ...],
) -> int:
    retained = nodes.__sizeof__() + path_to_id.__sizeof__()
    for row in nodes:
        retained += row.__sizeof__()
        for value in row:
            retained += sys.getsizeof(value)
    retained += sum(sys.getsizeof(node_id) for node_id in path_to_id.values())
    retained += _estimate_small_value(source) + _estimate_small_value(archive)
    if frontier_ids is not None:
        retained += frontier_ids.__sizeof__()
        retained += sum(sys.getsizeof(node_id) for node_id in frontier_ids)
    retained += relative_hardlinks.__sizeof__()
    for owner_id, target in relative_hardlinks:
        retained += sys.getsizeof((owner_id, target))
        retained += sys.getsizeof(owner_id) + sys.getsizeof(target)
    return retained


def _relative_hardlink_dependencies(
    members: list[list],
    *,
    nodes: list[list],
    path_to_id: dict[str, int],
) -> tuple[tuple[int, str], ...]:
    dependencies: list[tuple[int, str]] = []
    for row in members:
        if row[1] != MEMBER_HARDLINK:
            continue
        path = _relative_member_path(row[0])
        node_id = path_to_id.get(path, -1)
        if node_id >= 0 and nodes[node_id][2] == NODE_DIRECTORY:
            owner_id = node_id
        else:
            parent = _parent_path(path, LAYOUT_RELATIVE_TARGET_ROOT)
            owner_id = -1 if parent is None else path_to_id.get(parent, -1)
        if owner_id < 0 or nodes[owner_id][2] != NODE_DIRECTORY:
            raise _invalid("Relative hardlink отсутствует в compact hierarchy")
        dependencies.append((owner_id, _relative_member_path(row[3])))
    return tuple(dependencies)


def build_archive_inventory_snapshot(
    inventory: object,
    *,
    expected_source: dict | None = None,
    expected_archive: dict | None = None,
) -> ArchiveInventorySnapshot:
    """Deep-validate a document and retain only its bounded query representation."""
    value = validate_archive_inventory(
        inventory,
        expected_source=expected_source,
        expected_archive=expected_archive,
    )
    header = value["header"]
    nodes = value["view"]["nodes"]
    path_to_id = {row[0]: node_id for node_id, row in enumerate(nodes)}
    if len(path_to_id) != len(nodes):
        raise _invalid("Duplicate compact node path")

    projection = value["policy_projection"]
    if header["layout"] == LAYOUT_FIXED_ABSOLUTE:
        policy_summary = projection[1]
        frontier_count = projection[2]
        frontier_ids = None if projection[3] is None else tuple(projection[3])
        relative_hardlinks = ()
    else:
        policy_summary = 0
        frontier_count = 0
        frontier_ids = ()
        relative_hardlinks = _relative_hardlink_dependencies(
            value["members"],
            nodes=nodes,
            path_to_id=path_to_id,
        )

    source = dict(header["source"])
    archive = dict(header["archive"])
    retained_bytes = _estimate_snapshot_bytes(
        nodes=nodes,
        path_to_id=path_to_id,
        source=source,
        archive=archive,
        frontier_ids=frontier_ids,
        relative_hardlinks=relative_hardlinks,
    )
    if retained_bytes > MAX_ARCHIVE_INVENTORY_SNAPSHOT_BYTES:
        raise _inventory_resource_error(
            "Inventory слишком велик для безопасного размещения в query cache"
        )
    return ArchiveInventorySnapshot(
        revision=header["revision"],
        layout=header["layout"],
        source=source,
        archive=archive,
        root_count=value["view"]["root_count"],
        nodes=nodes,
        path_to_id=path_to_id,
        policy_summary=policy_summary,
        frontier_count=frontier_count,
        frontier_ids=frontier_ids,
        relative_hardlinks=relative_hardlinks,
        retained_bytes=retained_bytes,
    )


def project_archive_inventory(
    snapshot: ArchiveInventorySnapshot,
    *,
    target_root: object | None = None,
    storage_root: str | None = None,
) -> ArchiveInventoryProjection:
    """Bind a validated base snapshot to fixed paths or one safe target root."""
    if not isinstance(snapshot, ArchiveInventorySnapshot):
        raise _inventory_query_error("invalid_snapshot", "Inventory snapshot недоступен")
    if snapshot.layout == LAYOUT_FIXED_ABSOLUTE:
        if target_root is not None:
            raise _inventory_query_error(
                "unexpected_target_root",
                "target_root недопустим для Backup с фиксированными путями",
            )
        return ArchiveInventoryProjection(
            snapshot=snapshot,
            target_root=None,
            policy_flags=None,
            policy_summary=snapshot.policy_summary,
            frontier_count=snapshot.frontier_count,
            frontier_ids=snapshot.frontier_ids,
            retained_bytes=0,
        )
    if target_root is None:
        raise _inventory_query_error(
            "target_root_required",
            "Для imported Backup без Manifest требуется target_root",
        )

    scope = build_restore_scope(target_root=target_root, storage_root=storage_root)
    normalized_root = scope.target_root
    paths = _ProjectedPathColumn(snapshot.nodes, normalized_root)
    hardlinks = tuple(
        (
            owner_id,
            normalized_root
            if target == ""
            else posixpath.join(normalized_root, target),
        )
        for owner_id, target in snapshot.relative_hardlinks
    )
    policy = build_bulk_restore_policy(
        node_paths=paths,
        node_types=_NodeColumn(snapshot.nodes, 2),
        parent_ids=_NodeColumn(snapshot.nodes, 1),
        node_member_counts=_PolicyMemberCountColumn(snapshot.nodes),
        hardlink_dependencies=hardlinks,
    )
    flags = bytearray(len(snapshot.nodes))
    for node_id, row in enumerate(snapshot.nodes):
        value = row[3] & NODE_FLAG_EXPLICIT
        if policy["selectable"][node_id]:
            value |= NODE_FLAG_SELECTABLE
        if policy["blocked"][node_id]:
            value |= NODE_FLAG_BLOCKED
        if policy["has_selectable_descendants"][node_id]:
            value |= NODE_FLAG_HAS_SELECTABLE_DESCENDANTS
        flags[node_id] = value
    frontier = policy["frontier"]
    frontier_ids = tuple(frontier) if len(frontier) <= MAX_SELECTION_PATHS else None
    retained_bytes = (
        flags.__sizeof__()
        + sys.getsizeof(normalized_root)
        + (0 if frontier_ids is None else _estimate_small_value(frontier_ids))
    )
    if snapshot.retained_bytes + retained_bytes > MAX_ARCHIVE_INVENTORY_SNAPSHOT_BYTES:
        raise _inventory_resource_error(
            "Inventory projection слишком велик для безопасного размещения в query cache"
        )
    return ArchiveInventoryProjection(
        snapshot=snapshot,
        target_root=normalized_root,
        policy_flags=flags,
        policy_summary=policy["summary"],
        frontier_count=len(frontier),
        frontier_ids=frontier_ids,
        retained_bytes=retained_bytes,
    )


def project_archive_inventory_view(
    snapshot: ArchiveInventorySnapshot,
) -> ArchiveInventoryView:
    """Expose archive paths without binding relative content to a Restore root."""
    if not isinstance(snapshot, ArchiveInventorySnapshot):
        raise _inventory_query_error("invalid_snapshot", "Inventory snapshot недоступен")
    return ArchiveInventoryView(snapshot=snapshot)


def _projection_path(projection: ArchiveInventoryProjection, node_id: int) -> str:
    path = projection.snapshot.nodes[node_id][0]
    if projection.snapshot.layout == LAYOUT_FIXED_ABSOLUTE:
        return path
    target_root = projection.target_root
    return target_root if path == "" else posixpath.join(target_root, path)


def _projection_node_id(
    projection: ArchiveInventoryProjection,
    path: object,
) -> int:
    if not isinstance(path, str):
        raise _inventory_query_error("invalid_parent", "Некорректный parent inventory")
    if projection.snapshot.layout == LAYOUT_FIXED_ABSOLUTE:
        from .restore_plan import normalize_restore_root

        normalized = normalize_restore_root(path, field="inventory parent")
        relative = normalized
    else:
        from .restore_plan import normalize_restore_root

        normalized = normalize_restore_root(path, field="inventory parent")
        target_root = projection.target_root
        if normalized == target_root:
            relative = ""
        else:
            prefix = target_root.rstrip("/") + "/"
            if not normalized.startswith(prefix):
                raise _inventory_query_error(
                    "invalid_parent",
                    "Parent находится вне target_root inventory",
                )
            relative = _relative_member_path(normalized[len(prefix):])
    node_id = projection.snapshot.path_to_id.get(relative)
    if node_id is None:
        raise _inventory_query_error(
            "unknown_parent",
            "Parent отсутствует в archive inventory",
        )
    return node_id


def _projection_flags(projection: ArchiveInventoryProjection, node_id: int) -> int:
    if projection.policy_flags is not None:
        return projection.policy_flags[node_id]
    return projection.snapshot.nodes[node_id][3]


def archive_inventory_policy_summary(
    projection: ArchiveInventoryProjection,
) -> dict[str, bool]:
    bits = projection.policy_summary
    return {
        "has_selectable": bool(bits & POLICY_SUMMARY_HAS_SELECTABLE),
        "has_blocked": bool(bits & POLICY_SUMMARY_HAS_BLOCKED),
        "has_mixed": bool(bits & POLICY_SUMMARY_HAS_MIXED),
    }


def archive_inventory_select_all(
    projection: ArchiveInventoryProjection,
) -> dict:
    required_count = projection.frontier_count
    if projection.frontier_ids is None:
        return {
            "available": False,
            "required_count": required_count,
            "paths": None,
            "error": {
                "code": "selection_limit",
                "message": (
                    "Для выбора всех разрешённых путей требуется больше "
                    f"{MAX_SELECTION_PATHS} элементов"
                ),
            },
        }
    paths = [
        _projection_path(projection, node_id)
        for node_id in projection.frontier_ids
    ]
    return {
        "available": bool(paths),
        "required_count": required_count,
        "paths": paths,
        "error": None,
    }


def _archive_inventory_node(
    projection: ArchiveInventoryProjection,
    node_id: int,
) -> dict:
    row = projection.snapshot.nodes[node_id]
    path = _projection_path(projection, node_id)
    flags = _projection_flags(projection, node_id)
    result = {
        "path": path,
        "name": posixpath.basename(path) or path,
        "type": "directory" if row[2] == NODE_DIRECTORY else "file",
        "explicit": bool(flags & NODE_FLAG_EXPLICIT),
        "selectable": bool(flags & NODE_FLAG_SELECTABLE),
        "blocked": bool(flags & NODE_FLAG_BLOCKED),
        "has_selectable_descendants": bool(
            flags & NODE_FLAG_HAS_SELECTABLE_DESCENDANTS
        ),
    }
    if row[2] == NODE_DIRECTORY:
        result.update({
            "member_count": row[5],
            "file_count": row[6],
            "bytes": row[7],
            "has_children": row[9] > 0,
            "child_count": row[9],
        })
    else:
        result.update({
            "size": row[5],
            "has_children": False,
            "child_count": 0,
        })
    return result


def _cursor_context_hash(*values: object) -> str:
    encoded = json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(b"bot4vps:archive-inventory-cursor:v1\0" + encoded).digest()
    return base64.urlsafe_b64encode(digest[:18]).decode("ascii").rstrip("=")


def _encode_inventory_cursor(payload: list) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    if len(token) > MAX_ARCHIVE_INVENTORY_CURSOR_LENGTH:
        raise _inventory_query_error("cursor_invalid", "Cursor inventory слишком длинный")
    return token


def _decode_inventory_cursor(token: object) -> list:
    if (
        not isinstance(token, str)
        or not token
        or len(token) > MAX_ARCHIVE_INVENTORY_CURSOR_LENGTH
        or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in token)
    ):
        raise _inventory_query_error("cursor_invalid", "Некорректный cursor inventory")
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _inventory_query_error(
            "cursor_invalid",
            "Некорректный cursor inventory",
        ) from exc
    if not isinstance(payload, list):
        raise _inventory_query_error("cursor_invalid", "Некорректный cursor inventory")
    return payload


def _validate_query_limit(value: object) -> int:
    if value is None:
        return DEFAULT_ARCHIVE_INVENTORY_QUERY_LIMIT
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_ARCHIVE_INVENTORY_QUERY_LIMIT
    ):
        raise _inventory_query_error(
            "invalid_limit",
            f"Limit inventory должен быть от 1 до {MAX_ARCHIVE_INVENTORY_QUERY_LIMIT}",
        )
    return value


def query_archive_inventory_children(
    projection: ArchiveInventoryProjection,
    *,
    parent: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> dict:
    """Return one bounded root/direct-child page from a validated projection."""
    page_limit = _validate_query_limit(limit)
    snapshot = projection.snapshot
    if parent is None:
        parent_id = -1
        first = 0
        count = snapshot.root_count
    else:
        parent_id = _projection_node_id(projection, parent)
        parent_row = snapshot.nodes[parent_id]
        if parent_row[2] != NODE_DIRECTORY:
            raise _inventory_query_error(
                "parent_not_directory",
                "Parent inventory не является каталогом",
            )
        first = parent_row[8]
        count = parent_row[9]
        if count == 0:
            first = -1

    context = _cursor_context_hash(
        "children",
        projection.target_root,
        parent_id,
    )
    last_id = first - 1
    if cursor is not None:
        payload = _decode_inventory_cursor(cursor)
        if len(payload) != 6 or payload[0] != 1 or payload[2] != "children":
            raise _inventory_query_error("cursor_invalid", "Cursor children несовместим")
        if payload[1] != snapshot.revision:
            raise _inventory_query_error(
                "cursor_stale",
                "Archive inventory изменился; обновите дерево",
            )
        if payload[3] != context or payload[4] != parent_id:
            raise _inventory_query_error(
                "cursor_context",
                "Cursor относится к другому parent inventory",
            )
        anchor = payload[5]
        if (
            isinstance(anchor, bool)
            or not isinstance(anchor, int)
            or count == 0
            or anchor < first
            or anchor >= first + count
            or (parent_id >= 0 and snapshot.nodes[anchor][1] != parent_id)
            or (parent_id < 0 and snapshot.nodes[anchor][1] != -1)
        ):
            raise _inventory_query_error("cursor_invalid", "Cursor children повреждён")
        last_id = anchor

    start = last_id + 1
    end = first + count if count else start
    selected_ids = list(range(start, min(start + page_limit, end)))
    has_more = bool(selected_ids and selected_ids[-1] + 1 < end)
    next_cursor = None
    if has_more:
        next_cursor = _encode_inventory_cursor([
            1,
            snapshot.revision,
            "children",
            context,
            parent_id,
            selected_ids[-1],
        ])
    response = {
        "revision": snapshot.revision,
        "parent": parent,
        "items": [
            _archive_inventory_node(projection, node_id)
            for node_id in selected_ids
        ],
        "has_more": has_more,
        "next_cursor": next_cursor,
        "policy_summary": archive_inventory_policy_summary(projection),
    }
    if parent is None:
        response["select_all"] = archive_inventory_select_all(projection)
    return response


def _archive_view_node_id(view: ArchiveInventoryView, path: object) -> int:
    if not isinstance(path, str) or not path:
        raise _inventory_query_error("invalid_parent", "Некорректный parent inventory")
    snapshot = view.snapshot
    if snapshot.layout == LAYOUT_FIXED_ABSOLUTE:
        from .restore_plan import normalize_restore_root

        normalized = normalize_restore_root(path, field="inventory parent")
    else:
        normalized = _relative_member_path(path)
        if normalized != path:
            raise _inventory_query_error(
                "invalid_parent",
                "Parent archive inventory не canonical",
            )
    node_id = snapshot.path_to_id.get(normalized)
    if node_id is None:
        raise _inventory_query_error(
            "unknown_parent",
            "Parent отсутствует в archive inventory",
        )
    return node_id


def _archive_view_node(view: ArchiveInventoryView, node_id: int) -> dict:
    row = view.snapshot.nodes[node_id]
    path = row[0]
    return {
        "path": path,
        "name": posixpath.basename(path) or path,
        "type": "directory" if row[2] == NODE_DIRECTORY else "file",
        "explicit": bool(row[3] & NODE_FLAG_EXPLICIT),
        "has_children": bool(row[2] == NODE_DIRECTORY and row[9] > 0),
    }


def query_archive_inventory_view_children(
    view: ArchiveInventoryView,
    *,
    parent: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> dict:
    """Return one bounded archive-presentation page without Restore policy fields."""
    if not isinstance(view, ArchiveInventoryView):
        raise _inventory_query_error("invalid_snapshot", "Inventory snapshot недоступен")
    page_limit = _validate_query_limit(limit)
    snapshot = view.snapshot
    if parent is None:
        if snapshot.layout == LAYOUT_RELATIVE_TARGET_ROOT:
            parent_id = 0
            root = snapshot.nodes[parent_id]
            first = root[8]
            count = root[9]
        else:
            parent_id = -1
            first = 0
            count = snapshot.root_count
    else:
        parent_id = _archive_view_node_id(view, parent)
        parent_row = snapshot.nodes[parent_id]
        if parent_row[2] != NODE_DIRECTORY:
            raise _inventory_query_error(
                "parent_not_directory",
                "Parent inventory не является каталогом",
            )
        first = parent_row[8]
        count = parent_row[9]
    if count == 0:
        first = -1

    context = _cursor_context_hash("archive_children", parent_id)
    last_id = first - 1
    if cursor is not None:
        payload = _decode_inventory_cursor(cursor)
        if len(payload) != 6 or payload[0] != 1 or payload[2] != "archive_children":
            raise _inventory_query_error(
                "cursor_invalid",
                "Cursor archive children несовместим",
            )
        if payload[1] != snapshot.revision:
            raise _inventory_query_error(
                "cursor_stale",
                "Archive inventory изменился; обновите дерево",
            )
        if payload[3] != context or payload[4] != parent_id:
            raise _inventory_query_error(
                "cursor_context",
                "Cursor относится к другому parent inventory",
            )
        anchor = payload[5]
        if (
            isinstance(anchor, bool)
            or not isinstance(anchor, int)
            or count == 0
            or anchor < first
            or anchor >= first + count
            or snapshot.nodes[anchor][1] != parent_id
        ):
            raise _inventory_query_error("cursor_invalid", "Cursor children повреждён")
        last_id = anchor

    start = last_id + 1
    end = first + count if count else start
    selected_ids = list(range(start, min(start + page_limit, end)))
    has_more = bool(selected_ids and selected_ids[-1] + 1 < end)
    next_cursor = None
    if has_more:
        next_cursor = _encode_inventory_cursor([
            1,
            snapshot.revision,
            "archive_children",
            context,
            parent_id,
            selected_ids[-1],
        ])
    return {
        "revision": snapshot.revision,
        "parent": parent,
        "items": [_archive_view_node(view, node_id) for node_id in selected_ids],
        "has_more": has_more,
        "next_cursor": next_cursor,
    }


def query_archive_inventory_search(
    projection: ArchiveInventoryProjection,
    *,
    query: object,
    cursor: str | None = None,
    limit: int | None = None,
) -> dict:
    """Search the full hierarchy directory-first with bounded result memory."""
    if not isinstance(query, str):
        raise _inventory_query_error("invalid_query", "Некорректный query inventory")
    query = query.strip()
    if not query or len(query) > 256:
        raise _inventory_query_error(
            "invalid_query",
            "Query inventory должен содержать от 1 до 256 символов",
        )
    folded = query.casefold()
    page_limit = _validate_query_limit(limit)
    snapshot = projection.snapshot
    context = _cursor_context_hash(
        "search",
        projection.target_root,
        folded,
    )
    phase = 0
    last_id = -1
    if cursor is not None:
        payload = _decode_inventory_cursor(cursor)
        if len(payload) != 6 or payload[0] != 1 or payload[2] != "search":
            raise _inventory_query_error("cursor_invalid", "Cursor search несовместим")
        if payload[1] != snapshot.revision:
            raise _inventory_query_error(
                "cursor_stale",
                "Archive inventory изменился; повторите поиск",
            )
        if payload[3] != context:
            raise _inventory_query_error(
                "cursor_context",
                "Cursor относится к другому query inventory",
            )
        phase, last_id = payload[4:6]
        if (
            phase not in {0, 1}
            or isinstance(last_id, bool)
            or not isinstance(last_id, int)
            or last_id < 0
            or last_id >= len(snapshot.nodes)
            or snapshot.nodes[last_id][2] != (NODE_DIRECTORY if phase == 0 else NODE_FILE)
            or folded not in _projection_path(projection, last_id).casefold()
        ):
            raise _inventory_query_error("cursor_invalid", "Cursor search повреждён")

    matches: list[tuple[int, int]] = []
    scan_phase = phase
    scan_start = last_id + 1
    while scan_phase <= 1 and len(matches) <= page_limit:
        wanted_type = NODE_DIRECTORY if scan_phase == 0 else NODE_FILE
        for node_id in range(scan_start, len(snapshot.nodes)):
            if snapshot.nodes[node_id][2] != wanted_type:
                continue
            if folded not in _projection_path(projection, node_id).casefold():
                continue
            matches.append((scan_phase, node_id))
            if len(matches) > page_limit:
                break
        if len(matches) > page_limit:
            break
        scan_phase += 1
        scan_start = 0

    has_more = len(matches) > page_limit
    page = matches[:page_limit]
    next_cursor = None
    if has_more and page:
        cursor_phase, cursor_id = page[-1]
        next_cursor = _encode_inventory_cursor([
            1,
            snapshot.revision,
            "search",
            context,
            cursor_phase,
            cursor_id,
        ])
    return {
        "revision": snapshot.revision,
        "query": query,
        "items": [
            _archive_inventory_node(projection, node_id)
            for _phase, node_id in page
        ],
        "has_more": has_more,
        "next_cursor": next_cursor,
        "policy_summary": archive_inventory_policy_summary(projection),
    }


class ArchiveInventoryQueryCache:
    """Thread-safe shared-budget LRU with per-key single-flight loading."""

    def __init__(
        self,
        *,
        max_entries: int = MAX_ARCHIVE_INVENTORY_CACHE_ENTRIES,
        max_bytes: int = MAX_ARCHIVE_INVENTORY_CACHE_BYTES,
        max_snapshot_bytes: int = MAX_ARCHIVE_INVENTORY_SNAPSHOT_BYTES,
    ):
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._max_snapshot_bytes = max_snapshot_bytes
        self._entries: OrderedDict[object, object] = OrderedDict()
        self._flights: dict[object, _CacheFlight] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _base(value: object) -> ArchiveInventorySnapshot:
        if isinstance(value, ArchiveInventorySnapshot):
            return value
        if isinstance(value, (ArchiveInventoryProjection, ArchiveInventoryView)):
            return value.snapshot
        raise TypeError("inventory cache accepts snapshots, projections, and views only")

    @classmethod
    def _entry_bytes(cls, value: object) -> int:
        base = cls._base(value)
        overlay = value.retained_bytes if isinstance(value, ArchiveInventoryProjection) else 0
        return base.retained_bytes + overlay

    @classmethod
    def _total_bytes(cls, entries) -> int:
        bases: dict[int, ArchiveInventorySnapshot] = {}
        overlays = 0
        for value in entries:
            base = cls._base(value)
            bases[id(base)] = base
            if isinstance(value, ArchiveInventoryProjection):
                overlays += value.retained_bytes
        return sum(base.retained_bytes for base in bases.values()) + overlays

    def get(self, key: object):
        with self._lock:
            value = self._entries.get(key)
            if value is not None:
                self._entries.move_to_end(key)
            return value

    def put(self, key: object, value: object):
        entry_bytes = self._entry_bytes(value)
        if entry_bytes > self._max_snapshot_bytes:
            raise _inventory_resource_error(
                "Inventory snapshot превышает per-entry cache budget"
            )
        with self._lock:
            self._entries.pop(key, None)
            self._entries[key] = value
            while (
                len(self._entries) > self._max_entries
                or self._total_bytes(self._entries.values()) > self._max_bytes
            ):
                oldest_key = next(iter(self._entries))
                if oldest_key == key and len(self._entries) == 1:
                    self._entries.pop(key, None)
                    raise _inventory_resource_error(
                        "Inventory snapshot не помещается в общий cache budget"
                    )
                self._entries.popitem(last=False)
            return value

    def get_or_load(self, key: object, loader):
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                return cached
            flight = self._flights.get(key)
            owner = flight is None
            if owner:
                flight = _CacheFlight(threading.Event())
                self._flights[key] = flight

        if not owner:
            flight.event.wait()
            if flight.error is not None:
                raise flight.error
            return flight.result

        try:
            result = loader()
            self.put(key, result)
            flight.result = result
            return result
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                self._flights.pop(key, None)
                flight.event.set()

    def invalidate(self, predicate=None) -> None:
        with self._lock:
            if predicate is None:
                self._entries.clear()
                return
            for key in list(self._entries):
                if predicate(key, self._entries[key]):
                    self._entries.pop(key, None)

    def stats(self) -> dict:
        with self._lock:
            return {
                "entries": len(self._entries),
                "bytes": self._total_bytes(self._entries.values()),
                "inflight": len(self._flights),
            }


ARCHIVE_INVENTORY_HEAVY_OPERATION = threading.Semaphore(1)
archive_inventory_query_cache = ArchiveInventoryQueryCache()


class _BoundedWriter:
    def __init__(self, stream, maximum: int):
        self.stream = stream
        self.maximum = maximum
        self.bytes_written = 0

    def write(self, value: str) -> None:
        encoded = value.encode("utf-8")
        self.bytes_written += len(encoded)
        if self.bytes_written > self.maximum:
            raise _invalid("Archive inventory превышает допустимый размер")
        self.stream.write(value)


def write_archive_inventory(
    path: str | Path,
    inventory: dict,
    *,
    validate: bool = True,
) -> int:
    """Stream a canonical v2 envelope to a new mode-0600 staging file."""
    if validate:
        validate_archive_inventory(inventory)
    path = Path(path)
    encoder = json.JSONEncoder(
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    fd = None
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            fd = None
            writer = _BoundedWriter(stream, MAX_ARCHIVE_INVENTORY_V2_BYTES)
            writer.write('{"header":')
            for chunk in encoder.iterencode(inventory["header"]):
                writer.write(chunk)
            if writer.bytes_written > MAX_ARCHIVE_INVENTORY_HEADER_BYTES:
                raise _invalid("Header archive inventory превышает bounded prefix")
            writer.write(',"manifest":')
            for chunk in encoder.iterencode(inventory["manifest"]):
                writer.write(chunk)
            writer.write(',"members":[')
            for index, row in enumerate(inventory["members"]):
                if index:
                    writer.write(",")
                for chunk in encoder.iterencode(row):
                    writer.write(chunk)
            writer.write('],"view":{"root_count":')
            writer.write(str(inventory["view"]["root_count"]))
            writer.write(',"nodes":[')
            for index, row in enumerate(inventory["view"]["nodes"]):
                if index:
                    writer.write(",")
                for chunk in encoder.iterencode(row):
                    writer.write(chunk)
            writer.write(']},"policy_projection":')
            for chunk in encoder.iterencode(inventory["policy_projection"]):
                writer.write(chunk)
            writer.write("}")
            stream.flush()
            os.fsync(stream.fileno())
            return writer.bytes_written
    except Exception:
        if fd is not None:
            os.close(fd)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def parse_archive_inventory_header_prefix(raw: bytes) -> dict:
    """Decode the canonical v2 header from one bounded byte prefix."""
    if not isinstance(raw, bytes) or len(raw) > MAX_ARCHIVE_INVENTORY_HEADER_BYTES:
        raise _invalid("Некорректный bounded prefix archive inventory")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _invalid("Header archive inventory не является UTF-8") from exc
    prefix = '{"header":'
    if not text.startswith(prefix):
        raise _invalid("Archive inventory не начинается с canonical header")
    try:
        header, end = json.JSONDecoder().raw_decode(text, len(prefix))
    except json.JSONDecodeError as exc:
        raise _invalid("Header archive inventory не помещается в bounded prefix") from exc
    if end >= len(text) or text[end] != ",":
        raise _invalid("Header archive inventory не завершён в bounded prefix")
    if not isinstance(header, dict) or set(header) != _HEADER_KEYS:
        raise _invalid("Header archive inventory не соответствует schema v2")
    if header.get("schema_version") != ARCHIVE_INVENTORY_SCHEMA_VERSION:
        raise _invalid("Версия archive inventory не поддерживается")
    _validate_created_at(header.get("created_at"))
    if not _is_digest(header.get("revision")):
        raise _invalid("Некорректный revision archive inventory")
    _validate_source(header.get("source"))
    _validate_archive_binding(header.get("archive"))
    if header.get("layout") not in {LAYOUT_FIXED_ABSOLUTE, LAYOUT_RELATIVE_TARGET_ROOT}:
        raise _invalid("Некорректный layout archive inventory")
    if header.get("policy_revision") != online_restore_policy_revision():
        raise _invalid("Policy revision archive inventory устарела")
    return header


def read_archive_inventory_header(path: str | Path) -> dict:
    """Read only the canonical first header from a bounded 64-KiB prefix."""
    path = Path(path)
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_ARCHIVE_INVENTORY_HEADER_BYTES + 1)
    except OSError as exc:
        raise _invalid("Не удалось прочитать header archive inventory") from exc
    return parse_archive_inventory_header_prefix(
        raw[:MAX_ARCHIVE_INVENTORY_HEADER_BYTES]
    )
