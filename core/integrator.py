"""
Integrator Core — управление жизненным циклом сервисов (Bot4VPS v2.2+).

Обобщённое ядро интеграции. Ничего не знает про конкретные сервисы
(WireGuard, Docker, 3x-ui …) — только предоставляет общую инфраструктуру:

* реестр сервисов (обнаружение по services/<id>/service.json);
* базовый класс Service и доменный Parameter — контракт, не зависящий от UI;
* запуск действий через Task Manager (очередь, live-output, отмена, статусы);
* утилиты для сервисов: exec_sudo (sudo-aware запуск на сервере),
  sync_progress (прокси async progress_cb → sync-emit для asyncio.to_thread),
  StepError (шаг с контекстом);
* JSON-кэш состояния сервисов (per-service per-server, атомарная запись);
* события сервиса.

Архитектура:
    ui (telegram | web)
          ↓
    core/integrator      ← это ядро интеграции
          ↓
    core/task_manager, core/ssh, core/event_service, core/storage
          ↑
    services/<id>/<id>.py   (импортируется ЛЕНИВО, только при действии)

Зависимости однонаправленные: services/* → core, никогда обратно.
Конкретный сервис импортируется лениво — в реестре лежат только манифесты
(JSON), модуль грузится по первому обращению.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import os
import queue as _queue
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.task_manager import (
    Task,
    TaskResult,
    register_executor,
    task_manager,
)
from core.ssh import exec_sudo

# --------------------------------------------------
# Пути
# --------------------------------------------------

# Исходники сервисов (то, что в git: манифест + модуль + шаблоны).
SERVICES_DIR = Path("services")
# Runtime-данные сервисов (НЕ исходники; генерируется, как monitor.json/servers.json).
# data/services/<service_id>/<server_id>.json
# data/ — универсальный корень: здесь кэш состояния сервисов, позже — downloads/templates.
CACHE_DIR = Path("data/services")

# Блокировка для атомарного RMW над кэшем (TG-процесс + веб-процесс + мониторинг).
_CACHE_LOCK = threading.RLock()


# --------------------------------------------------
# Манифест сервиса
# --------------------------------------------------

@dataclass
class ServiceManifest:
    """Декларативное описание сервиса из service.json.

    Только данные — ровно столько, чтобы реестр и UI перечислили и нарисовали
    сервис БЕЗ импорта модуля. Вся логика — в services/<id>/<id>.py.
    Неизвестные поля попадают в `extra` (манифест толерантен к расширениям).
    """

    id: str
    name: str
    install: str = "apt"                       # "apt" | "package" | "custom"
    packages: List[str] = field(default_factory=list)
    supports_updates: bool = False             # нужен ли Version Checker
    icon: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServiceManifest":
        known = {"id", "name", "install", "packages", "supports_updates", "icon"}
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            install=data.get("install", "apt"),
            packages=list(data.get("packages", [])),
            supports_updates=bool(data.get("supports_updates", False)),
            icon=data.get("icon", ""),
            extra={k: v for k, v in data.items() if k not in known},
        )

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "name": self.name,
            "install": self.install,
            "packages": self.packages,
            "supports_updates": self.supports_updates,
            "icon": self.icon,
        }
        d.update(self.extra)
        return d


# --------------------------------------------------
# Доменный параметр (БЕЗ привязки к UI)
# --------------------------------------------------

@dataclass
class Parameter:
    """Контракт параметра мастера установки.

    Сервис объявляет ЧТО нужно (имя, тип, ограничения) — без текстов и виджетов.
    Как спросить (кнопка Да/Нет, текстовое поле, веб-форма) и какой показать
    label — решает UI-слой (telegram/web). Так web переиспользует сервисы as-is.

    type: text | number | bool | select (для select — choices).
    min/max — для number; pattern — regex для text.
    description — доменный смысл параметра (НЕ UI-label); фолбэк для UI.
    """

    name: str
    type: str = "text"                         # text | number | bool | select
    default: Any = None
    required: bool = True
    choices: List[str] = field(default_factory=list)
    min: Optional[float] = None
    max: Optional[float] = None
    pattern: Optional[str] = None
    description: Optional[str] = None


# --------------------------------------------------
# Пункт меню сервиса (доменный, без Telegram/HTML)
# --------------------------------------------------

@dataclass
class ServiceAction:
    """Действие сервиса (доменное, без привязки к UI).

    id         — токен op (install, migrate, prune, …).
    label      — текст для UI (кнопка).
    style      — подсказка UI: default | primary | danger.
    group      — необязательная секция.
    task_title — короткое имя для Task Manager («установка», «миграция»).
                 Если пусто — используется id.
    """

    id: str
    label: str
    style: str = "default"
    group: Optional[str] = None
    task_title: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "style": self.style,
            "group": self.group,
            "task_title": self.task_title,
        }


# --------------------------------------------------
# Базовый класс сервиса
# --------------------------------------------------

# async progress_cb(line): стримит строку live-вывода в task_manager.
ProgressCb = Callable[[str], Awaitable[None]]


class Service:
    """Контракт сервиса. Конкретный сервис наследует его и реализует do_*.

    do_install / do_remove вызываются ИСПОЛНИТЕЛЕМ task_manager (kind="svc"):
    получают progress_cb для live-вывода и должны вернуть TaskResult.
    Очередь, отмена, retry, история, события — берёт на себя task_manager,
    поэтому сервис про них не думает.

    do_sync — read-only запрос состояния; вызывается напрямую (не через очередь),
    возвращает dict для кэша. Используется и как авто-обновление кэша после
    любого действия.
    """

    def __init__(self, manifest: ServiceManifest):
        self.manifest = manifest

    def params_schema(self) -> List[Parameter]:
        """Схема параметров мастера установки (доменные Parameter, без UI)."""
        return []

    async def do_install(
        self, server_id: str, params: Dict[str, Any], progress_cb: ProgressCb
    ) -> TaskResult:
        raise NotImplementedError

    async def do_remove(
        self, server_id: str, params: Dict[str, Any], progress_cb: ProgressCb
    ) -> TaskResult:
        raise NotImplementedError

    async def do_sync(self, server_id: str) -> Dict[str, Any]:
        """Read-only запрос состояния сервера → данные для кэша."""
        return {}

    def get_state(self, server_id: str) -> Dict[str, Any]:
        """Живое чтение состояния БЕЗ записи кэша — для экранов UI, которым нужна
        актуальная статистика при открытии/рефреше (а не «тяжёлая» синхронизация).
        По умолчанию отдаёт кэш (``get_status``) — безопасно для сервисов без
        собственного live-reader'а; сервис переопределяет для свежего live-чтения."""
        return self.get_status(server_id)

    # --------------------------------------------------------
    # UI-доступ (cache-backed accessors). Handler говорит только
    # с сервисом через эти методы (integrator.call), никогда не лезёт
    # в кэш сам. Ключи кэша — деталь реализации сервиса.
    # --------------------------------------------------------
    def get_status(self, server_id: str) -> Dict[str, Any]:
        """UI-статус сервиса: installed/version/active/synced_at (+ что сервис
        сам решит отдать). По умолчанию {}. Сервис-провайдер переопределяет
        и возвращает срез своего кэша. Пополняется новыми полями по мере роста."""
        return {}

    def get_profiles(self, server_id: str) -> List[Dict[str, Any]]:
        """Коллекция профилей/клиентов для UI: [{name, enabled}, ...].
        По умолчанию []. Будущие коллекции (groups/owners/…) добавляются
        аналогичными accessor'ами — handler дальше не трогает кэш."""
        return []

    def get_actions(self, server_id: str) -> List["ServiceAction"]:
        """Доступные действия сервиса для UI.

        Integrator и handler не знают, какие действия есть у WireGuard/Docker —
        сервис сам формирует список. Базовая реализация: install / sync / remove
        по факту installed из get_status().
        """
        status = self.get_status(server_id) or {}
        installed = bool(status.get("installed"))
        items: List[ServiceAction] = []
        if not installed:
            items.append(ServiceAction("install", "🟢 Установить", style="primary", task_title="установка"))
            items.append(ServiceAction("sync", "🔵 Синхронизировать", task_title="синхронизация"))
        else:
            items.append(ServiceAction("sync", "🔵 Синхронизировать", task_title="синхронизация"))
            items.append(ServiceAction("confirm_remove", "🗑 Удалить сервис", style="danger", task_title="удаление"))
        return items

    def resolve_task_title(self, action: str) -> str:
        """Имя действия для Task Manager — только из ServiceAction.task_title.

        Сопоставление: action, confirm_{action}, а также add↔add_profile и т.п.
        Отдельных словарей названий в сервисах быть не должно.
        """
        aliases = {
            "add_profile": "add",
            "remove_profile": "delprofile",
            "toggle_profile": "toggle",
        }
        candidates = {action, f"confirm_{action}"}
        if action in aliases:
            candidates.add(aliases[action])
        try:
            for item in self.get_actions(""):
                aid = item.id if hasattr(item, "id") else (item.get("id") if isinstance(item, dict) else None)
                if aid not in candidates:
                    continue
                title = (
                    item.task_title if hasattr(item, "task_title")
                    else (item.get("task_title") if isinstance(item, dict) else None)
                )
                if title:
                    return title
        except Exception:
            pass
        return action



# --------------------------------------------------
# Реестр сервисов
# --------------------------------------------------

_MANIFESTS: Dict[str, ServiceManifest] = {}


def discover_services() -> List[ServiceManifest]:
    """Сканировать services/*/service.json и заполнить реестр манифестов.

    Модули НЕ импортирует — только читает JSON (дёшево, для UI/реестра).
    Идемпотентен: безопасно дёргать повторно (например, после добавления сервиса).
    """
    _MANIFESTS.clear()
    if not SERVICES_DIR.is_dir():
        return []
    for service_json in sorted(SERVICES_DIR.glob("*/service.json")):
        try:
            data = json.loads(service_json.read_text(encoding="utf-8"))
            manifest = ServiceManifest.from_dict(data)
            _MANIFESTS[manifest.id] = manifest
        except Exception as e:
            print(f"[INTEGRATOR] пропуск манифеста {service_json}: {e}", flush=True)
    return list_services()


def list_services() -> List[ServiceManifest]:
    return list(_MANIFESTS.values())


def get_manifest(service_id: str) -> Optional[ServiceManifest]:
    return _MANIFESTS.get(service_id)


def _get_service(service_id: str) -> Service:
    """Лениво импортировать модуль сервиса и создать экземпляр.

    Контракт модуля: services/<id>/<id>.py определяет `class Service(Service)`.
    """
    manifest = get_manifest(service_id)
    if not manifest:
        raise ValueError(f"Неизвестный сервис: {service_id}")
    module = importlib.import_module(f"services.{service_id}.{service_id}")
    svc_cls = getattr(module, "Service", None)
    if svc_cls is None or not isinstance(svc_cls, type) or not issubclass(svc_cls, Service):
        raise RuntimeError(
            f"services.{service_id}.{service_id} должен определять "
            f"class Service(core.integrator.Service)"
        )
    return svc_cls(manifest)


# --------------------------------------------------
# Кэш состояния (per-service per-server)
# --------------------------------------------------

def _cache_path(service_id: str, server_id: str) -> Path:
    return CACHE_DIR / service_id / f"{server_id}.json"


def read_cache(service_id: str, server_id: str) -> Dict[str, Any]:
    """Быстрое чтение кэша для UI. Не источник истины — возможна стертость."""
    path = _cache_path(service_id, server_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_cache(service_id: str, server_id: str, data: Dict[str, Any]) -> None:
    """Атомарная перезапись кэша (temp + fsync + os.replace)."""
    path = _cache_path(service_id, server_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with _CACHE_LOCK:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)


def update_cache(service_id: str, server_id: str, **fields: Any) -> Dict[str, Any]:
    """Атомарный RMW: прочитать → слить поля → записать. Всегда ставит synced_at."""
    with _CACHE_LOCK:
        data = read_cache(service_id, server_id)
        data.update(fields)
        data["synced_at"] = datetime.now().isoformat(timespec="seconds")
        write_cache(service_id, server_id, data)
        return data


# --------------------------------------------------
# Утилиты для сервисов
# --------------------------------------------------

class StepError(Exception):
    """Ошибка конкретного шага. Несёт стабильный id шага + контекст для TaskResult.

    `step`  — стабильный id (snake_case): попадает в логи/историю/диагностику/
              повторный запуск. Не зависит от формулировки.
    `title` — человекочитаемый заголовок (для live-вывода/сообщений).
    `detail`— вывод команды (stdout/stderr) для диагностики.
    """

    def __init__(self, step: str, exit_code: int, detail: str = "", title: Optional[str] = None):
        self.step = step
        self.title = title or step
        self.exit_code = exit_code
        self.detail = detail
        super().__init__(f"{self.title} завершилась с ошибкой (код {exit_code})")


class StepRunner:
    """Контекст выполнения именованных шагов на сервере.

    Инкапсулирует КАК выполнить шаг (SSH + sudo + стриминг + проверка exit +
    запись пройденных). Это инфраструктура ядра — «Integrator знает КАК».
    Сервис знает лишь КАКОЙ шаг запустить (стабильное имя + команда): «Service
    знает ЧТО».

        runner = StepRunner(ssh, server, emit)
        runner.run("apt_update", "DEBIAN_FRONTEND=noninteractive apt-get update",
                   title="apt update")

    `name` попадает в StepError при сбое и в `completed` при успехе — далее в
    логи, историю задачи, повторный запуск и диагностику.
    """

    def __init__(self, ssh, server, emit):
        self.ssh = ssh
        self.server = server
        self.emit = emit
        self.completed: List[str] = []
        self.failed: Optional[str] = None

    def run(self, name: str, command: str, title: Optional[str] = None) -> str:
        """Именованный шаг: стримит заголовок + вывод, падает в StepError при exit!=0."""
        title = title or name
        self.emit(f"• {title}")
        exit_code, out, err = exec_sudo(
            self.ssh, self.server, command, emit=lambda line: self.emit("   " + line)
        )
        if exit_code != 0:
            self.failed = name
            raise StepError(name, exit_code, title=title, detail=(err.strip() or out.strip())[:500])
        self.completed.append(name)
        return out

    def probe(self, command: str) -> str:
        """Read-only запрос без имени и без проверки exit — для детектов/проверок."""
        _, out, _ = exec_sudo(self.ssh, self.server, command)
        return out.strip()


@contextlib.asynccontextmanager
async def sync_progress(progress_cb: Optional[ProgressCb]):
    """Прокси: даёт sync-функцию emit(line) для кода внутри asyncio.to_thread,
    которая асинхронно стримит строки в async progress_cb.

    Один паттерн (queue + drain) — переиспользуется всеми сервисами для
    live-вывода. Сервис работает в синхронном _install_sync (через to_thread),
    а прогресс корректно доходит до task_manager без блокировки event loop.

        async with sync_progress(progress_cb) as emit:
            await asyncio.to_thread(install_sync, server, params, emit)
    """
    loop = asyncio.get_running_loop()
    q: "_queue.Queue[Optional[str]]" = _queue.Queue()

    async def _drain() -> None:
        while True:
            item = await loop.run_in_executor(None, q.get)
            if item is None:
                return
            if progress_cb:
                try:
                    await progress_cb(item)
                except Exception as e:
                    print(f"[INTEGRATOR] progress cb: {e}", flush=True)

    drain_task = asyncio.create_task(_drain())

    def emit(line: str) -> None:
        q.put(line)

    try:
        yield emit
    finally:
        q.put(None)
        try:
            await drain_task
        except Exception:
            pass


# --------------------------------------------------
# События сервиса
# --------------------------------------------------

def emit_service_event(
    service_id: str,
    level: "EventLevel",
    title: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Записать событие жизненного цикла сервиса в журнал (core.event_service).

    level — член EventLevel (INFO/WARNING/CRITICAL).
    """
    try:
        from core.event_service import create_event
        from core.event_types import EventLevel, EventType

        create_event(
            event_type=EventType.SERVICE,
            level=level,
            title=title,
            message=message,
            details={"service_id": service_id, **(details or {})},
            notify=(level == EventLevel.CRITICAL),
        )
    except Exception as e:
        print(f"[INTEGRATOR] event error: {e}", flush=True)


# --------------------------------------------------
# Связка с Task Manager
# --------------------------------------------------

# Один обобщённый исполнитель; service + action едут в payload.
# task_manager даёт очередь, live-output, отмену, retry, историю, события.
# Так сервисы НЕ дублируют очередь/вывод — они лишь описывают работу в do_*.
async def _svc_executor(
    payload: Dict[str, Any], task: Task, progress_cb: ProgressCb
) -> TaskResult:
    service_id = payload.get("service")
    action = payload.get("action")
    params = payload.get("params") or {}

    try:
        svc = _get_service(service_id)
    except Exception as e:
        return TaskResult(success=False, error=str(e))

    # Обобщённый диспетч: action → svc.do_<action>(server_id, params, progress_cb).
    # Любой do_*-метод сервиса автоматически становится действием через очередь.
    method = getattr(svc, f"do_{action}", None)
    if not callable(method):
        return TaskResult(
            success=False, error=f"Действие '{action}' не реализовано для '{service_id}'"
        )

    try:
        result = await method(task.server_id, params, progress_cb)
    except StepError as e:
        return TaskResult(success=False, error=str(e), output=e.detail)
    except Exception as e:
        return TaskResult(success=False, error=f"{type(e).__name__}: {e}")

    if not isinstance(result, TaskResult):
        return TaskResult(
            success=False, error=f"do_{action} должен возвращать TaskResult"
        )

    # После действия — обновить кэш (мост между TG- и веб-процессами).
    # Не роняем задачу из-за ошибки синхронизации.
    try:
        await sync(service_id, task.server_id)
    except Exception as e:
        print(f"[INTEGRATOR] post-action sync error: {e}", flush=True)

    return result



async def _svc_scan_executor(
    payload: Dict[str, Any], task: Task, progress_cb: ProgressCb
) -> TaskResult:
    """Полная проверка сервиса на всех серверах (Live Output)."""
    from core.storage import load_servers

    service_id = payload.get("service")
    if not service_id:
        return TaskResult(success=False, error="service не указан")

    servers = load_servers()
    if not servers:
        return TaskResult(success=True, output="Серверов для проверки нет")

    lines: List[str] = []
    ok = warn = fail = 0
    for s in servers:
        sid = s["id"]
        sname = s.get("name", sid)
        try:
            status = await sync(service_id, sid) or {}
            if status.get("installed"):
                mark = f"• {sname} — установлен"
                ok += 1
            elif status.get("error"):
                mark = f"• {sname} — ошибка: {status.get('error')}"
                warn += 1
            else:
                mark = f"• {sname} — не установлен"
                fail += 1
        except Exception as e:
            mark = f"• {sname} — ошибка: {e}"
            warn += 1
        await progress_cb(mark)
        lines.append(mark)

    summary = "\n".join(lines)
    return TaskResult(success=True, output=summary)


register_executor("svc_scan", _svc_scan_executor)


register_executor("svc", _svc_executor)


# --------------------------------------------------
# Публичный API (для UI: telegram / web)
# --------------------------------------------------

async def _enqueue_action(
    service_id: str,
    server_id: str,
    action: str,
    params: Optional[Dict[str, Any]] = None,
    src: Optional[str] = None,
) -> Task:
    from core.storage import find_server

    manifest = get_manifest(service_id)
    if not manifest:
        raise ValueError(f"Неизвестный сервис: {service_id}")
    server = find_server(server_id)
    if not server:
        raise ValueError("Сервер не найден")

    payload: Dict[str, Any] = {
        "service": service_id,
        "action": action,
        "params": params or {},
    }
    if src:
        payload["src"] = src
    return await task_manager.enqueue(
        name=f"{manifest.name}: {_get_service(service_id).resolve_task_title(action)}",
        server_id=server_id,
        server_name=server.get("name", server_id),
        kind="svc",
        payload=payload,
    )


async def enqueue(
    service_id: str,
    server_id: str,
    action: str,
    params: Optional[Dict[str, Any]] = None,
    src: Optional[str] = None,
) -> Task:
    """Поставить в очередь любое действие сервиса (dispatch на svc.do_<action>)."""
    return await _enqueue_action(service_id, server_id, action, params, src=src)


async def install(
    service_id: str, server_id: str, params: Optional[Dict[str, Any]] = None
) -> Task:
    """Поставить в очередь установку сервиса. Возвращает Task (с live-выводом)."""
    return await enqueue(service_id, server_id, "install", params)


async def remove(service_id: str, server_id: str) -> Task:
    """Поставить в очередь удаление сервиса."""
    return await enqueue(service_id, server_id, "remove")


async def call(service_id: str, server_id: str, method: str, *args: Any) -> Any:
    """Прямой (без очереди) вызов метода сервиса.

    Sync-методы (get_status, get_profiles, fetch_profile_config, set_endpoint) —
    в потоке через asyncio.to_thread, чтобы не блокировать event loop.
    Async-методы (do_* quick-ops: toggle/rename/reissue/add/remove_profile) —
    напрямую await (они сами делегируют SSH в to_thread через sync_progress).
    Раньше async do_* через to_thread возвращали НЕawaitенную корутину — теперь
    различаем по iscoroutinefunction.
    """
    svc = _get_service(service_id)
    fn = getattr(svc, method, None)
    if not callable(fn):
        raise ValueError(f"Метод '{method}' не найден у сервиса '{service_id}'")
    if asyncio.iscoroutinefunction(fn):
        return await fn(server_id, *args)
    return await asyncio.to_thread(fn, server_id, *args)


def params_schema(service_id: str) -> List[Parameter]:
    """Схема параметров установки сервиса (для UI-мастера).

    Синхронная (params_schema() не зависит от сервера); instantiation сервиса
    ленивая и дёшева. UI вызывает это напрямую, а не через call (нет server_id).
    """
    return _get_service(service_id).params_schema()


async def sync(service_id: str, server_id: str) -> Dict[str, Any]:
    """Напрямую (без очереди): read-only запрос состояния → кэш."""
    svc = _get_service(service_id)
    data = await svc.do_sync(server_id)
    data = dict(data)
    data.setdefault("service_id", service_id)
    data["synced_at"] = datetime.now().isoformat(timespec="seconds")
    write_cache(service_id, server_id, data)
    return data




async def enqueue_bulk_check(service_id: str) -> Task:
    """Полная проверка сервиса на всех серверах через Task Manager."""
    manifest = get_manifest(service_id)
    if not manifest:
        raise ValueError(f"Неизвестный сервис: {service_id}")
    return await task_manager.enqueue(
        name=f"{manifest.name}: полная проверка",
        server_id="__scan__",
        server_name="Все серверы",
        kind="svc_scan",
        payload={"service": service_id, "action": "bulk_check", "src": "tasks"},
    )

# Заполнить реестр манифестов при импорте модуля (модули сервисов НЕ грузятся).
discover_services()
