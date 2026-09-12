"""Точка входа консольного меню: ``python -m ui.cli`` (или команда bot4vps)."""
import sys

from ui.cli.menu import main

if __name__ == "__main__":
    sys.exit(main())
