"""Проверка подписанного релиза; также копируется рядом со standalone runner.

Ключ доверия берётся из установленного кода, никогда из загруженного релиза.
Закрытый ключ нужен только издателю и не входит в поставку приложения.
"""
from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

REPOSITORY = "crashdmd/Bot4VPS"
MANIFEST_NAME = "Bot4VPS-update.json"
MAX_MANIFEST_BYTES = 128 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
DOMAIN = b"Bot4VPS update manifest v1\n"
TRUSTED_KEYS = {
    "update-2026-11": "94047ed529cfeb37a70de6723cfb9146f348dce813ecf42c41cc08ed05347c77",
}


class ReleaseTrustError(ValueError):
    pass


def canonical_payload(payload: dict) -> bytes:
    return DOMAIN + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseTrustError("Описание релиза содержит повторяющиеся поля")
        result[key] = value
    return result


def decode_envelope(data: bytes) -> dict:
    if len(data) > MAX_MANIFEST_BYTES:
        raise ReleaseTrustError("Описание релиза слишком большое")
    try:
        value = json.loads(data, object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError, RecursionError) as e:
        raise ReleaseTrustError("Не удалось прочитать подписанное описание релиза") from e
    if not isinstance(value, dict):
        raise ReleaseTrustError("Ожидается подписанное описание релиза")
    return value


def normalized_version(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"v?\d+(?:\.\d+){0,2}", value):
        raise ReleaseTrustError("Неверная версия подписанного релиза")
    parts = value.removeprefix("v").split(".")
    return ".".join(str(int(x)) for x in parts + ["0"] * (3 - len(parts)))


def verify_envelope(envelope: dict, expected_version: str | None = None) -> dict:
    try:
        if len(json.dumps(envelope, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_MANIFEST_BYTES:
            raise ReleaseTrustError("Описание релиза слишком большое")
        if set(envelope) != {"key_id", "payload", "signature"}:
            raise ValueError("Envelope fields")
        payload = envelope["payload"]
        if not isinstance(payload, dict):
            raise ValueError("Payload")
        encoded_key = TRUSTED_KEYS.get(envelope["key_id"])
        if not encoded_key:
            raise ReleaseTrustError("Релиз подписан неизвестным ключом")
        signature = base64.b64decode(envelope["signature"], validate=True)
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(encoded_key)).verify(signature, canonical_payload(payload))
    except ReleaseTrustError:
        raise
    except (InvalidSignature, ValueError, TypeError, KeyError, RecursionError) as e:
        raise ReleaseTrustError("Подпись релиза недействительна. Установка запрещена") from e

    if (set(payload) != {"schema", "repository", "version", "tag", "commit", "archive", "changelog"}
            or type(payload["schema"]) is not int or payload["schema"] != 1
            or payload["repository"] != REPOSITORY):
        raise ReleaseTrustError("Подписанный релиз имеет неподдерживаемый формат или репозиторий")
    version = normalized_version(payload["version"])
    if version != payload["version"] or normalized_version(payload["tag"]) != version:
        raise ReleaseTrustError("Версия и тег подписанного релиза не совпадают")
    if expected_version is not None and version != normalized_version(expected_version):
        raise ReleaseTrustError("Подписанное описание относится к другой версии")
    if not isinstance(payload["commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", payload["commit"]):
        raise ReleaseTrustError("Релиз не закреплён за конкретной ревизией")
    archive = payload["archive"]
    if (not isinstance(archive, dict) or set(archive) != {"name", "sha256", "size"}
            or archive["name"] != f"Bot4VPS-{version}.tar.gz"
            or type(archive["size"]) is not int or not 0 < archive["size"] <= MAX_ARCHIVE_BYTES
            or not isinstance(archive["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", archive["sha256"])):
        raise ReleaseTrustError("Некорректные размер, имя или хеш подписанного архива")
    if not isinstance(payload["changelog"], str) or len(payload["changelog"].encode("utf-8")) > 64 * 1024:
        raise ReleaseTrustError("Некорректное описание изменений релиза")
    return payload


def manifest_url(tag: str) -> str:
    normalized_version(tag)
    return f"https://github.com/{REPOSITORY}/releases/download/{quote(tag, safe='')}/{MANIFEST_NAME}"


def archive_url(payload: dict) -> str:
    return f"https://github.com/{REPOSITORY}/releases/download/{quote(payload['tag'], safe='')}/{payload['archive']['name']}"


def main() -> int:
    try:
        if len(sys.argv) != 3:
            raise ReleaseTrustError("Не указаны описание релиза и ожидаемая версия")
        with Path(sys.argv[1]).open("rb") as source:
            envelope = decode_envelope(source.read(MAX_MANIFEST_BYTES + 1))
        payload = verify_envelope(envelope, sys.argv[2])
        print(json.dumps({"payload": payload, "archive_url": archive_url(payload)}, ensure_ascii=False))
        return 0
    except Exception:
        print("Не удалось подтвердить подлинность релиза. Установка запрещена", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
