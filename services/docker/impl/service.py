# -*- coding: utf-8 -*-
"""Docker Engine - интегрированный сервис Bot4VPS.

Phase 1: установка/удаление Docker Engine + статус демона (версия/active).
Phase 2: контейнеры — список со статистикой (get_state) + run/start/stop/
restart/rm + логи. Managed-флаг контейнеров — через лейбл bot4vps.managed=true.
Phase 4: образы — список + pull/rm/prune.
Phase 5: Compose-проекты. Объект — ПРОЕКТ (директория с compose + .env +
доп. файлами): локальная библиотека (compose_store) ↔ сервер (compose).
Единые действия compose_up/down/restart с параметром source=library|server;
внешние проекты управляются по их реальному working_dir.
Вся логика — здесь (core); Web (docker.js) и будущий TG-хендлер — тонкие оболочки
над core.integrator. Контракт идентичен WireGuard.

Кэш (data/services/docker/<server>.json):
    {installed, version, active, containers:[...], images:[...], stats:{...},
     synced_at, service_id}
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.integrator import (
    Service as BaseService,
    ServiceAction,
    read_cache,
    sync_progress,
)
from core.ssh import create_ssh_client, exec_sudo
from core.storage import find_server
from core.task_manager import TaskResult

from . import compose, compose_store, containers, images, lifecycle, stats


class Service(BaseService):
    """Docker Engine: установка и статус (Phase 1)."""

    def params_schema(self) -> list:
        # Phase 1 — без параметров мастера установки.
        return []

    async def do_install(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        async with sync_progress(progress_cb) as emit:
            runner = await asyncio.to_thread(lifecycle.install, server, params, emit)
        # post-action sync (do_sync → кэш) делает фреймворк (_svc_executor).
        return TaskResult(
            success=True,
            output="Docker установлен и запущен. Шаги: " + ", ".join(runner.completed),
        )

    async def do_remove(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        async with sync_progress(progress_cb) as emit:
            runner = await asyncio.to_thread(lifecycle.remove, server, emit)
        return TaskResult(
            success=True,
            output="Docker удалён (пакеты). /var/lib/docker сохранён. Шаги: "
            + ", ".join(runner.completed),
        )

    def _read_live(self, server_id: str) -> Dict[str, Any]:
        """Единое read-only живое чтение: версия Docker + статус демона + список
        контейнеров со статистикой (Phase 2). Ничего не пишет в кэш — это делает
        фреймворк sync() после do_sync. Используется и do_sync (→ кэш), и
        get_state (→ живой ответ без кэша)."""
        server = find_server(server_id)
        if not server:
            return {"installed": False, "error": "Сервер не найден"}
        ssh = create_ssh_client(server)
        try:
            _, ver, _ = exec_sudo(
                ssh, server,
                "command -v docker >/dev/null 2>&1 && docker --version || true",
            )
            installed = bool(ver.strip())
            active = "inactive"
            containers_list: List[Dict[str, Any]] = []
            if installed:
                _, active_out, _ = exec_sudo(
                    ssh, server,
                    "systemctl is-active docker 2>/dev/null || echo inactive",
                )
                active = active_out.strip() or "inactive"
                # Контейнеры читаем только если демон отвечает (иначе docker ps
                # висит/падает). Статистику — по живым (--no-stream single shot).
                if active == "active":
                    _, ps_txt, _ = exec_sudo(
                        ssh, server,
                        "docker ps -a --no-trunc --format '{{json .}}' 2>/dev/null || true",
                    )
                    _, stats_txt, _ = exec_sudo(
                        ssh, server,
                        "docker stats --no-stream --format '{{json .}}' 2>/dev/null || true",
                    )
                    # §3: uptime контейнера нужен для UI. StartedAt доступен только
                    # в docker inspect, не в ps; чтобы не делать inspect на каждый
                    # контейнер, читаем все ID сразу (JSON-массив).
                    _, inspect_txt, _ = exec_sudo(
                        ssh, server,
                        "docker inspect $(docker ps -q 2>/dev/null) 2>/dev/null || true",
                    )
                    ps_list = stats.parse_ps(ps_txt)
                    stats_map = stats.parse_stats(stats_txt)
                    inspect_map = stats.parse_inspect(inspect_txt)
                    containers_list = stats.build_container_stats(
                        ps_list, stats_map, inspect_map
                    )
            # Добавить service_url для контейнеров с опубликованными портами
            host = server.get("host", "")
            for c in containers_list:
                port = c.get("published_port")
                if port and c.get("state") == "running":
                    c["service_url"] = f"http://{host}:{port}"
                else:
                    c["service_url"] = ""
            # Phase 4: добавить список образов (только если демон активен)
            images_list: List[Dict[str, Any]] = []
            if installed and active == "active":
                images_list = images.list_images(server)
            running = sum(1 for c in containers_list if c.get("state") == "running")
            # Задачи здесь НЕ отдаём: их место — меню «Очереди» (/api/queues).
            # core не должен зависеть от ui.web.
            return {
                "installed": installed,
                "version": ver.strip() or None,
                "active": active,
                "containers": containers_list,
                "images": images_list,
                "stats": {
                    "total": len(containers_list),
                    "running": running,
                    "managed": sum(1 for c in containers_list if c.get("managed")),
                    "images": len(images_list),
                },
            }
        finally:
            ssh.close()

    async def do_sync(self, server_id: str) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self._read_live, server_id)
        except Exception as e:
            return {"installed": False, "error": str(e)}

    def get_state(self, server_id: str) -> Dict[str, Any]:
        """Живое чтение состояния БЕЗ записи кэша — для открытия/рефреша экрана.
        Синхронный: integrator.call заворачивает в asyncio.to_thread."""
        return self._read_live(server_id)

    def get_status(self, server_id: str) -> Dict[str, Any]:
        return read_cache(self.manifest.id, server_id)

    def get_profiles(self, server_id: str) -> List[Dict[str, Any]]:
        # Профили сервиса = контейнеры (единый accessor контракта; UI-агностично).
        return read_cache(self.manifest.id, server_id).get("containers", [])

    def get_images(self, server_id: str) -> List[Dict[str, Any]]:
        """Живой список образов (read-only, без записи кэша).
        Синхронный: integrator.call заворачивает в asyncio.to_thread."""
        server = find_server(server_id)
        if not server:
            return []
        return images.list_images(server)

    # --------------------------------------------------------
    # Действия над контейнерами (Phase 2). Любой async do_* автоматически
    # становится действием очереди (integrator.enqueue("docker", srv, action, params)).
    # --------------------------------------------------------

    async def do_container_run(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        async with sync_progress(progress_cb) as emit:
            info = await asyncio.to_thread(containers.run_container, server, params, emit)
        return TaskResult(
            success=True,
            output=f"Контейнер «{info['name']}» запущен из образа {info['image']}.",
        )

    async def do_container_start(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        return await self._container_op(
            server_id, params, progress_cb, containers.start_container, "запущен"
        )

    async def do_container_stop(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        return await self._container_op(
            server_id, params, progress_cb, containers.stop_container, "остановлен"
        )

    async def do_container_restart(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        return await self._container_op(
            server_id, params, progress_cb, containers.restart_container, "перезапущен"
        )

    async def do_container_rm(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        return await self._container_op(
            server_id, params, progress_cb, containers.remove_container, "удалён"
        )

    async def _container_op(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]], fn, verb: str,
    ) -> TaskResult:
        """Общая обёртка для start/stop/restart/rm: name из params → SSH-операция."""
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        name = str(params.get("name") or "")
        async with sync_progress(progress_cb) as emit:
            await asyncio.to_thread(fn, server, name, emit)
        return TaskResult(success=True, output=f"Контейнер «{name}» {verb}.")

    def fetch_logs(self, server_id: str, name: str, tail: int = 200) -> str:
        """Логи контейнера для UI (read-only). integrator.call заворачивает в
        asyncio.to_thread. Роутер отдаёт как текст."""
        server = find_server(server_id)
        if not server:
            raise RuntimeError("Сервер не найден")
        return containers.fetch_logs(server, name, tail)

    # --------------------------------------------------------
    # Compose-стеки (Phase 5).
    #
    # Два уровня хранения: локальная библиотека (compose_store) —
    # data/services/docker/compose/<stack>/docker-compose.yml, и деплой на
    # сервер (compose) — /opt/bot4vps/<stack>/docker-compose.yml.
    # Стек глобальный: одна запись библиотеки разворачивается на любой сервер.
    # --------------------------------------------------------

    def get_stacks(self, server_id: str) -> Dict[str, Any]:
        """Библиотека проектов + фактическое состояние сервера.

        Возвращает {library, server, reconciled, server_accessible}. Библиотека
        читается всегда (локальный ФС); серверное состояние — best-effort: при
        недоступности SSH проекты библиотеки всё равно видны и редактируемы.

        reconciled делит проекты на три группы:
          both         — есть и в библиотеке, и развёрнут Bot4VPS на этом сервере
                         (+ project_match: совпадают ли файлы, §23)
          library_only — только в библиотеке (можно развернуть)
          server_only  — найден на сервере, в библиотеке нет (внешний, §15)
        """
        library = compose_store.list_stacks()
        server: List[Dict[str, Any]] = []
        server_accessible = False
        srv_obj = find_server(server_id)
        if srv_obj:
            try:
                server = compose.list_server_stacks(srv_obj)
                server_accessible = True   # только ПОСЛЕ успешного чтения
            except Exception as e:
                print(f"[DOCKER] compose list_server_stacks({server_id}): {e}", flush=True)

        # Сверка каждой серверной записи с библиотекой — по ней UI решает,
        # предлагать ли импорт и предупреждать ли о перезаписи:
        #   in_library=False → импорт доступен (проекта в библиотеке нет)
        #   lib_match=True   → «совпадает», импорт незачем
        #   lib_match=False  → «отличается», импорт с подтверждением
        #   lib_match=None   → сравнить не удалось (файлы не прочитаны)
        lib_fp = {s["name"]: s.get("fingerprint") for s in library}
        for rec in server:
            name = rec.get("name")
            in_lib = name in lib_fp
            rec["in_library"] = in_lib
            srv_fp, l_fp = rec.get("fingerprint"), lib_fp.get(name)
            rec["lib_match"] = (srv_fp == l_fp) if (in_lib and srv_fp and l_fp) else None

        reconciled = compose_store.reconcile_stacks(library, server)
        return {
            "library": library,
            "server": server,
            "reconciled": reconciled,
            "server_accessible": server_accessible,
        }

    # --- файлы проекта в библиотеке (проект = директория) ---

    def fetch_stack_file(self, server_id: str, name: str) -> str:
        """Основной Compose-файл проекта из библиотеки (для редактора)."""
        return compose_store.read_stack(name)

    def save_stack_file(self, server_id: str, name: str, content: str) -> Dict[str, Any]:
        """Создать/обновить основной Compose-файл, не теряя остальные файлы.

        Валидация до записи; на сервер ничего не отправляется — деплой
        произойдёт при up/restart.
        """
        return compose_store.write_stack(name, content)

    def list_stack_files(self, server_id: str, name: str) -> List[Dict[str, Any]]:
        """Все файлы проекта: [{path, size, is_compose}]."""
        return compose_store.list_project_files(name)

    def fetch_stack_project_file(self, server_id: str, name: str, path: str) -> str:
        """Содержимое произвольного текстового файла проекта (.env и т.п.)."""
        return compose_store.read_project_file(name, path)

    def save_stack_project_file(
        self, server_id: str, name: str, path: str, content: str
    ) -> Dict[str, Any]:
        """Записать произвольный файл проекта, не трогая остальные."""
        return compose_store.save_project_file(name, path, content.encode("utf-8"))

    def delete_stack_project_file(self, server_id: str, name: str, path: str) -> str:
        """Удалить файл проекта (основной Compose-файл удалить нельзя)."""
        return compose_store.delete_project_file(name, path)

    def import_stack_zip(self, server_id: str, name: str, data: bytes) -> Dict[str, Any]:
        """Импортировать ZIP-архив как проект библиотеки (§5)."""
        return compose_store.import_zip(name, data)

    def delete_stack(self, server_id: str, name: str) -> str:
        """Удалить проект из библиотеки (на сервере ничего не трогаем)."""
        return compose_store.delete_stack(name)

    def fetch_stack_logs(
        self, server_id: str, name: str, tail: int = 200,
        source: str = compose.SOURCE_LIBRARY, key: Optional[str] = None,
    ) -> str:
        """Логи проекта с сервера (read-only). source: library | server."""
        server = find_server(server_id)
        if not server:
            raise RuntimeError("Сервер не найден")
        return compose.fetch_logs(server, name, tail, source=source, key=key)

    # --------------------------------------------------------
    # Единые действия Compose (§19).
    #
    # Никаких *_remote в публичном контракте: источник передаётся параметром
    # source = "library" | "server" (+ key для однозначного выбора
    # развёртывания, если на сервере несколько проектов с одним именем).
    # --------------------------------------------------------

    async def _compose_op(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]], fn, verb: str,
    ) -> TaskResult:
        """Общая обёртка up/down/restart: stack + source + key → SSH-операция."""
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        stack = str(params.get("stack") or params.get("name") or "")
        source = str(params.get("source") or compose.SOURCE_LIBRARY)
        if source not in (compose.SOURCE_LIBRARY, compose.SOURCE_SERVER):
            return TaskResult(
                success=False,
                error=f"Неизвестный источник проекта: {source!r}",
            )
        key = params.get("key") or None
        async with sync_progress(progress_cb) as emit:
            dep = await asyncio.to_thread(
                fn, server, stack, emit, source, key
            )
        where = dep.working_dir if hasattr(dep, "working_dir") else ""
        suffix = f" ({where})" if where else ""
        name = dep.project if hasattr(dep, "project") else stack
        return TaskResult(success=True, output=f"Проект «{name}» {verb}{suffix}.")

    async def do_compose_up(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        """Запустить проект. source=library — с деплоем, source=server — на месте."""
        return await self._compose_op(
            server_id, params, progress_cb, compose.up, "запущен"
        )

    async def do_compose_down(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        """Остановить проект. Тома сохраняются (без -v)."""
        return await self._compose_op(
            server_id, params, progress_cb, compose.down, "остановлен, тома сохранены"
        )

    async def do_compose_restart(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        """Перезапустить/применить конфигурацию (семантика up -d, §20)."""
        return await self._compose_op(
            server_id, params, progress_cb, compose.restart, "перезапущен"
        )

    async def do_compose_import(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        """Импортировать проект с сервера в библиотеку ЦЕЛИКОМ (§17)."""
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        stack = str(params.get("stack") or "").strip()
        overwrite = bool(params.get("overwrite", False))
        key = params.get("key") or None
        target = params.get("target_name") or None
        async with sync_progress(progress_cb) as emit:
            name = await asyncio.to_thread(
                compose.import_from_server, server, stack, overwrite, emit, key, target
            )
        return TaskResult(
            success=True,
            output=f"Проект «{name}» импортирован в библиотеку Bot4VPS",
        )

    async def do_compose_delete_remote(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        """Удалить проект с сервера: down (без -v) → и только затем файлы (§18).

        Библиотеку не трогает.
        """
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        stack = str(params.get("stack") or "").strip()
        source = str(params.get("source") or compose.SOURCE_LIBRARY)
        key = params.get("key") or None
        async with sync_progress(progress_cb) as emit:
            name = await asyncio.to_thread(
                compose.delete_from_server, server, stack, emit, source, key
            )
        return TaskResult(
            success=True,
            output=f"Проект «{name}» удалён с сервера (библиотека не изменена)",
        )

    # --------------------------------------------------------
    # Действия над образами (Phase 4). Любой async do_* автоматически
    # становится действием очереди.
    # --------------------------------------------------------

    async def do_image_pull(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        image = str(params.get("image") or "").strip()
        async with sync_progress(progress_cb) as emit:
            result_image = await asyncio.to_thread(images.pull_image, server, image, emit)
        return TaskResult(
            success=True,
            output=f"Образ «{result_image}» загружен.",
        )

    async def do_image_rm(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        image = str(params.get("image") or "").strip()
        async with sync_progress(progress_cb) as emit:
            result_image = await asyncio.to_thread(images.remove_image, server, image, emit)
        return TaskResult(
            success=True,
            output=f"Образ «{result_image}» удалён.",
        )

    async def do_image_prune(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        async with sync_progress(progress_cb) as emit:
            summary = await asyncio.to_thread(images.prune_images, server, emit)
        return TaskResult(
            success=True,
            output=f"Очистка завершена. {summary}",
        )

    def get_actions(self, server_id: str) -> List[ServiceAction]:
        status = self.get_status(server_id) or {}
        installed = bool(status.get("installed"))
        items: List[ServiceAction] = []
        if not installed:
            items.append(ServiceAction(
                "install", "🟢 Установить", style="primary", task_title="установка",
            ))
            items.append(ServiceAction(
                "sync", "🔵 Синхронизировать", task_title="синхронизация",
            ))
            return items
        items.append(ServiceAction(
            "sync", "🔵 Синхронизировать", task_title="синхронизация",
        ))
        items.append(ServiceAction(
            "container_run", "➕ Запустить контейнер", group="containers",
            task_title="запуск контейнера",
        ))
        items.append(ServiceAction(
            "image_pull", "⬇️ Загрузить образ", group="images",
            task_title="загрузка образа",
        ))
        # Compose: единые действия, источник — параметр source (§19).
        items.append(ServiceAction(
            "compose_up", "🧩 Запустить стек", group="compose",
            task_title="запуск стека",
        ))
        items.append(ServiceAction(
            "compose_down", "⏹ Остановить стек", group="compose",
            task_title="остановка стека",
        ))
        items.append(ServiceAction(
            "compose_restart", "🔄 Перезапустить / применить", group="compose",
            task_title="перезапуск стека",
        ))
        items.append(ServiceAction(
            "compose_import", "⬇️ Импорт стека с сервера", group="compose",
            task_title="импорт стека",
        ))
        items.append(ServiceAction(
            "compose_delete_remote", "🗑 Удалить стек с сервера", group="compose",
            task_title="удаление стека с сервера",
        ))
        items.append(ServiceAction(
            "confirm_remove", "🗑 Удалить сервис", style="danger", task_title="удаление",
        ))
        return items
