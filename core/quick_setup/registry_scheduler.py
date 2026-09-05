"""Часовой фоновый проход реестра ключей по всем серверам.

Реестр (keys/registry.json) — источник быстрых сверк «кем занят ключ»;
реальные authorized_keys на серверах — истина. При операциях с ключами
реестр синхронизируется на активном сервере (см. ssh_access), а этот
воркер раз в час проходит ВСЕ серверы и освежает их секции, чтобы
реестр не протухал (ключи, добавленные вручную мимо панели, тоже
попадают в него с правильным владельцем).

Никаких кнопок и настроек: воркер всегда работает вместе с Web UI
(стартует в lifespan app.py). Один сервер недоступен или без sudo —
его секция просто остаётся как есть, проход продолжается.
"""
from __future__ import annotations

import asyncio

from core.storage import load_servers

from .ssh_access import sync_server_key_registry

# Интервал фонового прохода: раз в час.
_INTERVAL_SECONDS = 3600.0


class KeyRegistryScheduler:
    def __init__(self, *, interval_seconds: float = _INTERVAL_SECONDS):
        self.interval_seconds = max(60.0, float(interval_seconds))
        self._stop = asyncio.Event()
        self._loop_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._stop.clear()
        self._loop_task = asyncio.create_task(
            self._run_loop(), name="key-registry-scheduler"
        )

    async def stop(self) -> None:
        self._stop.set()
        task = self._loop_task
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=30)
            except (asyncio.TimeoutError, Exception):
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._loop_task = None

    async def _run_loop(self) -> None:
        # Первый проход сразу при старте: после рестарта сервиса реестр
        # освежается, не дожидаясь часа.
        while not self._stop.is_set():
            try:
                await self.run_pass()
            except Exception as exc:
                print(
                    f"[KEY REGISTRY SCHEDULER] проход завершился ошибкой: "
                    f"{type(exc).__name__}",
                    flush=True,
                )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                pass

    async def run_pass(self) -> int:
        """Один проход по всем серверам; возвращает число обновлённых секций."""
        updated = 0
        total = 0
        for server in load_servers() or []:
            if self._stop.is_set():
                break
            if not isinstance(server, dict) or not server.get("id"):
                continue
            total += 1
            try:
                ok = await asyncio.to_thread(sync_server_key_registry, server)
            except Exception:
                ok = False
            if ok:
                updated += 1
        print(
            f"[KEY REGISTRY SCHEDULER] проход завершён: "
            f"{updated}/{total} серверов синхронизировано",
            flush=True,
        )
        return updated


_scheduler: KeyRegistryScheduler | None = None


async def start_key_registry_scheduler() -> KeyRegistryScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = KeyRegistryScheduler()
    await _scheduler.start()
    return _scheduler


async def stop_key_registry_scheduler() -> None:
    global _scheduler
    scheduler = _scheduler
    _scheduler = None
    if scheduler is not None:
        await scheduler.stop()
