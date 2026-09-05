"""Ядерная JobQueue: жизненный цикл фоновых задач принадлежит ядру.

Раньше jobs (system_sync, availability, SSL, updates) жили в JobQueue
PTB-приложения: Telegram поднят — jobs работают, выключен — ядро
мониторинга молча умирает. TG — лишь один из каналов уведомлений,
он не должен управлять жизненным циклом общих функций.

Теперь очередь — собственность ядра: лёгкая asyncio-обёртка (PTB
JobQueue standalone не работает — каждый job требует application).
Поднимается любым входом Bot4VPS (uvicorn lifespan либо run_polling
чистого ТГ) и живёт, пока жив процесс. Jobs планирует
core.monitor.schedule_monitor_jobs — как и раньше, по config.json.

API:
- start_core_jobs() / stop_core_jobs() — lifecycle точки входа;
- reschedule_core_jobs() — пересоздать jobs после смены настроек
  (Настройки Web, ТГ-админка). Очередь должна быть уже запущена.
"""
from __future__ import annotations

import asyncio

# Параметр context у job-функций мониторинга не используется (унаследован
# от PTB JobQueue) — обёртка передаёт None.
_CORE_CONTEXT = None


class _CoreJob:
    """Один повторяющийся job: asyncio-таск с cancellation-токеном."""

    def __init__(self, name, task: asyncio.Task):
        self.name = name
        self.task = task
        self._removed = False

    def schedule_removal(self) -> None:
        self._removed = True
        self.task.cancel()

    @property
    def removed(self) -> bool:
        return self._removed


class CoreJobQueue:
    """Минимальный run_repeating + get_jobs_by_name поверх asyncio."""

    def __init__(self) -> None:
        self._jobs: dict[str, list[_CoreJob]] = {}

    def run_repeating(self, callback, interval, first=None, name=None) -> _CoreJob:
        loop = asyncio.get_running_loop()
        job = None

        async def _run():
            try:
                if first is not None:
                    await asyncio.sleep(first)
                while not (job and job.removed):
                    # Не держим event loop долгим await'ом callback'а:
                    # jobs мониторинга сами уходят в to_thread/executor.
                    try:
                        await callback(_CORE_CONTEXT)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        print(f"[JOBS] {name or callback.__name__}: {e}", flush=True)
                    await asyncio.sleep(interval)

            except asyncio.CancelledError:
                pass

        task = loop.create_task(_run())
        job = _CoreJob(name or callback.__name__, task)
        self._jobs.setdefault(job.name, []).append(job)
        return job

    def get_jobs_by_name(self, name: str) -> list[_CoreJob]:
        # мёртвые (снятые) jobs из реестра не отдаём
        return [j for j in self._jobs.get(name, []) if not j.removed]

    async def stop(self) -> None:
        for jobs in self._jobs.values():
            for job in jobs:
                job.schedule_removal()
        self._jobs.clear()


_core_queue: CoreJobQueue | None = None


def get_core_queue():
    """Текущая очередь ядра или None (не поднималась / остановлена)."""
    return _core_queue


async def start_core_jobs() -> CoreJobQueue:
    """Поднять очередь ядра и спланировать jobs мониторинга.

    Идемпотентен: повторный вызов без stop — no-op (guard).
    Вызывается из lifespan uvicorn ИЛИ из _post_init чистого ТГ —
    входы взаимно исключают друг друга.
    """
    global _core_queue
    if _core_queue is not None:
        return _core_queue

    queue = CoreJobQueue()
    _core_queue = queue

    from core.monitor import schedule_monitor_jobs
    schedule_monitor_jobs(queue)

    print("[JOBS] ядерная JobQueue запущена (system_sync + мониторинг)", flush=True)
    return queue


async def stop_core_jobs() -> None:
    """Остановить очередь ядра (shutdown процесса)."""
    global _core_queue
    if _core_queue is None:
        return
    queue, _core_queue = _core_queue, None
    try:
        await queue.stop()
    except Exception as e:
        print(f"[JOBS] остановка: {e}", flush=True)
    else:
        print("[JOBS] ядерная JobQueue остановлена", flush=True)


def reschedule_core_jobs() -> bool:
    """Пересоздать jobs мониторинга по текущему config.json.

    Вызывается после изменения настроек (Web/ТГ-админка).
    Возвращает True, если очередь была запущена и jobs пересозданы.
    """
    if _core_queue is None:
        print("[JOBS] reschedule: очередь ядра не запущена", flush=True)
        return False
    from core.monitor import schedule_monitor_jobs
    schedule_monitor_jobs(_core_queue)
    return True
