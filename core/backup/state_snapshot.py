"""Слепок ``data/state.db`` для архива Bot4VPS и его спутники при restore.

Три факта, из которых следует всё остальное:

* **Живую sqlite нельзя копировать пофайлово.** ``.db`` без ``-wal`` — это
  состояние неизвестной давности, а тройка ``.db`` + ``-wal`` + ``-shm``
  снята в три разных момента (§12.2 ТЗ ``plans/AUDIT_AND_METRICS_PLAN.md``).
  Поэтому тройка исключена из обхода источника
  (``bot4vps_sources.STATE_DB_EXCLUSIONS``), а в архив едет копия, снятая
  ``VACUUM INTO`` при активных писателях. Кладётся она по тому же пути
  дерева установки — иначе restore не знал бы, куда её возвращать;
* **периодические метрики в архив не входят** (решение §16.1), а аудит и
  operation-bound observations входят как доказательства; восстановление
  панели само по себе событие, историю которого хочется сохранить.
  Разделение делает ``state_db.export_audit_snapshot``;
* **БД вне дерева установки** (подменённый путь в тестах и dev-запусках) в
  архив не попадает: место файла в архиве определяется деревом, а не
  выдумывается.

Обратная сторона — restore. Архивный слепок едет одним файлом, без
спутников, и ложится поверх живой БД. Спутники прежней БД на месте
восстановления при этом остаются: чужой ``-wal`` рядом с восстановленным
файлом — минимум отказ открытия, максимум чужие страницы в кэше. Поэтому
restore получает не только слепок, но и список путей, которые перед
распаковкой надо убрать (``stale_state_db_sidecars``).
"""
from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path

from core import state_db

NAME = "STATE SNAPSHOT"

# Имя слепка во временном каталоге операции. Рядом с собираемым архивом и
# вне дерева установки: единственный источник архива, которого нет в
# источнике, не должен выглядеть его частью.
SNAPSHOT_FILENAME = "state-snapshot.db"


@dataclass(frozen=True)
class StateSnapshot:
    """Готовый слепок: где он в дереве установки и где лежит сам файл."""

    relative: str
    path: Path
    size: int


@dataclass(frozen=True)
class SnapshotResult:
    """Итог подготовки слепка: либо файл, либо причина, почему его нет.

    Отсутствие БД — не сбой и замечания не заслуживает (свежая панель до
    первых метрик и записей аудита). Замечание появляется тогда, когда
    слепок был нужен, но не получился: молчаливый архив без аудита читался
    бы как «аудита и не было».
    """

    snapshot: StateSnapshot | None = None
    warning: str | None = None


def state_db_relative(install_path: str | Path) -> str | None:
    """Путь БД внутри дерева установки или ``None``, если БД вне его."""
    install = Path(install_path).resolve()
    db = state_db.resolved_path()
    if db == install or install not in db.parents:
        return None
    return db.relative_to(install).as_posix()


def snapshot_state_db(install_path: str | Path, destination: str | Path) -> SnapshotResult:
    """Снять слепок БД для архива. Сбой не отменяет backup.

    Хранилище метрик и аудита не критично для панели (§4 ТЗ): недоступная
    или повреждённая БД — это замечание к операции, а не отказ бэкапа,
    который уносит конфиг, ключи и серверы.
    """
    relative = state_db_relative(install_path)
    if relative is None:
        return SnapshotResult()
    if not state_db.resolved_path().exists():
        return SnapshotResult()

    destination = Path(destination)
    if not state_db.export_audit_snapshot(destination):
        return SnapshotResult(
            warning=(
                "Слепок журнала аудита не попал в архив: хранилище метрик и "
                "аудита не удалось прочитать (подробности в журнале панели)"
            )
        )
    try:
        size = destination.stat().st_size
    except OSError:
        return SnapshotResult(
            warning="Слепок журнала аудита не попал в архив: файл слепка недоступен"
        )
    return SnapshotResult(
        snapshot=StateSnapshot(relative=relative, path=destination, size=size)
    )


def stale_state_db_sidecars(plan: dict) -> list[str]:
    """Спутники БД, которую перезапишет план восстановления.

    Пути считаются по плану, а не по текущей машине: restore знает только
    то, что собирается записать. Нет в плане файла БД (архив старше аудита
    или собран без него) — нет и удаления: эту БД архив не заменяет, и
    снимать с неё WAL означало бы потерять чужие незачекпойнченные записи.
    """
    targets = [
        str(entry.get("path"))
        for entry in plan.get("entries") or ()
        if posixpath.basename(str(entry.get("path"))) == state_db.DB_NAME
    ]
    return [
        str(sidecar)
        for target in targets
        for sidecar in state_db.sidecar_paths(target)
    ]
