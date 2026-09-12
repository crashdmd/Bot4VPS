"""Bootstrap системной команды bot4vps (/usr/local/bin/bot4vps).

Команда — часть ui/cli, поэтому CLI сам гарантирует её наличие: проверка
идёт при каждом запуске приложения (Web+TG и TG-only — при старте сервиса,
само CLI — в начале main()). Неважно, каким путём новая версия попала на
машину: Web-обновление, install.sh, перенос файлов, восстановление —
первый запуск создаёт/чинит команду.
Идемпотентно: корректный исполняемый файл не трогается (один stat+read);
некорректный/отсутствующий — атомарно создаётся (tmp + os.replace).
Не-фатально: это bootstrap, ошибки (не-root, RO-fs) тихо пропускаются.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Каталог установки — из расположения самого модуля (ui/cli/bootstrap.py →
# корень проекта), а не хардкодом: обёртка обязана указывать на реальное
# место, откуда её запустили.
INSTALL_DIR = Path(__file__).resolve().parents[2]

COMMAND_PATH = Path("/usr/local/bin/bot4vps")

_EXPECTED = (
    "#!/bin/sh\n"
    "# Консольное меню Bot4VPS (python -m ui.cli)\n"
    "cd {install_dir} || exit 1\n"
    "exec ./venv/bin/python -m ui.cli \"$@\"\n"
)


def _expected_content() -> str:
    return _EXPECTED.format(install_dir=INSTALL_DIR)


def ensure_cli_command() -> bool:
    """Гарантировать наличие корректной команды bot4vps.

    Возвращает True, если команда в порядке (была или исправлена),
    False — если не получилось (нет прав и т.п.; вызывающий продолжает
    работу — это не критическая ошибка).
    """
    try:
        expected = _expected_content()
        if COMMAND_PATH.is_file():
            current = COMMAND_PATH.read_text(encoding="utf-8")
            if current == expected:
                # Содержимое верное: остался только бит исполняемости
                if not os.access(COMMAND_PATH, os.X_OK):
                    COMMAND_PATH.chmod(0o755)
                return True
        return _write_command(expected)
    except OSError:
        return False


def _write_command(content: str) -> bool:
    """Атомарно создать/заменить команду: tmp → chmod → os.replace."""
    try:
        COMMAND_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(COMMAND_PATH.parent), prefix=".bot4vps-", suffix=".tmp"
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp_path, 0o755)
            os.replace(tmp_path, COMMAND_PATH)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
        return True
    except OSError:
        return False
