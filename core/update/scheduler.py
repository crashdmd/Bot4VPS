"""Суточная задача проверки обновлений (PTB JobQueue).

Подключается через core.monitor.schedule_monitor_jobs — покрывает все
точки вызова (bot.py, ui/web/routers/monitor.py, admin_handlers.py).
"""
from __future__ import annotations

import asyncio

CHECK_INTERVAL_SECONDS = 86400  # раз в сутки
JOB_NAME = "update_check_job"


async def update_check_job(context) -> None:
    """Ежедневная проверка main; при выключенной настройке — молча пропустить."""
    from core.config import get_update_check_config
    from core.update import updater

    if not get_update_check_config().get("enabled"):
        return

    state = updater.read_state()
    if state["status"] in ("downloading", "installing", "rolling_back"):
        return  # не мешать идущей установке

    # Тихо: при отсутствии обновления пользователю ничего не показывается (ТЗ п.11)
    await updater.check_for_update(notify=True)


def schedule_update_jobs(job_queue) -> None:
    """(Пере)установить суточную задачу проверки обновлений."""
    if job_queue is None:
        return
    for job in job_queue.get_jobs_by_name(JOB_NAME):
        job.schedule_removal()

    from core.config import get_update_check_config
    if not get_update_check_config().get("enabled"):
        return

    job_queue.run_repeating(
        update_check_job,
        interval=CHECK_INTERVAL_SECONDS,
        first=30,
        name=JOB_NAME,
    )
