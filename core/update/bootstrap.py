"""Fresh-install verification, embedded in install.sh with its trusted verifier.

Only standard-library modules and the distribution's python3-cryptography
are used before the signed source and its dependency lock are trusted.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import re
import shutil
import sys
import tarfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from . import release_verify as trust
except ImportError:  # Standalone installer: the trusted module is embedded.
    import release_verify as trust

RELEASES_API = f"https://api.github.com/repos/{trust.REPOSITORY}/releases?per_page=100"
HOSTS = {"github.com", "api.github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
PRIVATE_ROOTS = {".git", "config.json", "servers.json", "monitor.json", "keys", "data", "logs", "backup", "venv", "tests", ".local-build", ".local-archives"}
MAX_UNPACKED = 1024 * 1024 * 1024


def check_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.port not in (None, 443)
            or parsed.username is not None or parsed.password is not None):
        raise ValueError("Недопустимый адрес загрузки релиза")


class ReleaseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str, limit: int, destination: Path | None = None) -> bytes:
    check_url(url)
    request = Request(url, headers={"User-Agent": "Bot4VPS installer", "Accept": "application/json" if destination is None else "application/octet-stream"})
    opener = build_opener(ReleaseRedirect())
    total = 0
    data = bytearray()
    with opener.open(request, timeout=60) as response:
        check_url(response.geturl())
        with destination.open("xb") if destination else nullcontext() as stream:
            while block := response.read(min(256 * 1024, limit + 1 - total)):
                total += len(block)
                if total > limit:
                    raise ValueError("Файл релиза превышает допустимый размер")
                if stream is not None:
                    stream.write(block)
                else:
                    data.extend(block)
    return bytes(data)


def latest_tag(data: bytes) -> str:
    releases = json.loads(data)
    if not isinstance(releases, list):
        raise ValueError("Не удалось прочитать список стабильных релизов")
    tags = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name")
        try:
            version = trust.normalized_version(tag)
        except trust.ReleaseTrustError:
            continue
        tags.append((tuple(map(int, version.split("."))), tag))
    if not tags:
        raise ValueError("Нет стабильного релиза Bot4VPS. Установка из main запрещена")
    return max(tags)[1]


def extract_verified(archive: Path, destination: Path, payload: dict) -> Path:
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        while block := stream.read(256 * 1024):
            digest.update(block)
    if archive.stat().st_size != payload["archive"]["size"] or digest.hexdigest() != payload["archive"]["sha256"]:
        raise ValueError("Размер или SHA256 архива не совпадает с подписанным релизом")
    source = destination / "source"
    with tarfile.open(archive, "r:gz") as tar:
        if tar.pax_headers.get("comment") != payload["commit"]:
            raise ValueError("Git-коммит архива не совпадает с подписанным релизом")
        members = tar.getmembers()
        prefix = f'Bot4VPS-{payload["version"]}'
        paths = set()
        total = 0
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != prefix:
                raise ValueError("Архив содержит недопустимый путь")
            if not member.isfile() and not member.isdir():
                raise ValueError("Ссылки и специальные файлы в архиве запрещены")
            if len(path.parts) == 1:
                if not member.isdir():
                    raise ValueError("Неверный корневой каталог архива")
                continue
            relative = PurePosixPath(*path.parts[1:])
            if relative.parts[0] in PRIVATE_ROOTS or relative in paths:
                raise ValueError("Архив содержит рабочие данные или повторяющийся путь")
            paths.add(relative)
            total += member.size
            if total > MAX_UNPACKED:
                raise ValueError("Распакованный архив слишком большой")
        source.mkdir()
        for member in members:
            relative = PurePosixPath(*PurePosixPath(member.name).parts[1:])
            target = source / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as stream, target.open("xb") as out:
                    shutil.copyfileobj(stream, out)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    version_source = (source / "core/version.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*[\'"]([^\'"]+)[\'"]\s*$', version_source, re.MULTILINE)
    if match is None or match.group(1) != payload["version"] or not (source / "bot.py").is_file():
        raise ValueError("Версия или состав исходников не совпадает с релизом")
    return source


def prepare(destination: Path) -> dict:
    tag = latest_tag(download(RELEASES_API, 4 * 1024 * 1024))
    envelope = trust.decode_envelope(download(trust.manifest_url(tag), trust.MAX_MANIFEST_BYTES))
    payload = trust.verify_envelope(envelope, tag)
    if payload["tag"] != tag:
        raise ValueError("Подпись относится к другому тегу")
    archive = destination / payload["archive"]["name"]
    download(trust.archive_url(payload), payload["archive"]["size"], archive)
    extract_verified(archive, destination, payload)
    return payload


def install_source(source: Path, destination: Path):
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise ValueError("Каталог установки не должен быть ссылкой или файлом")
    # Validate every destination before copying even the first source file.
    for entry in source.rglob("*"):
        relative = entry.relative_to(source)
        if relative.parts[0] in PRIVATE_ROOTS or entry.is_symlink():
            raise ValueError("Недопустимый файл установки")
        target = destination / relative
        for component in (target, *target.parents):
            if component.is_symlink():
                raise ValueError("Ссылки в каталоге установки запрещены")
        if target.exists() and target.is_dir() != entry.is_dir():
            raise ValueError("Тип файла в каталоге установки не совпадает")
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("prepare")
    fetch.add_argument("destination", type=Path)
    install = sub.add_parser("install")
    install.add_argument("source", type=Path)
    install.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            payload = prepare(args.destination)
            print(f'Проверен стабильный подписанный релиз {payload["version"]} ({payload["commit"][:12]})')
        else:
            install_source(args.source, args.destination)
    except Exception as exc:
        print(f"Установка остановлена: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
