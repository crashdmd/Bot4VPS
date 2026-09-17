# -*- coding: utf-8 -*-
"""Локальный кэш релиз-артефактов 3x-ui.

Раскладка: data/services/3x-ui/version/<tag>/<arch>/x-ui-linux-<arch>.tar.gz
(+ .sha256 рядом). Тег — без «v» (каталог назван «3.7.0», не «v3.7.0»).
Конвенция data/services/<sid>/ сохранена: рядом лежат кэши состояния
<server_id>.json; каталог version/ от файлов их не отличает.

Арх-политика (согласовано): дефолт — arch машины бота (amd64); прочие arch
докачиваются по фактическому спросу при несовпадении с целью и остаются.

Ретеншн: ровно последние 3 semver-версии (по версиям, независимо от того,
сколько arch внутри каждой). Удаление — целиком каталог версии, только
после успешной записи новой (не «сначала почистить, потом скачать»).

Скачивание — stdlib urllib, ретраи с паузами: РФ-канал до GitHub бывает
30-минутным, медленный download — норма, не ошибка.
"""
from __future__ import annotations

import hashlib
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional

from core.install_paths import get_install_path

from . import releases
from .releases import ReleaseError, parse_tag

RETENTION = 3  # сколько последних версий хранить

_DOWNLOAD_RETRIES = 4
_RETRY_PAUSES = (5, 15, 60)  # сек, между попытками (медленный канал — норм)
_CHUNK = 256 * 1024


def cache_root() -> Path:
    """data/services/3x-ui/version/ — относительно корня установки."""
    return get_install_path() / "data" / "services" / "3x-ui" / "version"


def _version_dir(tag: str) -> Path:
    return cache_root() / _norm_tag(tag)


def _norm_tag(tag: str) -> str:
    return str(tag or "").strip().lstrip("v")


def _require_semver(tag: str) -> str:
    if parse_tag(tag) is None:
        raise ReleaseError(f"Некаталожный тег для кэша: {tag!r}")
    return _norm_tag(tag)


def default_arch() -> str:
    """Arch машины бота в терминах артефактов 3x-ui."""
    import platform
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    raise ReleaseError(f"Arch машины бота не поддерживается 3x-ui: {machine}")


# ------------------------------------------------------------------
# Инвентарь (чтение)
# ------------------------------------------------------------------

def list_cached_versions() -> List[str]:
    """Semver-версии в кэше, свежие первыми. Мусорные каталоги игнорируются."""
    root = cache_root()
    if not root.is_dir():
        return []
    found = []
    for child in root.iterdir():
        if child.is_dir() and parse_tag(child.name):
            found.append(child.name)
    return sorted(found, key=lambda t: parse_tag(t), reverse=True)


def has_version(tag: str, arch: Optional[str] = None) -> bool:
    """Артефакт версии (и arch, если указана) полностью в кэше и валиден."""
    arch = arch or default_arch()
    d = _version_dir(tag)
    tarball = d / f"x-ui-linux-{arch}.tar.gz"
    sha = d / f"x-ui-linux-{arch}.tar.gz.sha256"
    return tarball.is_file() and tarball.stat().st_size > 0 and sha.is_file()


def tarball_path(tag: str, arch: Optional[str] = None) -> Path:
    """Локальный путь тарболла (существование не проверяется — has_version
    вызывающий проверяет сам)."""
    arch = arch or default_arch()
    return _version_dir(tag) / f"x-ui-linux-{arch}.tar.gz"


# ------------------------------------------------------------------
# Скачивание + верификация
# ------------------------------------------------------------------

def _fetch(url: str, timeout: int, sink: Callable[[bytes], None]) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": releases.USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        while True:
            chunk = resp.read(_CHUNK)
            if not chunk:
                break
            sink(chunk)


def _download_with_retries(
    tag: str, arch: str, emit: Callable[[str], None]
) -> tuple:
    """Скачать тарболл+sha256 во временные файлы. Возвращает (tmp_dir, sha_line).

    Ретраи с паузами: обрывы и таймауты на медленном канале — норма,
    каждая попытка докачивается с нуля во временный каталог (атомарность:
    в живой каталог попадает только полная пара файлов).
    """
    import tempfile
    tmp_dir = Path(tempfile.mkdtemp(prefix="xui-dl-", dir=cache_root().parent))
    try:
        tar_tmp = tmp_dir / "tarball"
        sha_tmp = tmp_dir / "sha256"

        last_err: Optional[Exception] = None
        for attempt in range(_DOWNLOAD_RETRIES):
            if attempt:
                pause = _RETRY_PAUSES[min(attempt - 1, len(_RETRY_PAUSES) - 1)]
                emit(f"   повтор через {pause}с (попытка {attempt + 1}/{_DOWNLOAD_RETRIES})")
                time.sleep(pause)
            try:
                emit(f"   качаю чексумму {tag}/{arch}")
                buf = bytearray()
                _fetch(releases.sha256_url(tag, arch), 20, buf.extend)
                expected = buf.decode("utf-8", "replace").strip().split()[0]
                if len(expected) != 64 or not re_is_hex(expected):
                    raise ReleaseError(f"Некорректный .sha256 для {tag}: {expected!r}")

                emit(f"   качаю тарболл {tag}/{arch} (медленный канал — норма)")
                h = hashlib.sha256()
                size = 0
                with open(tar_tmp, "wb") as fh:
                    def sink(chunk: bytes) -> None:
                        nonlocal size
                        fh.write(chunk)
                        h.update(chunk)
                        size += len(chunk)
                    _fetch(releases.tarball_url(tag, arch), 120, sink)
                if size == 0:
                    raise ReleaseError(f"Пустой тарболл {tag}/{arch}")

                if h.hexdigest() != expected:
                    raise ReleaseError(
                        f"sha256 не совпал для {tag}/{arch}: "
                        f"ожидался {expected}, получен {h.hexdigest()}"
                    )
                sha_tmp.write_text(expected + "\n", encoding="utf-8")
                return tmp_dir, expected
            except (urllib.error.URLError, OSError, ReleaseError) as e:
                last_err = e
                emit(f"   [!] попытка {attempt + 1} не удалась: {e}")
        raise ReleaseError(
            f"Не удалось скачать {tag}/{arch} за {_DOWNLOAD_RETRIES} попыток: {last_err}"
        )
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def re_is_hex(s: str) -> bool:
    return all(c in "0123456789abcdef" for c in s.lower())


def download(tag: str, arch: Optional[str] = None, emit: Optional[Callable[[str], None]] = None) -> Path:
    """Скачать релиз в кэш (идемпотентно: уже есть и валиден — ничего не делаем).

    Возвращает путь к тарболлу в кэше. По успеху применяет ретеншн.
    """
    tag = _require_semver(tag)
    arch = arch or default_arch()
    emit = emit or (lambda _line: None)

    if has_version(tag, arch):
        emit(f"   {tag}/{arch} уже в кэше")
        return tarball_path(tag, arch)

    emit(f"• Скачивание релиза 3x-ui {tag} ({arch})")
    cache_root().mkdir(parents=True, exist_ok=True)

    tmp_dir, _ = _download_with_retries(tag, arch, emit)
    try:
        dest_dir = _version_dir(tag)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_tar = dest_dir / f"x-ui-linux-{arch}.tar.gz"
        dest_sha = dest_dir / f"x-ui-linux-{arch}.tar.gz.sha256"
        shutil.move(str(tmp_dir / "tarball"), str(dest_tar))
        shutil.move(str(tmp_dir / "sha256"), str(dest_sha))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    emit(f"   {tag}/{arch} в кэше")
    apply_retention()
    return tarball_path(tag, arch)


# ------------------------------------------------------------------
# Ретеншн
# ------------------------------------------------------------------

def apply_retention() -> List[str]:
    """Оставить последние RETENTION версий, старшие каталоги удалить.

    Удаляем только каталоги с semver-именем — мусор/чужие файлы не трогаем.
    Возвращает список удалённых версий (для лога/уведомления).
    """
    versions = list_cached_versions()
    to_remove = versions[RETENTION:]
    for tag in to_remove:
        shutil.rmtree(_version_dir(tag), ignore_errors=True)
    return to_remove


def verify_cached(tag: str, arch: Optional[str] = None) -> bool:
    """Пересчитать sha256 закэшированного артефакта (целостность по требованию;
    download уже верифицирует при скачивании)."""
    arch = arch or default_arch()
    p = tarball_path(tag, arch)
    sha_p = Path(str(p) + ".sha256")
    if not p.is_file() or not sha_p.is_file():
        return False
    expected = sha_p.read_text(encoding="utf-8").strip().split()[0]
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest() == expected
