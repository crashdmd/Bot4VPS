#!/usr/bin/env python3
"""Regenerate the runtime, optional Certbot and separate test-repo hash locks."""
from pathlib import Path
import argparse
import subprocess
import shutil

ROOT = Path(__file__).resolve().parents[1]
UV_VERSION = "0.9.21"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", default=shutil.which("uv") or "uv")
    parser.add_argument("--upgrade-package", action="append", default=[])
    args = parser.parse_args()
    version = subprocess.check_output([args.uv, "--version"], text=True).strip().split()
    if version[:2] != ["uv", UV_VERSION]:
        parser.error(f"Use uv {UV_VERSION} in a separate development environment")
    common = [args.uv, "pip", "compile", "--universal", "--python-version", "3.10",
              "--no-python-downloads", "--generate-hashes", "--quiet"]
    upgrades = [part for name in args.upgrade_package for part in ("--upgrade-package", name)]
    subprocess.run(common + ["requirements.in", "--output-file", "requirements.txt",
                            "--custom-compile-command", "python3 tools/lock_dependencies.py"] + upgrades,
                   cwd=ROOT, check=True)
    subprocess.run(common + ["requirements.in", "requirements-certbot.in", "--constraints", "requirements.txt",
                            "--output-file", "requirements-certbot.txt",
                            "--custom-compile-command", "python3 tools/lock_dependencies.py"] + upgrades,
                   cwd=ROOT, check=True)
    shutil.copyfile(ROOT / "requirements-certbot.txt",
                    ROOT / "core/migration/privileged/requirements-certbot.txt")
    tests = ROOT / "tests" / "ci" / "requirements.in"
    if tests.is_file():
        subprocess.run(common + ["requirements.in", "tests/ci/requirements.in", "--constraints", "requirements.txt",
                                "--output-file", "tests/ci/requirements.txt",
                                "--custom-compile-command", "python3 tools/lock_dependencies.py"] + upgrades,
                       cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
