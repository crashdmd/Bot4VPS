"""Cancellable server-side preparation for restart, update and rollback."""
from __future__ import annotations

import asyncio
import math
import time
from typing import Awaitable, Callable

from core.task_manager import SHUTDOWN_GRACE_SECONDS, TaskManager


class PanelMaintenance:
    def __init__(self, manager: TaskManager):
        self.manager = manager
        self.operation: dict | None = None
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._worker: asyncio.Task | None = None

    def snapshot(self) -> dict | None:
        op = self.operation
        if not op:
            return None
        return {
            "id": op["id"], "kind": op["kind"], "target": op["target"],
            "phase": op["phase"], "forced": op["forced"],
            "remaining_seconds": max(0, math.ceil(op["deadline"] - time.monotonic()))
                if op["phase"] == "waiting" else 0,
            "error": op.get("error"), "result": op.get("result"),
        }

    async def begin(self, operation_id: str, kind: str, target: str | None,
                    action: Callable[[], Awaitable[dict]],
                    update_state: Callable[[], dict] | None = None) -> dict:
        async with self._lock:
            if self.operation and self.operation["id"] == operation_id:
                if (self.operation["kind"], self.operation["target"]) != (kind, target):
                    raise ValueError("Идентификатор операции уже используется")
                return self.snapshot()
            if self.operation and self.operation["phase"] in {"waiting", "stopping", "executing"}:
                raise RuntimeError("Операция с панелью уже выполняется")
            await self.manager.hold_for_maintenance(operation_id)
            self._wake = asyncio.Event()
            op = self.operation = {
                "id": operation_id, "kind": kind, "target": target,
                "phase": "waiting" if self.manager.shutdown_preview()["running"] else "stopping",
                "deadline": time.monotonic() + SHUTDOWN_GRACE_SECONDS, "forced": False,
            }
            self._worker = asyncio.create_task(self._drive(op, action, update_state))
            return self.snapshot()

    async def cancel(self, operation_id: str) -> dict:
        async with self._lock:
            op = self._require(operation_id)
            if op["phase"] == "cancelled":
                return self.snapshot()
            if op["phase"] != "waiting":
                raise RuntimeError("Остановка уже началась — отменить операцию нельзя")
            op["phase"] = "cancelled"
            self._wake.set()
            await self.manager.release_maintenance(operation_id)
            return self.snapshot()

    async def force(self, operation_id: str) -> dict:
        async with self._lock:
            op = self._require(operation_id)
            if op["phase"] == "waiting":
                op["forced"] = True
                op["phase"] = "stopping"
                self._wake.set()
            elif op["phase"] not in {"stopping", "executing"}:
                raise RuntimeError("Операция уже завершена")
            return self.snapshot()

    def _require(self, operation_id: str) -> dict:
        if not self.operation or self.operation["id"] != operation_id:
            raise ValueError("Подготовка операции не найдена")
        return self.operation

    async def _drive(self, op: dict, action: Callable[[], Awaitable[dict]],
                     update_state: Callable[[], dict] | None) -> None:
        try:
            while op["phase"] == "waiting":
                if (op["forced"] or not self.manager.shutdown_preview()["running"]
                        or time.monotonic() >= op["deadline"]):
                    async with self._lock:
                        if op["phase"] != "waiting":
                            return
                        op["forced"] = bool(self.manager.shutdown_preview()["running"])
                        op["phase"] = "stopping"
                    break
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=min(.2, max(0, op["deadline"] - time.monotonic())))
                except asyncio.TimeoutError:
                    pass
            if op["phase"] != "stopping":
                return
            # Ожидающие отменяются только после необратимого перехода:
            # отмена подготовки до этого оставляет очередь и активные задачи.
            await self.manager.shutdown(timeout=0)
            op["phase"] = "executing"
            op["result"] = await action()
            if op["result"].get("ok") is False:
                raise RuntimeError(op["result"].get("error") or "Операция не запущена")
            # Если runner не смог установить версию и процесс остался жив,
            # приём задач должен восстановиться без участия браузера.
            if update_state:
                while op is self.operation and op["phase"] == "executing":
                    state = update_state()
                    if state["status"] in {"failed", "idle"}:
                        if state["status"] == "failed":
                            raise RuntimeError(state.get("last_error") or "Установка версии не удалась")
                        op["phase"] = "done"
                        await self.manager.release_maintenance(op["id"])
                        return
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            # Реальная остановка процесса не возобновляет приём задач.
            raise
        except Exception as error:
            op["phase"] = "failed"
            op["error"] = str(error)
            await self.manager.release_maintenance(op["id"])
