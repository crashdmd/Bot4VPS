"""Консольный вход в тот же подписанный updater, что используется Web/CLI."""
from __future__ import annotations

import argparse
import asyncio
import sys

from core.actor import Actor, set_actor
from core.update import updater


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Только проверить наличие подписанного релиза")
    args = parser.parse_args()
    set_actor(Actor.cli())
    result = asyncio.run(updater.check_for_update(notify=False))
    if result.get("busy"):
        print("Обновление уже выполняется", file=sys.stderr)
        return 1
    if result.get("error"):
        print(result["error"], file=sys.stderr)
        return 1
    if not result.get("update_available"):
        print(f"Подписанных обновлений нет. Установлена версия {updater.APP_VERSION}")
        return 0
    version = result["version"]
    print(f"Доступен подписанный релиз Bot4VPS {version}")
    print(updater.CHANGELOG_NEW_FILE.read_text(encoding="utf-8"))
    if args.check:
        return 0
    try:
        # При curl | bash stdin занят самим установщиком.
        with open("/dev/tty", "r+") as terminal:
            terminal.write("Установить этот релиз? [y/N]: ")
            terminal.flush()
            approved = terminal.readline().strip().lower() in ("y", "yes", "д", "да")
    except OSError:
        if not sys.stdin.isatty():
            print("Для установки нужно подтверждение в интерактивной консоли", file=sys.stderr)
            return 1
        approved = input("Установить этот релиз? [y/N]: ").strip().lower() in ("y", "yes", "д", "да")
    if not approved:
        print("Отмена")
        return 0
    try:
        from ui.cli.ops import update_install
        update_install(version)
        print(f"Установлена версия {version}")
        return 0
    except Exception as e:
        print(f"Обновление не выполнено: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
