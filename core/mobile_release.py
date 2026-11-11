"""Independent Android distribution: fixed public source and verified local cache."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request

from core.install_paths import get_install_path
from core.json_store import atomic_write_json, locked

SOURCE_DIRECTORY = "https://api.github.com/repos/crashdmd/Bot4VPS-Mobile/contents/apk"
MANIFEST_URL = SOURCE_DIRECTORY + "/release.json?ref=main"
BUNDLED_DIR = get_install_path() / "ui/mobile"
CACHE_DIR = get_install_path() / "data/mobile-release"
MAX_APK_SIZE = 49_000_000
CHECK_INTERVAL = 3600
_CHECK_LOCK = threading.RLock()
_RELEASE_LOCK = threading.RLock()
APK_NAME = "Bot4VPS-Mobile.apk"


@dataclass(frozen=True)
class Release:
    path: Path
    version: str
    size: int
    sha256: str
    installation_note: str = ""
    version_code: int = 0


def _version(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,5}\.[0-9]{1,5}(?:\.[0-9]{1,5})?", value):
        raise ValueError("Некорректная версия APK")
    parts = tuple(map(int, value.split(".")))
    return parts if len(parts) == 3 else (*parts, 0)


def _manifest(data: dict, *, remote=False) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Некорректные метаданные APK")
    version = data.get("version")
    _version(version)
    if data.get("filename") != f"Bot4VPS-Mobile-{version}-release.apk":
        raise ValueError("Некорректное имя APK")
    size, digest = data.get("size"), data.get("sha256")
    code = data.get("versionCode", 0)
    if (type(size) is not int or not 0 < size <= MAX_APK_SIZE
            or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or type(code) is not int or not 0 <= code <= 2_147_483_647 or remote and code == 0):
        raise ValueError("Метаданные APK не прошли проверку")
    note, changes = data.get("installation_note", ""), data.get("changelog", "")
    if not isinstance(note, str) or len(note) > 2000 or not isinstance(changes, str) or len(changes) > 30_000:
        raise ValueError("Описание APK слишком большое или повреждено")
    return {"version": version, "versionCode": code, "filename": data["filename"],
            "size": size, "sha256": digest, "installation_note": note, "changelog": changes}


def _json_file(path: Path) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("Метаданные APK слишком большие")
    return json.loads(raw)


def _verify(path: Path, root: Path, data: dict) -> Release:
    if path.is_symlink() or path.resolve().parent != root.resolve():
        raise ValueError("Недопустимый путь APK")
    if path.stat().st_size != data["size"]:
        raise ValueError("Размер APK не совпадает")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if path.stat().st_size != data["size"] or digest.hexdigest() != data["sha256"]:
        raise ValueError("Размер или контрольная сумма APK не совпадают")
    return Release(path, data["version"], data["size"], data["sha256"],
                   data["installation_note"], data["versionCode"])


def bundled_release(directory: Path | None = None) -> Release:
    root = Path(directory) if directory is not None else BUNDLED_DIR
    data = _manifest(_json_file(root / "release.json"))
    return _verify(root / data["filename"], root, data)


def cached_release() -> Release:
    with locked(CACHE_DIR / "release.lock", _RELEASE_LOCK):
        _recover_publication()
        data = _manifest(_json_file(CACHE_DIR / "release.json"), remote=True)
        return _verify(CACHE_DIR / APK_NAME, CACHE_DIR, data)


def selected_release(directory: Path | None = None) -> Release:
    releases = []
    for load in (cached_release, lambda: bundled_release(directory)):
        try:
            releases.append(load())
        except (OSError, ValueError, TypeError, KeyError):
            pass
    if not releases:
        raise ValueError("Релиз приложения пока недоступен. Проверьте источник APK в настройках.")
    return max(releases, key=lambda item: (_version(item.version), item.version_code))


def open_selected(directory: Path | None = None):
    """Open the validated inode before publication can replace its pathname."""
    with locked(CACHE_DIR / "release.lock", _RELEASE_LOCK):
        release = selected_release(directory)
        return release, release.path.open("rb")


def _recover_publication() -> None:
    pending, rollback = CACHE_DIR / ".pending.json", CACHE_DIR / ".rollback.apk"
    if not pending.exists():
        return
    data = _manifest(_json_file(pending), remote=True)
    try:
        _verify(CACHE_DIR / APK_NAME, CACHE_DIR, data)
    except (OSError, ValueError):
        # The swap did not happen, or the temporary replacement was damaged.
        if rollback.exists():
            os.replace(rollback, CACHE_DIR / APK_NAME)
    else:
        atomic_write_json(CACHE_DIR / "release.json", data)
    rollback.unlink(missing_ok=True)
    pending.unlink(missing_ok=True)


def _publish(temporary: Path, data: dict) -> None:
    """Publish one APK and metadata under a short reader lock, with recovery."""
    with locked(CACHE_DIR / "release.lock", _RELEASE_LOCK):
        _recover_publication()
        target = CACHE_DIR / APK_NAME
        rollback, pending = CACHE_DIR / ".rollback.apk", CACHE_DIR / ".pending.json"
        if target.is_symlink():
            raise ValueError("Недопустимый путь APK")
        try:
            old_metadata = _json_file(CACHE_DIR / "release.json")
        except (OSError, ValueError):
            old_metadata = None
        had_target = target.exists()
        if had_target:
            os.link(target, rollback)
        try:
            atomic_write_json(pending, data)
            os.replace(temporary, target)
            atomic_write_json(CACHE_DIR / "release.json", data)
        except Exception:
            if rollback.exists():
                os.replace(rollback, target)
            elif not had_target:
                target.unlink(missing_ok=True)
            if old_metadata is not None:
                atomic_write_json(CACHE_DIR / "release.json", old_metadata)
            else:
                (CACHE_DIR / "release.json").unlink(missing_ok=True)
            pending.unlink(missing_ok=True)
            raise
        rollback.unlink(missing_ok=True)
        pending.unlink(missing_ok=True)


def seed_local_release(directory: Path) -> Release:
    """Installer-only migration of a verified supplied APK into writable data."""
    data = _manifest(_json_file(Path(directory) / "release.json"), remote=True)
    supplied = bundled_release(Path(directory))
    with locked(CACHE_DIR / "check.lock", _CHECK_LOCK):
        try:
            current = cached_release()
        except (OSError, ValueError):
            current = None
        if current and (_version(current.version), current.version_code) >= (_version(supplied.version), supplied.version_code):
            return current
        fd, name = tempfile.mkstemp(prefix=".download-", dir=CACHE_DIR)
        os.close(fd)
        temporary = Path(name)
        try:
            shutil.copyfile(supplied.path, temporary)
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            _verify(temporary, CACHE_DIR, data)
            _publish(temporary, data)
        finally:
            temporary.unlink(missing_ok=True)
        return cached_release()


def cache_status() -> dict:
    try:
        state = _json_file(CACHE_DIR / "status.json")
        if not isinstance(state, dict) or type(state.get("checked_at")) not in (int, float):
            raise ValueError()
        return state
    except (OSError, ValueError, TypeError):
        return {"checked_at": 0, "ok": False, "updated": False}


def _source_url(url: str) -> str:
    if url != MANIFEST_URL:
        filename = url.removeprefix(SOURCE_DIRECTORY + "/").removesuffix("?ref=main")
        if url != SOURCE_DIRECTORY + "/" + filename + "?ref=main" or not re.fullmatch(
                r"Bot4VPS-Mobile-[0-9]{1,5}\.[0-9]{1,5}(?:\.[0-9]{1,5})?-release\.apk", filename):
            raise ValueError("Недопустимый источник APK")
    return url


class _SourceRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        _source_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _open(url: str):
    request = urllib.request.Request(_source_url(url), headers={
        "User-Agent": "Bot4VPS-Mobile-Distributor", "Accept": "application/vnd.github.raw+json"})
    response = urllib.request.build_opener(_SourceRedirect()).open(request, timeout=15)
    try:
        _source_url(response.geturl())
    except Exception:
        response.close()
        raise
    return response


def _remote_manifest() -> dict:
    with _open(MANIFEST_URL) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("Метаданные APK слишком большие")
    return _manifest(json.loads(raw), remote=True)


def _download(data: dict, target: Path) -> None:
    started = time.monotonic()
    digest, count = hashlib.sha256(), 0
    with _open(SOURCE_DIRECTORY + "/" + data["filename"] + "?ref=main") as response, target.open("wb") as stream:
        length = response.headers.get("Content-Length")
        if length is not None and int(length) != data["size"]:
            raise ValueError("Размер APK отличается от метаданных")
        while True:
            if time.monotonic() - started > 180:
                raise TimeoutError("Истекло время загрузки APK")
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            count += len(chunk)
            if count > data["size"]:
                raise ValueError("APK превышает заявленный размер")
            digest.update(chunk)
            stream.write(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    if count != data["size"] or digest.hexdigest() != data["sha256"]:
        raise ValueError("Контрольная сумма APK не совпадает")


def _message(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return "APK и release.json ещё не опубликованы в Bot4VPS-Mobile."
        return f"Источник APK вернул ошибку {exc.code}. Повторите позже."
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        return "Не удалось подключиться к источнику APK. Сохранённая версия остаётся доступна."
    return "Метаданные или APK не прошли проверку. Сохранённая версия остаётся доступна."


def refresh(*, force=False, directory: Path | None = None) -> dict:
    """Publish only a complete verified artifact; failed checks keep the old APK."""
    with locked(CACHE_DIR / "check.lock", _CHECK_LOCK):
        previous = cache_status()
        if not force and 0 <= time.time() - previous["checked_at"] < CHECK_INTERVAL:
            return {**previous, "updated": False}
        result = {"checked_at": time.time(), "ok": False, "updated": False,
                  "source": MANIFEST_URL}
        temporary = None
        try:
            data = _remote_manifest()
            try:
                current = selected_release(directory)
            except ValueError:
                current = None
            if current is not None:
                if (_version(data["version"]) < _version(current.version)
                        or data["versionCode"] < current.version_code):
                    result.update(ok=True, version=current.version, versionCode=current.version_code)
                    atomic_write_json(CACHE_DIR / "status.json", result)
                    return result
                if data["versionCode"] == current.version_code and (
                        data["sha256"] != current.sha256 or _version(data["version"]) != _version(current.version)):
                    raise ValueError("Разные APK имеют один versionCode")
            try:
                saved = cached_release()
            except (OSError, ValueError):
                saved = None
            if not saved or saved.sha256 != data["sha256"] or saved.version_code != data["versionCode"]:
                fd, name = tempfile.mkstemp(prefix=".download-", dir=CACHE_DIR)
                os.close(fd)
                temporary = Path(name)
                _download(data, temporary)
                _publish(temporary, data)
                temporary = None
            result.update(ok=True, version=data["version"], versionCode=data["versionCode"],
                          updated=current is None or current.sha256 != data["sha256"])
        except Exception as exc:
            result["error"] = _message(exc)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        atomic_write_json(CACHE_DIR / "status.json", result)
        return result
