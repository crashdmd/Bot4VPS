# -*- coding: utf-8 -*-
"""Экспорт/импорт базы данных 3x-ui (этап 4, блок «Доп. действия»).

Их CLI-меню (x-ui.sh, пункт Database) делает то же самое: скачивание
/etc/x-ui/x-ui.db и загрузка .db/.dump с последующим restore. Мы не
эмулируем их bash — выполняем эквивалентные шаги своим кодом:

- export: консистентная копия sqlite3 (.backup, не cp во время работы)
  → отдаётся панелью как файл на устройство пользователя;
- import: файл с устройства → SFTP → бэкап текущей базы → замена →
  x-ui migrate (доводит схему) → рестарт панели (база читается при
  старте).

.dump восстанавливается библиотекой SQLite в изолированную базу на панели,
проверяется integrity_check и только потом становится x-ui.db.
"""
from __future__ import annotations

import shlex
import uuid
from typing import Any, Dict

from core.integrator import StepError
from core.ssh import checked_output, exec_binary_stream, exec_sudo, private_remote_directory, private_remote_upload

from . import templates
from .manage import _probe, _run

DB_PATH = f"{templates.XUI_ETC}/x-ui.db"
DB_BACKUP = f"{templates.XUI_ETC}/x-ui.db.bot4vps-backup"
# верхняя граница здравого смысла: их базы — единицы МБ, лимит загрузки
# панелью такой же (5 МБ, как scripts/files)
MAX_IMPORT_SIZE = 5 * 1024 * 1024


def _recover(ssh, server, command, **kwargs):
    from core.cancel_flags import recovery_scope
    with recovery_scope():
        return _run(ssh, server, command, **kwargs)


def _ensure_sqlite3(ssh, server: dict) -> None:
    """sqlite3 нужен и экспорту (.backup), и импорту (.dump); ставим при отсутствии."""
    found = checked_output(exec_sudo(ssh, server,
        "if command -v sqlite3 >/dev/null; then echo yes; else echo no; fi"), title="Проверка sqlite3")
    if found == "yes":
        return
    rid = _probe(ssh, server, ". /etc/os-release 2>/dev/null; echo $ID")
    pkgs = {
        "debian": "apt-get update -qq && apt-get install -y -qq sqlite3",
        "ubuntu": "apt-get update -qq && apt-get install -y -qq sqlite3",
        "armbian": "apt-get update -qq && apt-get install -y -qq sqlite3",
        "fedora": "dnf makecache -y -q && dnf -y -q install sqlite",
        "amzn": "dnf makecache -y -q && dnf -y -q install sqlite",
        "virtuozzo": "dnf makecache -y -q && dnf -y -q install sqlite",
        "rhel": "dnf makecache -y -q && dnf -y -q install sqlite",
        "almalinux": "dnf makecache -y -q && dnf -y -q install sqlite",
        "rocky": "dnf makecache -y -q && dnf -y -q install sqlite",
        "ol": "dnf makecache -y -q && dnf -y -q install sqlite",
        "centos": "yum makecache -q -y && yum -y -q install sqlite",
        "arch": "pacman -Sy --noconfirm sqlite",
        "manjaro": "pacman -Sy --noconfirm sqlite",
        "parch": "pacman -Sy --noconfirm sqlite",
        "opensuse-tumbleweed": "zypper -q refresh && zypper -q install -y sqlite3",
        "opensuse-leap": "zypper -q refresh && zypper -q install -y sqlite3",
        "alpine": "apk add sqlite",
    }
    cmd = pkgs.get(rid)
    if not cmd:
        raise StepError("sqlite3_install", -1, title="Установка sqlite3",
                        detail=f"дистрибутив не поддерживается: {rid or 'неизвестен'} — "
                               "установите sqlite3 вручную")
    _run(ssh, server, cmd, step="sqlite3_install", title="Установка sqlite3")


def export_db(ssh, server: dict, server_name: str) -> Dict[str, Any]:
    """Консистентная копия x-ui.db → (bytes, filename) — файл на устройство.

    sqlite3 .backup берёт копию при живой панели (cp на бегущей базе
    может отдать битый файл). Ожидаем, что панель сама вызывала
    _card_check_installed.
    """
    _ensure_sqlite3(ssh, server)
    with private_remote_directory(ssh, server, privileged=True) as directory:
        tmp = directory + "/export.db"
        _run(ssh, server,
             f"umask 077 && sqlite3 {shlex.quote(DB_PATH)} {shlex.quote('.backup ' + tmp)}",
             step="db_backup", title="Копия базы (sqlite3 .backup)")
        chunks = []
        code, stderr = exec_binary_stream(ssh, server, ["cat", "--", tmp], chunks.append, timeout=120)
        if code != 0:
            raise StepError("db_export", code, title="Экспорт базы",
                            detail=stderr.decode("utf-8", errors="replace")[:500] or "Не удалось прочитать копию базы через sudo")
        data = b"".join(chunks)
    if not data:
        raise StepError("db_export", -1, title="Экспорт базы",
                        detail="база не выгрузилась (пустой файл)")
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in (server_name or "server"))
    return {"data": data, "filename": f"x-ui-{safe or 'server'}.db"}


def import_db(ssh, server: dict, data: bytes, emit=lambda line: None) -> Dict[str, Any]:
    """Загрузить .db / .dump с устройства пользователя и восстановить базу.

    .dump → ограниченный процесс восстановления на панели → файл .db →
    SFTP → integrity_check → стоп панели → бэкап текущей базы →
    замена → migrate → старт (авторестарт — база читается при старте).
    Владелец/права как у оригинала: root:root 600 (база содержит креды).
    """
    if len(data) > MAX_IMPORT_SIZE:
        raise StepError("db_import", -1, title="Импорт базы",
                        detail=f"файл больше {MAX_IMPORT_SIZE // (1024 * 1024)} МБ")
    if not data:
        raise StepError("db_import", -1, title="Импорт базы",
                        detail="файл пуст")

    from .sql_dump import restore_sql_dump
    is_database = data.startswith(b"SQLite format 3\x00")
    if not is_database:
        data = restore_sql_dump(data)
        emit("• Формат: дамп SQLite (.dump) — проверен и развёрнут в отдельную базу")
    _ensure_sqlite3(ssh, server)
    with private_remote_upload(ssh, server, data) as uploaded:
        emit(f"• Файл передан ({len(data)} байт)")
        check_target = uploaded
        if is_database:
            emit("• Формат: база SQLite (.db)")
        ok = _run(ssh, server,
                  f"sqlite3 {shlex.quote(check_target)} 'PRAGMA integrity_check;'",
                  step="db_import_check", title="Проверка базы SQLite")
        if ok != "ok":
            raise StepError("db_import", -1, title="Импорт базы",
                            detail=f"Файл не является корректной базой/дампом SQLite (integrity_check: {ok[:200]})")
        emit("• integrity_check: ok")
        original_state = _run(ssh, server, "systemctl show x-ui -p ActiveState --value",
                              step="db_import_state", title="Проверка состояния панели")
        if original_state not in {"active", "inactive", "failed"}:
            raise StepError("db_import_state", -1, title="Импорт базы",
                            detail="Не удалось определить стабильное состояние панели. Повторите проверку.")
        was_active = original_state == "active"
        backup = DB_BACKUP + "." + uuid.uuid4().hex
        stop_attempted = False
        replacement_attempted = False
        sidecars = f"{shlex.quote(DB_PATH + '-wal')} {shlex.quote(DB_PATH + '-shm')}"
        try:
            stop_attempted = True
            _run(ssh, server, "systemctl stop x-ui",
                 step="db_import_stop", title="Остановка панели")
            _run(ssh, server,
                 f"umask 077 && sqlite3 {shlex.quote(DB_PATH)} {shlex.quote('.backup ' + backup)} && "
                 f"chmod 600 {shlex.quote(backup)}",
                 step="db_import_backup", title="Бэкап текущей базы")
            replacement_attempted = True
            _run(ssh, server,
                 f"rm -f -- {sidecars} && install -m 600 -o root -g root "
                 f"{shlex.quote(check_target)} {shlex.quote(DB_PATH)}",
                 step="db_import_install", title="Установка новой базы")
            _run(ssh, server, f"{templates.XUI_FOLDER}/x-ui migrate",
                 step="db_import_migrate", title="Миграция схемы базы")
            if was_active:
                _run(ssh, server, "systemctl start x-ui && systemctl is-active --quiet x-ui",
                     step="db_import_restart", title="Запуск панели")
        except Exception as failure:
            recovery_errors = []
            if replacement_attempted:
                try:
                    _recover(ssh, server, "systemctl stop x-ui",
                         step="db_import_rollback_stop", title="Остановка панели перед откатом")
                    _recover(ssh, server,
                         f"rm -f -- {sidecars} && install -m 600 -o root -g root "
                         f"{shlex.quote(backup)} {shlex.quote(DB_PATH)}",
                         step="db_import_rollback", title="Восстановление прежней базы")
                except Exception as recovery:
                    recovery_errors.append(f"Не удалось восстановить прежнюю базу: {recovery}. Копия: {backup}")
            if stop_attempted and was_active and not recovery_errors:
                try:
                    _recover(ssh, server, "systemctl start x-ui && systemctl is-active --quiet x-ui",
                         step="db_import_recover", title="Восстановление работы панели")
                except Exception as recovery:
                    recovery_errors.append(f"Не удалось запустить панель после ошибки: {recovery}")
            if recovery_errors:
                previous_database = backup if replacement_attempted else DB_PATH
                raise StepError("db_import_recovery", -1, title="Импорт базы и восстановление панели",
                                detail=f"Прежняя база: {previous_database}. {failure}. " + " ".join(recovery_errors)) from failure
            emit("• Импорт не завершён; прежняя база и исходное состояние панели восстановлены")
            raise
    return {"ok": True, "backup": f"{backup} (прежняя база сохранена на сервере)"}
