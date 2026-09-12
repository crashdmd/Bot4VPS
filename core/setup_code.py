"""Код первичной установки (создание первого администратора Web).

Владелец кода — systemd drop-in ``/etc/systemd/system/bot4vps.service.d/
setup.conf`` с ``Environment=B4V_SETUP_CODE=...`` (права 0600, атомарная
запись tmp + os.replace).

Файл = источник истины: работающий Web читает его при каждом запросе,
поэтому код, выданный CLI по этому же файлу, подхватывается БЕЗ рестарта
сервиса. Env ``B4V_SETUP_CODE`` — только фолбэк: daemon-reload не меняет
окружение живого процесса, поэтому env не может быть источником истины
для уже запущенного Web.

После создания администратора drop-in удаляется (unlink + daemon-reload +
очистка env в текущем процессе) — второго «первого запуска» не бывает.

Install-time паритет: install.sh пишет этот же drop-in своим кодом при
установке (сервис ещё не запущен) — сознательное дублирование, как с
юнитами systemd (прецедент — write_web_unit в install.sh и ui/cli/
systemd_ops.py). Формат строки Environment= здесь и там должен совпадать.

Код живёт 10 минут (SETUP_CODE_TTL_SECONDS, возраст = mtime drop-in):
перевыпуск — CLI «Восстановление → Код первичной установки».
"""
from __future__ import annotations

import os
import re
import secrets
import subprocess
import time
from pathlib import Path

SERVICE_NAME = "bot4vps"
DROPIN_DIR = Path("/etc/systemd/system") / f"{SERVICE_NAME}.service.d"
DROPIN_FILE = DROPIN_DIR / "setup.conf"
ENV_VAR = "B4V_SETUP_CODE"

# Код — одноразовый секрет, открывающий мастер создания админа: живёт
# 10 минут с момента выдачи (mtime drop-in). Перевыпуск — одной командой
# CLI («Восстановление → Код первичной установки»), поэтому ограничение
# срока не запирает установку: истёкший код панель не открывает, новый
# выдаётся сразу. issue/перевыпуск обновляет mtime — срок начинается заново.
SETUP_CODE_TTL_SECONDS = 600

# Environment=B4V_SETUP_CODE=<код без пробелов>
_CODE_RE = re.compile(r"^Environment=" + re.escape(ENV_VAR) + r"=(\S+)\s*$", re.MULTILINE)


def setup_code_state() -> dict:
    """Полное состояние кода: значение, срок, источник.

    {"code": str|None, "expired": bool, "age": float|None,
     "ttl_left": float|None, "source": "file"|"env"|None}.

    Возраст файла — mtime drop-in (запись атомарная, mtime = момент
    выдачи). Истёкший код НЕ возвращается в "code": текущий владелец
    состояния (Web-гейт, мастер) обязан видеть его как отсутствующий,
    иначе панель со свежей установки (auth off) открылась бы по коду,
    который давно скомпрометирован. Для env-фолбэка срока нет: env
    попадает в процесс только при старте с существующим drop-in, а
    легитимное удаление кода чистит env в этом же процессе.
    """
    try:
        text = DROPIN_FILE.read_text(encoding="utf-8")
        mtime = DROPIN_FILE.stat().st_mtime
    except OSError:
        text = ""
        mtime = None
    if mtime is not None:
        m = _CODE_RE.search(text)
        if m:
            age = max(0.0, time.time() - mtime)
            expired = age > SETUP_CODE_TTL_SECONDS
            return {
                "code": None if expired else m.group(1),
                "expired": expired,
                "age": age,
                "ttl_left": None if expired else max(0.0, SETUP_CODE_TTL_SECONDS - age),
                "source": "file",
            }
    env = os.environ.get(ENV_VAR) or None
    if env:
        return {
            "code": env,
            "expired": False,
            "age": None,
            "ttl_left": None,
            "source": "env",
        }
    return {
        "code": None,
        "expired": False,
        "age": None,
        "ttl_left": None,
        "source": None,
    }


def current_setup_code() -> str | None:
    """Действующий (не истёкший) код установки: файл, затем env-фолбэк.

    Читается при каждом вызове (файл крошечный): код, выданный CLI в
    работающей системе, становится виден Web без рестарта.
    """
    return setup_code_state()["code"]


def issue_setup_code() -> str:
    """Сгенерировать новый код и записать drop-in (+ daemon-reload)."""
    code = secrets.token_urlsafe(15)
    write_setup_code(code)
    return code


def write_setup_code(code: str) -> None:
    """Атомарно записать drop-in с кодом (0600 — код открывает мастер)."""
    code = (code or "").strip()
    if not code or any(ch.isspace() for ch in code):
        raise ValueError("Код установки не может быть пустым или содержать пробелы")
    DROPIN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DROPIN_FILE.with_name(DROPIN_FILE.name + ".tmp")
    tmp.write_text(
        "[Service]\nEnvironment=%s=%s\n" % (ENV_VAR, code),
        encoding="utf-8",
    )
    os.chmod(tmp, 0o600)
    os.replace(tmp, DROPIN_FILE)
    _daemon_reload()


def remove_setup_code() -> None:
    """Удалить код: unlink + daemon-reload + очистка env процесса.

    Очистка os.environ обязательна: если процесс стартовал с env-кодом,
    после unlink файла фолбэк продолжал бы возвращать старый код.
    Вызывающая сторона (Web после создания админа) ничего больше не
    чистит — состояние мастера вычисляется по факту (код есть/нет).
    """
    try:
        DROPIN_FILE.unlink(missing_ok=True)
    except OSError as e:
        print(f"[SETUP] не удалось удалить drop-in с кодом: {e}", flush=True)
    os.environ.pop(ENV_VAR, None)
    _daemon_reload()


def _daemon_reload() -> None:
    """Не-фатально: сбой печатается в журнал, код всё ещё записан/удалён."""
    try:
        subprocess.run(
            ["systemctl", "daemon-reload"],
            check=True,
            timeout=60,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[SETUP] daemon-reload не выполнен: {e}", flush=True)
