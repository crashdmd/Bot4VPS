#!/usr/bin/env python3
"""Подготовить архив конкретного Git-коммита и подписанное описание релиза.

Закрытый ключ хранится вне исходников/публикуемых файлов. Эта команда
не делает commit, push или публикацию GitHub и не читает рабочие секреты.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_verify", ROOT / "core/update/release_verify.py")
trust = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trust)


def git(source: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(source), *args], capture_output=True, check=True).stdout


def load_key(path: Path) -> Ed25519PrivateKey:
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("Закрытый ключ должен быть обычным файлом с правами 0600")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Нужен ключ подписи Ed25519")
    return key


def create_key(path: Path) -> None:
    path = path.absolute()
    if path.is_relative_to(ROOT):
        raise ValueError("Создавайте ключ вне исходников проекта")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = Ed25519PrivateKey.generate()
    encoded = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(encoded)
        out.flush()
        os.fsync(out.fileno())
    print("Открытый ключ:", key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex())


def prepare(source: Path, revision: str, key_path: Path, output: Path, tag: str | None = None) -> dict:
    key = load_key(key_path)
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    key_id = next((identifier for identifier, known in trust.TRUSTED_KEYS.items() if known == public), None)
    if key_id is None:
        raise ValueError("Открытый ключ издателя отсутствует в установленном списке доверия")
    commit = git(source, "rev-parse", "--verify", revision + "^{commit}").decode().strip()
    version_source = git(source, "show", f"{commit}:core/version.py").decode()
    match = re.search(r'^APP_VERSION\s*=\s*[\'"]([^\'"]+)[\'"]\s*$', version_source, re.MULTILINE)
    if match is None:
        raise ValueError("В коммите нет версии Bot4VPS")
    version = trust.normalized_version(match.group(1))
    tag = tag or "v" + version
    if trust.normalized_version(tag) != version:
        raise ValueError("Тег не соответствует версии выбранного коммита")
    files = git(source, "ls-tree", "-r", "--name-only", commit).decode().splitlines()
    private_roots = {"config.json", "servers.json", "monitor.json", "keys", "data", "logs", "backup", "venv", ".local-build", ".local-archives", "tests"}
    if any(name.split("/", 1)[0] in private_roots or name.endswith((".keystore", ".jks", ".key")) for name in files):
        raise ValueError("Коммит содержит рабочие данные или закрытые ключи; публикация запрещена")
    certbot_lock = "requirements-certbot.txt"
    bundled_lock = "core/migration/privileged/requirements-certbot.txt"
    if certbot_lock in files or bundled_lock in files:
        if (certbot_lock not in files or bundled_lock not in files
                or git(source, "show", f"{commit}:{certbot_lock}") != git(source, "show", f"{commit}:{bundled_lock}")):
            raise ValueError("Копия зависимостей Certbot для старого updater отсутствует или устарела")
    if key_path.resolve().is_relative_to(source.resolve()) and not key_path.resolve().is_relative_to(source.resolve() / ".local-build"):
        raise ValueError("Закрытый ключ нельзя хранить в исходниках")
    changelog = git(source, "show", f"{commit}:core/update/changelog.md").decode()
    sections = list(re.finditer(r"(?m)^## (\d+(?:\.\d+){0,2})\s*$", changelog))
    description = None
    for i, section in enumerate(sections):
        if trust.normalized_version(section.group(1)) == version:
            description = changelog[section.end():sections[i + 1].start() if i + 1 < len(sections) else len(changelog)].strip()
            break
    if description is None:
        raise ValueError("В коммите нет описания изменений этой версии")
    installer_source = git(source, "show", f"{commit}:install.sh")
    embedded = re.findall(rb'base64\.b64decode\("([A-Za-z0-9+/=]+)"\)', installer_source)
    expected = [git(source, "show", f"{commit}:core/update/{name}")
                for name in ("release_verify.py", "bootstrap.py")]
    if len(embedded) != 2 or [base64.b64decode(value, validate=True) for value in embedded] != expected:
        raise ValueError("Встроенный установщик устарел; выполните tools/build_installer.py до коммита")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"Bot4VPS-{version}.tar.gz"
    manifest = output / trust.MANIFEST_NAME
    installer = output / "install.sh"
    if archive.exists() or manifest.exists() or installer.exists():
        raise ValueError("Файлы релиза уже существуют; подпись и архив не перезаписываются")
    created = []
    try:
        with tempfile.TemporaryFile() as tar:
            subprocess.run(["git", "-C", str(source), "archive", "--format=tar", f"--prefix=Bot4VPS-{version}/", commit], stdout=tar, check=True)
            tar.seek(0)
            with archive.open("xb") as dest:
                created.append(archive)
                with gzip.GzipFile(fileobj=dest, mode="wb", filename="", mtime=0) as zipped:
                    while block := tar.read(256 * 1024):
                        zipped.write(block)
                dest.flush()
                os.fsync(dest.fileno())
        digest = hashlib.sha256()
        with archive.open("rb") as stream:
            while block := stream.read(256 * 1024):
                digest.update(block)
        payload = {"schema": 1, "repository": trust.REPOSITORY, "version": version, "tag": tag, "commit": commit,
                   "archive": {"name": archive.name, "size": archive.stat().st_size, "sha256": digest.hexdigest()}, "changelog": description}
        envelope = {"key_id": key_id, "payload": payload, "signature": base64.b64encode(key.sign(trust.canonical_payload(payload))).decode()}
        trust.verify_envelope(envelope, version)
        with manifest.open("x", encoding="utf-8") as dest:
            created.append(manifest)
            json.dump(envelope, dest, ensure_ascii=False, indent=2)
            dest.write("\n")
            dest.flush()
            os.fsync(dest.fileno())
        with installer.open("xb") as dest:
            created.append(installer)
            dest.write(installer_source)
            dest.flush()
            os.fsync(dest.fileno())
        installer.chmod(0o755)
        print(json.dumps({"version": version, "commit": commit, "archive": str(archive), "manifest": str(manifest), "installer": str(installer), "sha256": digest.hexdigest()}, ensure_ascii=False, indent=2))
        return envelope
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create-key", type=Path)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--key", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--tag")
    args = parser.parse_args()
    try:
        if args.create_key is not None:
            create_key(args.create_key)
        else:
            if args.key is None or args.output is None:
                parser.error("Для подписи нужны --key и --output")
            prepare(args.source, args.commit, args.key, args.output, args.tag)
        return 0
    except Exception as e:
        print(f"Не удалось подготовить релиз: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
