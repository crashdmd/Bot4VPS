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

.dump (миграционный дамп SQLite) засыпается через sqlite3 в tmp-базу,
проверяется integrity_check и только потом становится x-ui.db.
"""
from __future__ import annotations

import posixpath
import shlex
from typing import Any, Dict

from core.integrator import StepError
from core.ssh import exec_sudo

from . import templates
from .manage import _probe, _run

DB_PATH = f"{templates.XUI_ETC}/x-ui.db"
DB_BACKUP = f"{templates.XUI_ETC}/x-ui.db.bot4vps-backup"
TMP_IMPORT = "/tmp/bot4vps_xui_import.db"
# верхняя граница здравого смысла: их базы — единицы МБ, лимит загрузки
# панелью такой же (5 МБ, как scripts/files)
MAX_IMPORT_SIZE = 5 * 1024 * 1024


def _ensure_sqlite3(ssh, server: dict) -> None:
    """sqlite3 нужен и экспорту (.backup), и импорту (.dump); ставим при отсутствии."""
    if _probe(ssh, server, "command -v sqlite3 >/dev/null && echo yes") == "yes":
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
    tmp = "/tmp/bot4vps_xui_export.db"
    _run(ssh, server,
         f"sqlite3 {shlex.quote(DB_PATH)} '.backup {shlex.quote(tmp)}'",
         step="db_backup", title="Копия базы (sqlite3 .backup)")
    sftp = ssh.open_sftp()
    try:
        with sftp.file(tmp, "r") as f:
            data = f.read()
    finally:
        sftp.close()
        # выгрузили — прибираем за собой
        exec_sudo(ssh, server, f"rm -f {shlex.quote(tmp)}", timeout=30)
    if not data:
        raise StepError("db_export", -1, title="Экспорт базы",
                        detail="база не выгрузилась (пустой файл)")
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in (server_name or "server"))
    return {"data": data, "filename": f"x-ui-{safe or 'server'}.db"}


def import_db(ssh, server: dict, data: bytes, emit=lambda line: None) -> Dict[str, Any]:
    """Загрузить .db / .dump с устройства пользователя и восстановить базу.

    Файл → SFTP /tmp → формат: .dump засыпается в свежую базу, .db
    проверяется integrity_check → стоп панели → бэкап текущей базы →
    замена → migrate → старт (авторестарт — база читается при старте).
    Владелец/права как у оригинала: root:root 600 (база содержит креды).
    """
    if len(data) > MAX_IMPORT_SIZE:
        raise StepError("db_import", -1, title="Импорт базы",
                        detail=f"файл больше {MAX_IMPORT_SIZE // (1024 * 1024)} МБ")
    if not data:
        raise StepError("db_import", -1, title="Импорт базы",
                        detail="файл пуст")

    _ensure_sqlite3(ssh, server)
    sftp = ssh.open_sftp()
    try:
        with sftp.file(TMP_IMPORT, "w") as f:
            f.write(data)
    finally:
        sftp.close()
    emit(f"• Файл передан ({len(data)} байт)")

    head = data[:64]
    if head.lstrip().startswith(b"SQLite format 3"):
        # готовая база: проверяем как есть
        check_target = TMP_IMPORT
        emit("• Формат: база SQLite (.db)")
    else:
        # миграционный дамп: засыпаем в свежую базу
        _run(ssh, server,
             f"rm -f {shlex.quote(TMP_IMPORT)}.new && "
             f"sqlite3 {shlex.quote(TMP_IMPORT)}.new < {shlex.quote(TMP_IMPORT)}",
             step="db_dump_restore", title="Развёртывание дампа (.dump) в базу")
        check_target = f"{TMP_IMPORT}.new"
        emit("• Формат: дамп SQLite (.dump) — развёрнут в базу")

    ok = _probe(ssh, server,
                f"sqlite3 {shlex.quote(check_target)} 'PRAGMA integrity_check;' 2>&1")
    if ok != "ok":
        raise StepError("db_import", -1, title="Импорт базы",
                        detail=f"файл не является корректной базой/дампом SQLite "
                               f"(integrity_check: {ok[:200]})")
    emit("• integrity_check: ok")

    # стоп → бэкап → замена → права как у оригинала → migrate → старт
    _run(ssh, server, "systemctl stop x-ui 2>/dev/null; exit 0",
         step="db_import_stop", title="Остановка панели")
    _run(ssh, server,
         f"cp -a {shlex.quote(DB_PATH)} {shlex.quote(DB_BACKUP)} 2>/dev/null; exit 0",
         step="db_import_backup", title="Бэкап текущей базы")
    _run(ssh, server,
         f"install -m 600 -o root -g root {shlex.quote(check_target)} {shlex.quote(DB_PATH)}",
         step="db_import_install", title="Установка новой базы")
    try:
        _run(ssh, server, f"{templates.XUI_FOLDER}/x-ui migrate",
             step="db_import_migrate", title="Миграция схемы базы")
    except StepError:
        # миграция не прошла — откатываемся на бэкап, панель не теряем
        _run(ssh, server,
             f"cp -a {shlex.quote(DB_BACKUP)} {shlex.quote(DB_PATH)} 2>/dev/null; exit 0",
             step="db_import_rollback", title="Откат базы")
        _run(ssh, server, "systemctl start x-ui",
             step="db_import_restart", title="Запуск панели")
        raise
    _run(ssh, server, "systemctl start x-ui",
         step="db_import_restart", title="Запуск панели")
    _run(ssh, server, f"rm -f {shlex.quote(TMP_IMPORT)} {shlex.quote(TMP_IMPORT)}.new",
         step="db_import_cleanup", title="Очистка временных файлов")
    return {"ok": True,
            "backup": f"{DB_BACKUP} (прежняя база сохранена на сервере)"}
