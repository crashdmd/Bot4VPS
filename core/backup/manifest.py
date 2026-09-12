from __future__ import annotations

import json
import posixpath
import tarfile
from pathlib import Path, PurePosixPath

from .errors import BackupError, ErrorCode
from .ids import validate_id
from .time_utils import normalize_utc_offset, parse_utc_timestamp
from .validation import normalize_exclusions


MAX_MANIFEST_BYTES = 1024 * 1024
MAX_LABEL_LENGTH = 200
MAX_METADATA_LENGTH = 200
_ALLOWED_TYPES = {"server", "bot4vps"}
_ALLOWED_PURPOSES = {"regular", "protective", "pre_update", "migration_source"}
_ALLOWED_MODES = {"manual", "automatic", "internal"}
_MANIFEST_KEYS = {
    "manifest_version", "backup_id", "type", "purpose", "mode", "label",
    "created_at", "completed_at", "archive", "producer", "source",
    "sources", "content", "bot4vps",
}
_ARCHIVE_KEYS = {"format", "encrypted"}
_PRODUCER_KEYS = {"name", "version"}
_SOURCE_ENTRY_KEYS = {"path", "payload_prefix", "exclusions"}
_CONTENT_KEYS = {"metadata", "file_count", "source_bytes"}
_CONTENT_METADATA_KEYS = {"hardlinks"}
# Типы членов, которые archive v1 умеет и создать, и восстановить. Жёсткая
# ссылка входит в набор осознанно: на живом корне второе имя одного inode —
# норма, и разыменовать его значило бы и прочитать, и сохранить файл дважды, и
# потерять саму связь имён при восстановлении.
_ALLOWED_MEMBER_TYPES = {"file", "directory", "symlink", "hardlink"}
_SERVER_SOURCE_KEYS = {"kind", "server_name"}
_SERVER_SOURCE_KEYS_WITH_ID = _SERVER_SOURCE_KEYS | {"server_id"}
_SERVER_SOURCE_KEYS_V2 = _SERVER_SOURCE_KEYS | {"utc_offset"}
_SERVER_SOURCE_KEYS_V2_WITH_ID = _SERVER_SOURCE_KEYS_WITH_ID | {"utc_offset"}
_BOT_SOURCE_KEYS = {"kind", "install_path", "systemd_unit"}
_BOT_SOURCE_KEYS_V2 = _BOT_SOURCE_KEYS | {"utc_offset"}
_BOT_EXTENSION_KEYS = {"version", "install_path", "systemd_unit"}


def _require_exact_keys(value: object, expected: set[str], field: str) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise BackupError(
            ErrorCode.MANIFEST_INVALID,
            f"{field} не соответствует закрытой schema v1",
        )
    return value


def _safe_metadata(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_METADATA_LENGTH
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise BackupError(ErrorCode.MANIFEST_INVALID, f"Некорректное metadata поле {field}")
    return value


def _normalized_member_name(name: str) -> str:
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
        raise BackupError(ErrorCode.ARCHIVE_PATH_UNSAFE, "Недопустимое имя archive member")
    path = PurePosixPath(name)
    if path.is_absolute():
        raise BackupError(ErrorCode.ARCHIVE_PATH_UNSAFE, "Абсолютный archive member path запрещён")
    normalized = posixpath.normpath(name)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise BackupError(ErrorCode.ARCHIVE_PATH_UNSAFE, "Archive path выходит за допустимый root")
    return normalized


def _validate_link(target: object, normalized_name: str) -> None:
    """Только пригодность самой строки target. Куда она указывает — не запрет.

    Абсолютная цель (``/mnt/data``) и цель с ``..`` разрешены осознанно: symlink
    восстанавливается ссылкой, а не разыменовывается, поэтому создание ссылки
    ничего за пределами корня не пишет. Настоящий escape даёт не цель ссылки, а
    ЗАПИСЬ ВНУТРЬ неё — её закрывают cross-member инвариант в
    :func:`_validate_managed_members` (ссылка внутри архива) и
    ``restore_apply.assert_no_symlink_ancestors`` (ссылка, уже лежащая на target).

    Прежний запрет абсолютных и выходящих целей делал managed-архив строже
    импортированного: одна и та же ссылка на диске сервера то попадала в бэкап, то
    ломала его верификацию, а безопасности не добавляла.
    """
    del normalized_name  # Имя члена участвует только в cross-member проверке.
    if not isinstance(target, str) or not target or "\x00" in target or "\\" in target:
        raise BackupError(ErrorCode.ARCHIVE_PATH_UNSAFE, "Некорректная symlink target")


def _absolute_source_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise BackupError(ErrorCode.MANIFEST_INVALID, f"{field} должен быть абсолютным POSIX path")
    path = PurePosixPath(value)
    normalized = posixpath.normpath(value)
    if not path.is_absolute():
        raise BackupError(ErrorCode.MANIFEST_INVALID, f"{field} должен быть допустимым абсолютным POSIX path")
    return normalized


def _payload_prefix_for(source_path: str) -> str:
    return "payload/" + source_path.lstrip("/")


def _reject_secret_path(source_path: str) -> None:
    parts = {part.lower() for part in PurePosixPath(source_path).parts}
    basename = PurePosixPath(source_path).name.lower()
    secret_basenames = {
        "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "authorized_keys",
    }
    if ".ssh" in parts or basename in secret_basenames or basename.endswith((".pem", ".key")):
        raise BackupError(
            ErrorCode.MANIFEST_INVALID,
            "Manifest не должен содержать private-key path",
        )


def validate_manifest(manifest: dict, *, expected_backup_id: str | None = None, expected_type: str | None = None) -> dict:
    if not isinstance(manifest, dict):
        raise BackupError(ErrorCode.MANIFEST_INVALID, "manifest.json должен содержать JSON object")
    manifest_version = manifest.get("manifest_version")
    if manifest_version not in {1, 2}:
        raise BackupError(
            ErrorCode.MANIFEST_VERSION_UNSUPPORTED,
            "Поддерживаются manifest_version 1 и 2",
        )
    manifest_keys = set(manifest)
    if manifest_keys != _MANIFEST_KEYS and manifest_keys != _MANIFEST_KEYS - {"label"}:
        raise BackupError(
            ErrorCode.MANIFEST_INVALID,
            "manifest.json не соответствует закрытой schema v1",
        )
    try:
        validate_id(manifest.get("backup_id"), field="backup_id")
        created_at = parse_utc_timestamp(manifest.get("created_at"))
        completed_at = parse_utc_timestamp(manifest.get("completed_at"))
    except (TypeError, ValueError) as exc:
        raise BackupError(ErrorCode.MANIFEST_INVALID, "Некорректные ID или UTC timestamps manifest") from exc
    if completed_at < created_at:
        raise BackupError(ErrorCode.MANIFEST_INVALID, "completed_at не может быть раньше created_at")
    if manifest.get("type") not in _ALLOWED_TYPES or manifest.get("purpose") not in _ALLOWED_PURPOSES or manifest.get("mode") not in _ALLOWED_MODES:
        raise BackupError(ErrorCode.MANIFEST_INVALID, "Некорректные type/purpose/mode manifest")
    if expected_backup_id and manifest.get("backup_id") != expected_backup_id:
        raise BackupError(ErrorCode.MANIFEST_INVALID, "backup_id manifest не совпадает с операцией")
    if expected_type and manifest.get("type") != expected_type:
        raise BackupError(ErrorCode.ARCHIVE_TYPE_MISMATCH, "Тип archive не соответствует операции")
    label = manifest.get("label")
    if label is not None and (
        not isinstance(label, str)
        or len(label) > MAX_LABEL_LENGTH
        or any(ord(char) < 32 or ord(char) == 127 for char in label)
    ):
        raise BackupError(ErrorCode.MANIFEST_INVALID, "Некорректный label manifest")
    archive = _require_exact_keys(manifest.get("archive"), _ARCHIVE_KEYS, "archive")
    if archive.get("format") != "tar.gz" or not isinstance(archive.get("encrypted"), bool):
        raise BackupError(ErrorCode.MANIFEST_INVALID, "archive manifest: ожидается tar.gz (plain или B4VE-зашифрованный)")
    producer = _require_exact_keys(manifest.get("producer"), _PRODUCER_KEYS, "producer")
    _safe_metadata(producer.get("name"), "producer.name")
    _safe_metadata(producer.get("version"), "producer.version")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise BackupError(ErrorCode.MANIFEST_INVALID, "Manifest sources не может быть пустым")
    source_paths: set[str] = set()
    payload_prefixes: set[str] = set()
    for item in sources:
        item = _require_exact_keys(item, _SOURCE_ENTRY_KEYS, "sources[]")
        source_path = _absolute_source_path(item.get("path"), "sources[].path")
        _reject_secret_path(source_path)
        if source_path in source_paths:
            raise BackupError(ErrorCode.MANIFEST_INVALID, "Manifest sources содержит duplicate path")
        source_paths.add(source_path)
        expected_prefix = _payload_prefix_for(source_path)
        if item.get("payload_prefix") != expected_prefix:
            raise BackupError(ErrorCode.MANIFEST_INVALID, "sources[].payload_prefix не соответствует source path")
        payload_prefixes.add(expected_prefix)
        exclusions = normalize_exclusions(
            item.get("exclusions"),
            field="sources[].exclusions",
            error_code=ErrorCode.MANIFEST_INVALID,
        )
        item["exclusions"] = exclusions
    content = _require_exact_keys(manifest.get("content"), _CONTENT_KEYS, "content")
    for field in ("file_count", "source_bytes"):
        value = content.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise BackupError(ErrorCode.MANIFEST_INVALID, f"content.{field} должен быть неотрицательным integer")
    metadata = _require_exact_keys(content.get("metadata"), _CONTENT_METADATA_KEYS, "content.metadata")
    if not isinstance(metadata.get("hardlinks"), bool):
        # Флаг описывает содержимое архива, а не запрет: hardlink-члены
        # допустимы, но объявление обязано быть правдой — сверка с реальными
        # членами идёт в verify_archive.
        raise BackupError(ErrorCode.MANIFEST_INVALID, "content.metadata.hardlinks должен быть boolean")
    if manifest["type"] == "server":
        source_value = manifest.get("source")
        expected_server_shapes = (
            {
                frozenset(_SERVER_SOURCE_KEYS_V2),
                frozenset(_SERVER_SOURCE_KEYS_V2_WITH_ID),
            }
            if manifest_version == 2
            else {
                frozenset(_SERVER_SOURCE_KEYS),
                frozenset(_SERVER_SOURCE_KEYS_WITH_ID),
            }
        )
        if not isinstance(source_value, dict) or frozenset(source_value) not in expected_server_shapes:
            raise BackupError(
                ErrorCode.MANIFEST_INVALID,
                f"source не соответствует закрытой schema v{manifest_version}",
            )
        source = source_value
    else:
        source = _require_exact_keys(
            manifest.get("source"),
            _BOT_SOURCE_KEYS_V2 if manifest_version == 2 else _BOT_SOURCE_KEYS,
            "source",
        )
    if source.get("kind") != manifest["type"]:
        raise BackupError(ErrorCode.MANIFEST_INVALID, "source.kind не соответствует type")
    if manifest_version == 2:
        try:
            normalized_offset = normalize_utc_offset(source.get("utc_offset"))
        except ValueError as exc:
            raise BackupError(ErrorCode.MANIFEST_INVALID, "Некорректный source.utc_offset") from exc
        if source.get("utc_offset") != normalized_offset:
            raise BackupError(
                ErrorCode.MANIFEST_INVALID,
                "source.utc_offset должен иметь канонический формат +HH:MM",
            )
    if manifest["type"] == "server":
        if "server_id" in source:
            try:
                validate_id(source.get("server_id"), field="source.server_id")
            except (TypeError, ValueError) as exc:
                raise BackupError(ErrorCode.MANIFEST_INVALID, "Некорректный source.server_id") from exc
        _safe_metadata(source.get("server_name"), "source.server_name")
        if manifest.get("bot4vps") is not None:
            raise BackupError(ErrorCode.MANIFEST_INVALID, "Server manifest должен содержать bot4vps=null")
    else:
        extension = _require_exact_keys(
            manifest.get("bot4vps"),
            _BOT_EXTENSION_KEYS,
            "bot4vps",
        )
        _safe_metadata(extension.get("version"), "bot4vps.version")
        install_path = _absolute_source_path(extension.get("install_path"), "bot4vps.install_path")
        systemd_unit = _absolute_source_path(extension.get("systemd_unit"), "bot4vps.systemd_unit")
        if source.get("install_path") != install_path or source.get("systemd_unit") != systemd_unit:
            raise BackupError(ErrorCode.MANIFEST_INVALID, "Bot4VPS source не совпадает с extension")
        if install_path not in source_paths or systemd_unit not in source_paths:
            raise BackupError(ErrorCode.MANIFEST_INVALID, "Bot4VPS sources не содержат install_path/systemd_unit")
    return manifest


def _member_type(member: tarfile.TarInfo) -> str:
    if member.isfile():
        return "file"
    if member.isdir():
        return "directory"
    if member.issym():
        return "symlink"
    if member.islnk():
        return "hardlink"
    if member.ischr():
        return "character_device"
    if member.isblk():
        return "block_device"
    if member.isfifo():
        return "fifo"
    return "other"


def _manifest_logical_name(name: object) -> bool:
    """Recognize the conventional Manifest name without applying path policy."""
    if not isinstance(name, str) or not name or "\x00" in name:
        return False
    if PurePosixPath(name).is_absolute():
        return False
    return posixpath.normpath(name) == "manifest.json"


def _member_metadata(member: tarfile.TarInfo) -> dict:
    member_type = _member_type(member)
    metadata = {
        "name": member.name,
        "type": member_type,
        "size": int(member.size),
    }
    if member_type in {"symlink", "hardlink"}:
        metadata["linkname"] = member.linkname
    if member_type in {"character_device", "block_device"}:
        metadata["devmajor"] = int(member.devmajor)
        metadata["devminor"] = int(member.devminor)
    if member_type == "other":
        typeflag = member.type
        metadata["typeflag"] = (
            typeflag.decode("ascii", errors="backslashreplace")
            if isinstance(typeflag, bytes)
            else str(typeflag)
        )
    return metadata


def _member_ancestor_names(normalized_name: str):
    """Логические предки имени члена внутри архива, от ближайшего к корню."""
    parent = posixpath.dirname(normalized_name)
    while parent:
        yield parent
        next_parent = posixpath.dirname(parent)
        if next_parent == parent:
            break
        parent = next_parent


def validate_ordered_member_graph(
    members,
    *,
    name_of,
    type_of,
    linkname_of,
    set_name=None,
) -> None:
    """Validate ordered archive metadata through a lightweight row adapter.

    The adapter lets persisted compact rows and TAR-inspection dictionaries share
    the same path, symlink-prefix, and hardlink-order security boundary without
    expanding compact rows into a second dictionary graph.
    """
    names: set[str] = set()
    symlink_names: set[str] = set()
    preceding_files: set[str] = set()

    for index, member in enumerate(members):
        normalized = _normalized_member_name(name_of(member))
        if normalized in names:
            if normalized == "manifest.json":
                raise BackupError(
                    ErrorCode.MANIFEST_DUPLICATE,
                    "Archive содержит несколько manifest.json",
                )
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Archive содержит duplicate logical member",
            )
        names.add(normalized)
        if set_name is not None:
            set_name(member, normalized)

        member_type = type_of(member)
        if member_type not in _ALLOWED_MEMBER_TYPES:
            raise BackupError(
                ErrorCode.ARCHIVE_SPECIAL_FILE_UNSUPPORTED,
                "Special files запрещены в archive v1",
            )
        if member_type == "symlink":
            _validate_link(linkname_of(member), normalized)
            symlink_names.add(normalized)
        elif member_type == "hardlink":
            raw_target = linkname_of(member)
            if (
                not isinstance(raw_target, str)
                or not raw_target
                or "\x00" in raw_target
                or "\\" in raw_target
            ):
                raise BackupError(
                    ErrorCode.ARCHIVE_PATH_UNSAFE,
                    f"Некорректная hardlink target у {normalized}",
                )
            try:
                target = _normalized_member_name(raw_target)
            except BackupError as exc:
                raise BackupError(
                    ErrorCode.ARCHIVE_PATH_UNSAFE,
                    "Hardlink target выходит за пределы archive: "
                    f"{normalized} → {raw_target}",
                ) from exc
            if _manifest_logical_name(target):
                raise BackupError(
                    ErrorCode.ARCHIVE_PATH_UNSAFE,
                    f"Hardlink указывает на manifest.json: {normalized}",
                )
            if target not in preceding_files:
                raise BackupError(
                    ErrorCode.ARCHIVE_PATH_UNSAFE,
                    "Hardlink указывает не на предшествующий ему файл archive: "
                    f"{normalized} → {raw_target}",
                )
        elif member_type == "file" and normalized != "manifest.json":
            preceding_files.add(normalized)

    if symlink_names:
        for member in members:
            normalized = _normalized_member_name(name_of(member))
            for ancestor in _member_ancestor_names(normalized):
                if ancestor in symlink_names:
                    raise BackupError(
                        ErrorCode.ARCHIVE_PATH_UNSAFE,
                        "Archive member лежит внутри symlink member: "
                        f"{normalized} внутри {ancestor}",
                    )


def validate_managed_member_namespace(members, *, name_of) -> None:
    """Require exactly one Manifest member and the closed managed namespace."""
    manifest_found = False
    for member in members:
        name = name_of(member)
        if name == "manifest.json":
            manifest_found = True
            continue
        if not isinstance(name, str) or not name.startswith("payload/"):
            raise BackupError(
                ErrorCode.ARCHIVE_PATH_UNSAFE,
                "Archive member находится вне manifest/payload namespace",
            )
    if not manifest_found:
        raise BackupError(ErrorCode.MANIFEST_MISSING, "manifest.json отсутствует")


def validate_manifest_member_scope(
    members,
    *,
    manifest: dict,
    name_of,
    type_of,
) -> None:
    """Bind a validated Manifest declaration to ordered member metadata."""
    if not manifest["content"]["metadata"]["hardlinks"] and any(
        type_of(member) == "hardlink" for member in members
    ):
        raise BackupError(
            ErrorCode.MANIFEST_INVALID,
            "Manifest объявил hardlinks=false, но archive содержит hardlink member",
        )
    expected_prefixes = {
        _payload_prefix_for(item["path"]) for item in manifest["sources"]
    }
    for member in members:
        name = name_of(member)
        if name == "manifest.json":
            continue
        if not any(
            name == prefix
            or name.startswith(prefix + "/")
            or (prefix == "payload/" and name.startswith("payload/"))
            for prefix in expected_prefixes
        ):
            raise BackupError(
                ErrorCode.ARCHIVE_PATH_UNSAFE,
                "Payload находится вне описанных manifest sources",
            )


def _validate_member_graph(
    members: list[dict],
    *,
    copy_members: bool,
) -> list[dict]:
    """Validate member safety, optionally normalizing an owned graph in place."""
    validated = [dict(member) for member in members] if copy_members else members
    validate_ordered_member_graph(
        validated,
        name_of=lambda member: member.get("name"),
        type_of=lambda member: member.get("type"),
        linkname_of=lambda member: member.get("linkname"),
        set_name=lambda member, normalized: member.__setitem__("name", normalized),
    )
    return validated


def _validate_managed_members(members: list[dict]) -> list[dict]:
    """Validate physical TAR safety and return detached normalized metadata."""
    return _validate_member_graph(members, copy_members=True)


def _validate_owned_managed_members(members: list[dict]) -> list[dict]:
    """Validate and normalize metadata owned by one private TAR inspection."""
    return _validate_member_graph(members, copy_members=False)


def validate_archive_inventory_members(members: object) -> list[dict]:
    """Validate the closed metadata shape used by a persisted archive inventory."""
    if not isinstance(members, list) or not members:
        raise BackupError(
            ErrorCode.ARCHIVE_INVALID,
            "Archive inventory не содержит ordered members",
        )
    checked: list[dict] = []
    for member in members:
        if not isinstance(member, dict):
            raise BackupError(ErrorCode.ARCHIVE_INVALID, "Некорректный member archive inventory")
        member_type = member.get("type")
        expected = {"name", "type", "size"}
        if member_type in {"symlink", "hardlink"}:
            expected.add("linkname")
        if member_type not in _ALLOWED_MEMBER_TYPES or set(member) != expected:
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Member archive inventory не соответствует закрытой schema v1",
            )
        size = member.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise BackupError(ErrorCode.ARCHIVE_INVALID, "Некорректный размер member inventory")
        if not isinstance(member.get("name"), str):
            raise BackupError(ErrorCode.ARCHIVE_INVALID, "Некорректное имя member inventory")
        if "linkname" in member and not isinstance(member.get("linkname"), str):
            raise BackupError(ErrorCode.ARCHIVE_INVALID, "Некорректная link target inventory")
        checked.append(dict(member))
    return _validate_managed_members(checked)


def _inspect_archive(archive_path: str | Path) -> tuple[dict, BackupError | None]:
    """Read TAR members and retain, but do not raise, optional Manifest errors."""
    archive_path = Path(archive_path)
    members: list[dict] = []
    manifest_members: list[tarfile.TarInfo] = []
    raw_manifest: bytes | None = None
    manifest_error: BackupError | None = None
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            for member in archive:
                members.append(_member_metadata(member))
                if _manifest_logical_name(member.name):
                    manifest_members.append(member)

            if len(manifest_members) > 1:
                raise BackupError(
                    ErrorCode.MANIFEST_DUPLICATE,
                    "Archive содержит несколько manifest.json",
                )
            if manifest_members:
                manifest_member = manifest_members[0]
                if not manifest_member.isfile():
                    manifest_error = BackupError(
                        ErrorCode.MANIFEST_INVALID,
                        "manifest.json должен быть regular file",
                    )
                elif not 0 <= manifest_member.size <= MAX_MANIFEST_BYTES:
                    manifest_error = BackupError(
                        ErrorCode.MANIFEST_INVALID,
                        "manifest.json превышает допустимый размер",
                    )
                else:
                    stream = archive.extractfile(manifest_member)
                    if stream is None:
                        manifest_error = BackupError(
                            ErrorCode.MANIFEST_INVALID,
                            "manifest.json недоступен для чтения",
                        )
                    else:
                        raw_manifest = stream.read(MAX_MANIFEST_BYTES + 1)
                        if len(raw_manifest) > MAX_MANIFEST_BYTES:
                            raw_manifest = None
                            manifest_error = BackupError(
                                ErrorCode.MANIFEST_INVALID,
                                "manifest.json превышает допустимый размер",
                            )
    except BackupError:
        raise
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise BackupError(ErrorCode.ARCHIVE_INVALID, "Archive tar.gz повреждён или недоступен") from exc

    manifest: dict | None = None
    if raw_manifest is not None:
        if raw_manifest.startswith(b"\xef\xbb\xbf"):
            manifest_error = BackupError(
                ErrorCode.MANIFEST_INVALID,
                "manifest.json должен быть UTF-8 без BOM",
            )
        else:
            try:
                decoded = json.loads(raw_manifest.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                decoded = None
            if isinstance(decoded, dict):
                manifest = decoded
            else:
                manifest_error = BackupError(
                    ErrorCode.MANIFEST_INVALID,
                    "manifest.json должен быть JSON object",
                )
    return {"manifest": manifest, "members": members}, manifest_error


def inspect_archive(archive_path: str | Path) -> dict:
    """Read TAR structure and optional usable Manifest without extraction."""
    inspected, _manifest_error = _inspect_archive(archive_path)
    return inspected


def validate_archive_physical(archive_path: str | Path) -> dict:
    """Validate TAR readability and safe members without requiring Manifest."""
    inspected, _manifest_error = _inspect_archive(archive_path)
    members = _validate_managed_members(inspected["members"])
    return {"manifest": inspected["manifest"], "members": members}


def verify_archive_with_members(
    archive_path: str | Path,
    *,
    expected_backup_id: str | None = None,
    expected_type: str | None = None,
) -> dict:
    """Verify one native archive and return its owned ordered member metadata."""
    inspected, manifest_error = _inspect_archive(archive_path)
    members = _validate_owned_managed_members(inspected["members"])
    if manifest_error is not None:
        raise manifest_error
    manifest = inspected["manifest"]
    if manifest is None:
        raise BackupError(ErrorCode.MANIFEST_MISSING, "manifest.json отсутствует")

    validate_managed_member_namespace(
        members,
        name_of=lambda member: member["name"],
    )

    validated = validate_manifest(
        manifest,
        expected_backup_id=expected_backup_id,
        expected_type=expected_type,
    )
    validate_manifest_member_scope(
        members,
        manifest=validated,
        name_of=lambda member: member["name"],
        type_of=lambda member: member["type"],
    )
    return {"manifest": validated, "members": members}


def verify_archive(
    archive_path: str | Path,
    *,
    expected_backup_id: str | None = None,
    expected_type: str | None = None,
) -> dict:
    """Verify one native archive and return its validated Manifest."""
    return verify_archive_with_members(
        archive_path,
        expected_backup_id=expected_backup_id,
        expected_type=expected_type,
    )["manifest"]
