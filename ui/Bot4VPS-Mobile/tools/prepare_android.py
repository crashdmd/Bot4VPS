#!/usr/bin/env python3
"""Temporary, verified Android build environment; no emulator or system install."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import tarfile
import shutil
import zipfile
from xml.etree import ElementTree as ET

root = Path(__file__).resolve().parent.parent
env = Path(os.environ.get("BOT4VPS_BUILD_ENV", str(root / ".build-env")))
env.mkdir(parents=True, exist_ok=True)

def fetch(url):
    for attempt in range(3):
        target = url.replace("https://downloads.gradle.org/", "https://services.gradle.org/") if attempt else url
        try:
            return subprocess.check_output(["curl", "--fail", "--location", "--silent", "--show-error", "--connect-timeout", "10", "--max-time", "30", target])
        except (OSError, subprocess.CalledProcessError):
            if attempt == 2: raise
            time.sleep(3)

def archive(url, name, checksum, algorithm="sha256"):
    path = env / name
    if not path.exists():
        print("Downloading", name, flush=True)
        partial = path.with_suffix(path.suffix + ".part")
        subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error", "--connect-timeout", "10", "--max-time", "300", "--speed-limit", "1024", "--speed-time", "30", "--retry", "2", "--retry-delay", "3", "--output", str(partial), url], check=True)
        partial.rename(path)
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): digest.update(chunk)
    if digest.hexdigest() != checksum.strip():
        raise RuntimeError("Checksum mismatch: " + name)
    return path

if not (env / "jdk/bin/java").exists():
    try:
        assets = json.loads(fetch("https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture=x64&image_type=jdk&os=linux&vendor=eclipse"))
        package = assets[0]["binary"]["package"]
        path = archive(package["link"], "jdk.tar.gz", package["checksum"])
    except subprocess.CalledProcessError:
        # An official alternative when GitHub release downloads are unavailable.
        packages = json.loads(fetch("https://api.azul.com/metadata/v1/zulu/packages/?java_version=17&os=linux&arch=x86&archive_type=tar.gz&java_package_type=jdk&release_status=ga&availability_types=CA&latest=true"))
        candidates = [p for p in packages if p["name"].endswith("-linux_x64.tar.gz") and "-fx-" not in p["name"] and "-crac-" not in p["name"]]
        # A newly published CDN file can stall while the prior official JDK 17
        # is already available. Both choices use Azul's exact SHA-256 metadata.
        for index, package in enumerate(candidates[:2]):
            try:
                detail = json.loads(fetch("https://api.azul.com/metadata/v1/zulu/packages/" + package["package_uuid"]))
                path = archive(detail["download_url"], "jdk-zulu-" + str(index) + ".tar.gz", detail["sha256_hash"])
                break
            except subprocess.CalledProcessError:
                if index == len(candidates[:2]) - 1: raise
        else:
            raise RuntimeError("No official Linux x64 JDK 17 package found")
    with tarfile.open(path) as tar:
        top = Path(tar.getmembers()[0].name).parts[0]
        tar.extractall(env, filter="data")
    (env / "jdk").symlink_to(env / top, target_is_directory=True)
if not (env / "gradle-8.9/bin/gradle").exists():
    base = "https://downloads.gradle.org/distributions/gradle-8.9-bin.zip"
    checksum = fetch(base + ".sha256").decode()
    try:
        path = archive(base, "gradle.zip", checksum)
    except subprocess.CalledProcessError:
        release = json.loads(fetch("https://api.github.com/repos/gradle/gradle-distributions/releases/tags/v8.9.0"))
        asset = next(item for item in release["assets"] if item["name"] == "gradle-8.9-bin.zip")
        partial = env / "gradle.zip.part"
        subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error", "--connect-timeout", "10", "--max-time", "300", "--header", "Accept: application/octet-stream", "--output", str(partial), asset["url"] + "?download=1"], check=True)
        partial.rename(env / "gradle.zip")
        path = archive(base, "gradle.zip", checksum)
    with zipfile.ZipFile(path) as z:
        z.extractall(env)
    (env / "gradle-8.9/bin/gradle").chmod(0o755)
sdk = env / "android-sdk"
def install_sdk_package(package_path, target, marker):
    if (target / marker).exists(): return
    repository = ET.fromstring(fetch("https://dl.google.com/android/repository/repository2-3.xml"))
    package = next(item for item in repository.findall(".//{*}remotePackage") if item.attrib.get("path") == package_path)
    item = next(item for item in package.findall(".//{*}archive") if item.findtext("{*}host-os") in (None, "linux"))
    complete = item.find("{*}complete")
    name = "sdk-" + package_path.replace(";", "-") + ".zip"
    source = archive("https://dl.google.com/android/repository/" + complete.findtext("{*}url"), name, complete.findtext("{*}checksum"), "sha1")
    unpack = env / (name + "-unpack")
    if unpack.exists(): shutil.rmtree(unpack)
    unpack.mkdir()
    with zipfile.ZipFile(source) as z:
        z.extractall(unpack)
        for info in z.infolist():
            extracted = unpack / info.filename
            if extracted.is_file() and info.external_attr >> 16 & 0o111: extracted.chmod(0o755)
    directories = [path for path in unpack.iterdir() if path.is_dir()]
    if len(directories) != 1: raise RuntimeError("Unexpected SDK archive layout: " + name)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists(): shutil.rmtree(target)
    directories[0].rename(target)
    shutil.rmtree(unpack)
    licenses = sdk / "licenses"
    licenses.mkdir(exist_ok=True)
    for license in repository.findall("{*}license"):
        license_text = "".join(license.itertext()).strip()
        digest = hashlib.sha1(license_text.encode()).hexdigest()
        license_file = licenses / license.attrib["id"]
        accepted = license_file.read_text().splitlines() if license_file.exists() else []
        if digest not in accepted: license_file.write_text("\n".join(accepted + [digest]) + "\n")
    if not (target / marker).exists(): raise RuntimeError("SDK package incomplete: " + package_path)

install_sdk_package("platforms;android-35", sdk / "platforms/android-35", "android.jar")
install_sdk_package("build-tools;35.0.0", sdk / "build-tools/35.0.0", "aapt2")
install_sdk_package("platform-tools", sdk / "platform-tools", "adb")
signing = root / ".signing/debug.keystore"
signing.parent.mkdir(exist_ok=True)
signing.parent.chmod(0o700)
if not signing.exists():
    subprocess.run([str(env / "jdk/bin/keytool"), "-genkeypair", "-keystore", str(signing), "-storepass", "android", "-keypass", "android", "-alias", "androiddebugkey", "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000", "-storetype", "JKS", "-dname", "CN=Android Debug,O=Android,C=US"], check=True)
signing.chmod(0o600)
print("Build environment ready:", env, flush=True)
