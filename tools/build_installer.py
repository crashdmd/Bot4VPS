#!/usr/bin/env python3
"""Embed the reviewed verifier/bootstrap in the standalone shell installer."""
from __future__ import annotations

import argparse
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN = "# BEGIN GENERATED RELEASE BOOTSTRAP"
END = "# END GENERATED RELEASE BOOTSTRAP"


def render(verifier: bytes, bootstrap: bytes) -> str:
    encoded_verifier = base64.b64encode(verifier).decode()
    encoded_bootstrap = base64.b64encode(bootstrap).decode()
    return f'''{BEGIN}
# Source: core/update/release_verify.py + bootstrap.py; tools/build_installer.py
run_install_bootstrap() {{
    "$PYTHON" - "$@" <<'B4V_BOOTSTRAP_PY'
import base64, sys, types
verifier = types.ModuleType("release_verify")
sys.modules[verifier.__name__] = verifier
exec(compile(base64.b64decode("{encoded_verifier}"), "<trusted release verifier>", "exec"), verifier.__dict__)
exec(compile(base64.b64decode("{encoded_bootstrap}"), "<trusted install bootstrap>", "exec"), {{"__name__": "__main__", "__package__": None}})
B4V_BOOTSTRAP_PY
}}
{END}'''


def build(root: Path = ROOT) -> str:
    path = root / "install.sh"
    text = path.read_text()
    start = text.index(BEGIN)
    end = text.index(END, start) + len(END)
    return text[:start] + render((root / "core/update/release_verify.py").read_bytes(),
                                (root / "core/update/bootstrap.py").read_bytes()) + text[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = build()
    path = ROOT / "install.sh"
    if args.check:
        if path.read_text() != rendered:
            raise SystemExit("install.sh bootstrap is stale; run tools/build_installer.py")
    else:
        path.write_text(rendered)


if __name__ == "__main__":
    main()
