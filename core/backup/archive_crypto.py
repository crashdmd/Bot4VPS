"""Шифрование backup-архивов паролем (формат B4VE, версия 1).

Потоковое AES-256-GCM поверх готового tar.gz: ключ выводится scrypt из
пароля, архив режется на куски по 4 МиБ, каждый кусок шифруется своим
nonce (base + номер куска) с AAD = header + номер куска + флаг «последний».

Что это даёт:

- неверный пароль / подмена кусков / обрезка хвоста → InvalidTag →
  ENCRYPTION_PASSWORD_INVALID (неверный пароль или архив повреждён);
- кусок из другого архива не подходит (в AAD свой header: salt + base nonce);
- «последний» кусок в AAD: нельзя отрезать хвост — новый финальный кусок
  был зашифрован с флагом last=0 и не пройдёт проверку;
- формат самодокументирован: magic+version+параметры scrypt в header.

Пароль нигде не хранится и не логируется: он живёт только в памяти на
время операции (ручной ввод или расшифровка сохранённого enc1:-значения).
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .errors import BackupError, ErrorCode

MAGIC = b"B4VE"
VERSION = 1

# scrypt: N=2^14, r=8, p=1 — ~16 MiB памяти, ~сотни мс на вывод ключа:
# перебор паролей дорог, интерактивный ввод — незаметен.
SCRYPT_N = 1 << 14
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LEN = 32
SALT_LEN = 16
NONCE_PREFIX_LEN = 8  # + 4 байта счётчика = 12-байтовый nonce GCM
CHUNK_SIZE = 4 * 1024 * 1024
TAG_LEN = 16  # AESGCM дописывает тег к шифротексту

# magic(4) version(1) N(4) r(4) p(4) salt(16) nonce_prefix(8) chunk(4)
_HEADER = struct.Struct("<4sBIII16s8sI")
MAX_PASSWORD_LEN = 256


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = Scrypt(
        salt=salt,
        length=KEY_LEN,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
    )
    return kdf.derive(password.encode("utf-8"))


def _check_password(password: str) -> None:
    if not password:
        raise BackupError(ErrorCode.ENCRYPTION_PASSWORD_REQUIRED, "Пароль шифрования не задан")
    if len(password) > MAX_PASSWORD_LEN:
        raise BackupError(ErrorCode.INVALID_REQUEST, "Пароль шифрования длиннее 256 символов")


def is_encrypted_file(path: str | Path) -> bool:
    """B4VE-детект по магии (замена tar-сниффинга 1f8b там, где нужно)."""
    try:
        with open(path, "rb") as fh:
            return fh.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def _nonce(prefix: bytes, counter: int) -> bytes:
    # Случайный префикс + счётчик: nonce уникальны в рамках архива
    return prefix + counter.to_bytes(12 - NONCE_PREFIX_LEN, "big")


def _aad(header: bytes, counter: int, last: bool) -> bytes:
    # Номер куска + флаг «последний»: защита от перестановки и обрезки
    return header + struct.pack("<IB", counter, 1 if last else 0)


def _read_chunk(in_fh, size: int, carry: bytes) -> tuple[bytes, bytes, bool]:
    """Прочитать кусок ровно size байт (или меньше у EOF).

    Возвращает (кусок, перенос на следующую итерацию, это_последний).
    Для обычных файлов read(n) < n означает EOF.
    """
    chunk = carry + in_fh.read(size - len(carry)) if carry else in_fh.read(size)
    if not chunk:
        return b"", b"", True
    if len(chunk) < size:
        return chunk, b"", True
    nxt = in_fh.read(1)
    return chunk, nxt, not nxt


def encrypt_file(src: str | Path, dst: str | Path, password: str) -> None:
    """Потоковое шифрование src → dst (dst перезаписывается, режим 0600)."""
    _check_password(password)
    salt = os.urandom(SALT_LEN)
    nonce_prefix = os.urandom(NONCE_PREFIX_LEN)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    header = _HEADER.pack(
        MAGIC, VERSION, SCRYPT_N, SCRYPT_R, SCRYPT_P, salt, nonce_prefix, CHUNK_SIZE,
    )
    try:
        with open(src, "rb") as in_fh:
            fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as out_fh:
                out_fh.write(header)
                counter = 0
                carry = b""
                while True:
                    chunk, carry, last = _read_chunk(in_fh, CHUNK_SIZE, carry)
                    if not chunk:
                        # Пустой src — один пустой «последний» кусок
                        if counter == 0:
                            out_fh.write(
                                aesgcm.encrypt(_nonce(nonce_prefix, 0), b"", _aad(header, 0, True))
                            )
                        break
                    out_fh.write(
                        aesgcm.encrypt(_nonce(nonce_prefix, counter), chunk, _aad(header, counter, last))
                    )
                    counter += 1
                    if last:
                        break
    except BackupError:
        raise
    except OSError as exc:
        raise BackupError(ErrorCode.ENCRYPTION_FAILED, f"Ошибка шифрования архива: {exc}") from exc


def verify_password(path: str | Path, password: str) -> bool:
    """Быстрая проверка пароля: расшифровывается только первый кусок.

    Полная расшифровка не нужна ни модалкам, ни тихой пробе сохранённого
    пароля — GCM-тег первого куска достаточно надёжно отличает верный пароль
    от неверного. Ничего не пишется на диск; сам пароль не логируется.
    """
    if not password:
        return False
    try:
        with open(path, "rb") as in_fh:
            raw = in_fh.read(_HEADER.size)
            if len(raw) != _HEADER.size:
                return False
            magic, version, n, r, p, salt, nonce_prefix, chunk_size = _HEADER.unpack(raw)
            if magic != MAGIC or version != VERSION:
                return False
            if (n, r, p) != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
                return False
            if chunk_size <= 0 or chunk_size > 64 * 1024 * 1024:
                return False
            blob = in_fh.read(chunk_size + TAG_LEN)
            if not blob:
                # Ни одного куска — это не B4VE-поток
                return False
            key = _derive_key(password, salt)
            aesgcm = AESGCM(key)
            last = len(blob) < chunk_size + TAG_LEN
            aesgcm.decrypt(_nonce(nonce_prefix, 0), blob, _aad(raw, 0, last))
            return True
    except Exception:
        # InvalidTag (неверный пароль), битый/недоступный файл — всё это
        # «пароль не подтверждён», отдельных кодов ошибки probing не требует.
        return False


def decrypt_file(src: str | Path, dst: str | Path, password: str) -> None:
    """Потоковая расшифровка src → dst (dst перезаписывается, режим 0600)."""
    _check_password(password)
    try:
        with open(src, "rb") as in_fh:
            raw = in_fh.read(_HEADER.size)
            if len(raw) != _HEADER.size:
                raise BackupError(ErrorCode.ENCRYPTION_UNSUPPORTED, "Архив повреждён: неполный header B4VE")
            magic, version, n, r, p, salt, nonce_prefix, chunk_size = _HEADER.unpack(raw)
            if magic != MAGIC:
                raise BackupError(ErrorCode.ENCRYPTION_UNSUPPORTED, "Это не B4VE-архив")
            if version != VERSION:
                raise BackupError(
                    ErrorCode.ENCRYPTION_UNSUPPORTED,
                    f"Неподдерживаемая версия B4VE: {version}",
                )
            if (n, r, p) != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
                # Чужие параметры scrypt не принимаем: crafted-header с
                # гигантским N = memory-bomb при выводе ключа
                raise BackupError(ErrorCode.ENCRYPTION_UNSUPPORTED, "Архив повреждён: параметры scrypt")
            if chunk_size <= 0 or chunk_size > 64 * 1024 * 1024:
                raise BackupError(ErrorCode.ENCRYPTION_UNSUPPORTED, "Архив повреждён: некорректный размер куска")
            key = _derive_key(password, salt)
            aesgcm = AESGCM(key)
            fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as out_fh:
                counter = 0
                carry = b""
                while True:
                    blob, carry, last = _read_chunk(in_fh, chunk_size + TAG_LEN, carry)
                    if not blob:
                        # Ни один кусок не был помечен «последним» —
                        # архив обрезан (или это вообще не B4VE-поток)
                        raise BackupError(
                            ErrorCode.ENCRYPTION_PASSWORD_INVALID,
                            "Неверный пароль или архив повреждён (обрезан)",
                        )
                    try:
                        plain = aesgcm.decrypt(
                            _nonce(nonce_prefix, counter), blob, _aad(raw, counter, last)
                        )
                    except Exception as exc:
                        raise BackupError(
                            ErrorCode.ENCRYPTION_PASSWORD_INVALID,
                            "Неверный пароль или архив повреждён",
                        ) from exc
                    out_fh.write(plain)
                    counter += 1
                    if last:
                        break
    except BackupError:
        raise
    except OSError as exc:
        raise BackupError(ErrorCode.ENCRYPTION_FAILED, f"Ошибка расшифровки архива: {exc}") from exc


def encrypt_in_place(path: str | Path, password: str) -> None:
    """Зашифровать файл на месте: staging tar.gz → B4VE (tmp + replace)."""
    path = Path(path)
    tmp = path.with_name(path.name + ".b4ve.tmp")
    try:
        encrypt_file(path, tmp, password)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def decrypt_in_place(path: str | Path, password: str) -> None:
    """Расшифровать файл на месте: B4VE → tar.gz (tmp + replace)."""
    path = Path(path)
    tmp = path.with_name(path.name + ".plain.tmp")
    try:
        decrypt_file(path, tmp, password)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
