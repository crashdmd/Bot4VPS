# -*- coding: utf-8 -*-
"""Docker-специфичный Telegram-UI.

Сценарий Telegram: быстро проверить → установить → запустить → управлять.
Подробная настройка и редактирование Compose — только Web UI.

Карта раздела:
    🐳 Docker
    ├── 🔄 Проверить все серверы
    ├── 🛠 Установить Docker            (только серверы без Docker)
    ├── 📋 Compose                      (локальная библиотека, без сервера)
    │   ├── проекты → 🚀 Развернуть → выбор сервера
    │   └── 📥 Загрузить (YAML или ZIP-проект)
    └── 🖥 <сервер>
        ├── 📦 Контейнеры → карточка → стоп/рестарт/логи/удалить/открыть сервис
        │   └── ➕ Запустить контейнер (пошаговый мастер)
        ├── 🖼 Образы → карточка → удалить; 📥 скачать образ
        └── 📋 Compose
            ├── 📚 Bot4VPS  (библиотека → 🚀 Запустить)
            └── 🖥 Сервер   (реальные проекты, в т.ч. внешние)

Сознательно НЕ реализуется (иначе Telegram превратится во второй Web):
    редактор Compose/файлов, кнопки «Открыть в Web», ввод Docker CLI, большие формы.

Вся логика — в services/docker/ через core.integrator; этот модуль только
отображает и маршрутизирует нажатия.
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from core import integrator
from core.integrator import get_manifest
from core.storage import find_server, load_servers
from state import DOCKER_CB_TOKENS, DOCKER_COMPOSE_UPLOAD, DOCKER_RUN_WIZARD

from .base import CallbackCtx, DocumentCtx, MessageCtx, ServiceUI, register_service_ui
from ._shared import (
    _back_from_service,
    _enqueue_watch_message,
    _enqueue_watch_query,
    _noop_progress,
    _svc_cb,
)

SERVICE_ID = "docker"

# Источники Compose-проекта (совпадают с константами core: services/docker/impl/compose.py)
SOURCE_LIBRARY = "library"
SOURCE_SERVER = "server"


# --------------------------------------------------------------
# Короткие токены для callback_data
#
# Telegram ограничивает callback_data 64 байтами, а deployment key внешнего
# проекта («project|/long/working/dir|/long/config/path») легко даёт 100+.
# Поэтому в кнопку кладём 8-символьный хеш, а полное значение держим в
# per-user словаре. Словарь перезаполняется при каждой отрисовке списка, так
# что «устаревший» токен просто не найдётся — обработчик попросит обновить список.
# --------------------------------------------------------------

def _token(user_id: int, value: str) -> str:
    """Короткий токен для значения; регистрирует его в словаре пользователя."""
    tok = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    DOCKER_CB_TOKENS.setdefault(user_id, {})[tok] = value
    return tok


def _resolve_token(user_id: int, tok: Optional[str]) -> Optional[str]:
    """Значение по токену (None, если список не отрисовывался в этой сессии)."""
    if not tok:
        return None
    return (DOCKER_CB_TOKENS.get(user_id) or {}).get(tok)


# --------------------------------------------------------------
# Форматтеры (данные приходят из Core, здесь только представление)
# --------------------------------------------------------------

def _fmt_uptime(seconds: Optional[int]) -> str:
    """Секунды → «45с» / «1м 23с» / «2ч 14м» / «5д 3ч». Core отдаёт число."""
    if seconds is None:
        return "—"
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if s < 0:
        return "—"
    if s < 60:
        return f"{s}с"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}м {s}с"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}ч {m}м"
    d, h = divmod(h, 24)
    return f"{d}д {h}ч"


def _short_version(raw: Optional[str]) -> str:
    """«Docker version 29.0.0, build abc» → «29.0.0»."""
    import re
    m = re.search(r"\d+\.\d+[\w.\-]*", str(raw or ""))
    return m.group(0) if m else "—"


def _state_icon(state: str) -> str:
    st = (state or "").strip().lower()
    if st == "running":
        return "🟢"
    if st in ("exited", "dead"):
        return "🔴"
    if st == "paused":
        return "⏸"
    return "🟡"


def _stack_icon(rec: Dict[str, Any]) -> str:
    """Иконка проекта на сервере: запущен / частично / остановлен."""
    total = int(rec.get("containers_total") or 0)
    running = int(rec.get("containers_running") or 0)
    if total and running == total:
        return "🟢"
    if running:
        return "🟡"
    return "⚪"


def _trim(text: str, limit: int = 3900) -> str:
    """Telegram не принимает сообщения длиннее ~4096 символов."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…(обрезано)"


async def _edit(query, text: str, kb: Optional[InlineKeyboardMarkup] = None):
    """edit_message_text с фолбэком на новое сообщение (сообщение могло устареть)."""
    try:
        await query.edit_message_text(_trim(text), reply_markup=kb)
    except Exception:
        try:
            await query.message.reply_text(_trim(text), reply_markup=kb)
        except Exception:
            pass


async def _get_state(server_id: str) -> Dict[str, Any]:
    """Живое состояние Docker на сервере (версия, контейнеры, образы)."""
    try:
        return await integrator.call(SERVICE_ID, server_id, "get_state") or {}
    except Exception as e:
        return {"installed": False, "error": str(e)}


async def _get_status(server_id: str) -> Dict[str, Any]:
    """Кэшированный статус (быстро, без SSH) — для списков серверов."""
    try:
        return await integrator.call(SERVICE_ID, server_id, "get_status") or {}
    except Exception:
        return {}


# ==============================================================
# §1 Главный хаб раздела «🐳 Docker»
# ==============================================================

async def _hub(query) -> None:
    """Точка входа раздела: только действия, без списка серверов.

    Серверы выбираются внутри «Управлять» / «Установить» — так список не
    дублируется в меню и каждая кнопка ведёт в свой, отфильтрованный набор.
    """
    installed = missing = unknown = 0
    for s in load_servers():
        inst = (await _get_status(s["id"])).get("installed")
        if inst is True:
            installed += 1
        elif inst is False:
            missing += 1
        else:
            unknown += 1

    lines = ["🐳 Docker", ""]
    total = installed + missing + unknown
    if not total:
        lines.append("Серверов нет — добавьте сервер в разделе «Серверы».")
    else:
        if installed:
            lines.append(f"🟢 С Docker: {installed}")
        if missing:
            lines.append(f"⚪ Без Docker: {missing}")
        if unknown:
            lines.append(f"❔ Не проверено: {unknown}")
        if not installed:
            lines += ["", "Ни на одном сервере Docker пока не найден.",
                      "Начните с «Проверить все серверы» или «Установить Docker»."]

    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton("🔄 Проверить все серверы", callback_data=f"tasks_svc_check:{SERVICE_ID}")],
        [InlineKeyboardButton("⚙️ Управлять Docker", callback_data=_svc_cb("dk_manage_list", SERVICE_ID, "-"))],
        [InlineKeyboardButton("🛠 Установить Docker", callback_data=_svc_cb("dk_install_list", SERVICE_ID, "-"))],
        [InlineKeyboardButton("📋 Compose", callback_data=_svc_cb("cl_list", SERVICE_ID, "-"))],
        [InlineKeyboardButton("⬅️ Задачи", callback_data="tasks")],
    ]
    await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))


# ==============================================================
# §2 Выбор сервера: управление (Docker есть) / установка (Docker нет)
# ==============================================================

async def _server_list(query, mode: str) -> None:
    """Список серверов, отфильтрованный по наличию Docker.

    mode="manage"  — только с Docker  → карточка сервера;
    mode="install" — только без Docker → подтверждение установки.
    Так «Управлять» и «Установить» симметричны и не смешивают серверы.
    """
    manage = (mode == "manage")
    rows: List[List[InlineKeyboardButton]] = []
    has_unknown = False
    for s in load_servers():
        inst = (await _get_status(s["id"])).get("installed")
        if manage:
            if inst is not True:
                continue
            label = f"🖥 {s['name']}"
            op = "dk_view"
        else:
            if inst is True:
                continue
            label = f"🖥 {s['name']}"
            if inst is None:
                label += " · нет данных"
                has_unknown = True
            op = "dk_install_one"
        rows.append([InlineKeyboardButton(label, callback_data=_svc_cb(op, SERVICE_ID, s["id"]))])

    if manage:
        lines = ["⚙️ Управление Docker", ""]
        if rows:
            lines.append("Выберите сервер:")
        else:
            lines += ["Нет серверов с установленным Docker.",
                      "", "Установите Docker или выполните «Проверить все серверы»."]
    else:
        lines = ["🛠 Установка Docker", ""]
        if rows:
            lines.append("Выберите сервер:")
            if has_unknown:
                lines += ["", "«нет данных» — сервер ещё не проверялся."]
        else:
            lines += ["Docker установлен на всех серверах.",
                      "Если это не так — сначала «Проверить все серверы»."]

    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("dk_hub", SERVICE_ID, "-"))])
    await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _install_confirm(query, server_id: str) -> None:
    server = find_server(server_id)
    name = server["name"] if server else server_id
    text = (
        f"🛠 Установка Docker\n\n"
        f"🖥 {name}\n\n"
        f"Docker Engine будет установлен официальным скриптом get.docker.com.\n"
        f"Это займёт несколько минут."
    )
    rows = [
        [InlineKeyboardButton("🚀 Установить", callback_data=_svc_cb("dk_install_run", SERVICE_ID, server_id))],
        [InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("dk_install_list", SERVICE_ID, "-"))],
    ]
    await _edit(query, text, InlineKeyboardMarkup(rows))


# ==============================================================
# §7 Карточка Docker на конкретном сервере
# ==============================================================

async def _server_card(
    query, server_id: str, src: Optional[str] = None, *, from_docker_hub: bool = False
) -> None:
    """Сводка по серверу: версия, счётчики, вход в разделы.

    При входе из меню «Сервисы» конкретного сервера кнопка «Назад» возвращает
    туда же (как у WireGuard). Только вход через общий Docker-хаб возвращает в
    список управления Docker — его помечает отдельный op ``dk_view``.
    """
    back_callback = (
        _svc_cb("dk_manage_list", SERVICE_ID, "-")
        if from_docker_hub or src == "tasks"
        else _back_from_service(SERVICE_ID, server_id, src)
    )
    refresh_callback = _svc_cb(
        "dk_view" if from_docker_hub else "view", SERVICE_ID, server_id, src=src
    )
    server = find_server(server_id)
    name = server["name"] if server else server_id
    st = await _get_state(server_id)

    if not st.get("installed"):
        err = st.get("error")
        lines = [f"🐳 Docker · {name}", "", "⚪ Docker не установлен"]
        if err:
            lines += ["", f"⚠️ {err}"]
        rows = [
            [InlineKeyboardButton("🛠 Установить Docker", callback_data=_svc_cb("dk_install_one", SERVICE_ID, server_id))],
            [InlineKeyboardButton("🔄 Синхронизировать", callback_data=_svc_cb("sync", SERVICE_ID, server_id, src=src))],
            [InlineKeyboardButton("⬅️ Назад", callback_data=back_callback)],
        ]
        await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))
        return

    containers = st.get("containers") or []
    stats = st.get("stats") or {}
    active = (st.get("active") or "").strip()
    daemon = "🟢" if active == "active" else "🔴"

    # Compose-проекты считаем отдельно: это отдельный SSH-запрос, поэтому
    # только для счётчика и без падения всей карточки при ошибке.
    compose_count = 0
    try:
        stacks = await integrator.call(SERVICE_ID, server_id, "get_stacks") or {}
        rows = stacks.get("rows") or []
        compose_count = sum(1 for r in rows if r.get("source") == "server")
    except Exception:
        pass

    lines = [
        f"🐳 Docker · {name}",
        "",
        f"{daemon} Docker {_short_version(st.get('version'))}",
        "",
        f"📦 Контейнеры: {stats.get('total', len(containers))}",
        f"▶ Запущено: {stats.get('running', 0)}",
        f"🖼 Образы: {stats.get('images', 0)}",
        f"📋 Compose: {compose_count}",
    ]
    rows = [
        [InlineKeyboardButton("📦 Контейнеры", callback_data=_svc_cb("ct_list", SERVICE_ID, server_id))],
        [InlineKeyboardButton("🖼 Образы", callback_data=_svc_cb("im_list", SERVICE_ID, server_id))],
        [InlineKeyboardButton("📋 Compose", callback_data=_svc_cb("cp_tabs", SERVICE_ID, server_id))],
        [InlineKeyboardButton("🔄 Обновить", callback_data=refresh_callback)],
        [
            InlineKeyboardButton("🗑 Удалить Docker", callback_data=_svc_cb("confirm_remove", SERVICE_ID, server_id, src=src)),
            InlineKeyboardButton("⬅️ Назад", callback_data=back_callback),
        ],
    ]
    await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))


# ==============================================================
# §8 Список контейнеров
# ==============================================================

async def _container_list(query, server_id: str) -> None:
    server = find_server(server_id)
    name = server["name"] if server else server_id
    st = await _get_state(server_id)
    containers = st.get("containers") or []

    lines = [f"🐳 Docker · {name}", "", "📦 Контейнеры", ""]
    rows: List[List[InlineKeyboardButton]] = []
    if not containers:
        lines.append("Контейнеров нет.")
    for c in containers:
        cname = c.get("name") or "?"
        icon = _state_icon(c.get("state"))
        lines.append(f"{icon} {cname}")
        if c.get("state") == "running" and c.get("uptime_seconds") is not None:
            lines.append(f"    ⏱ {_fmt_uptime(c.get('uptime_seconds'))}")
        else:
            lines.append(f"    {c.get('status') or c.get('state') or '—'}")
        lines.append(f"    {c.get('image') or '—'}")
        lines.append("")
        rows.append([InlineKeyboardButton(
            f"{icon} {cname}",
            callback_data=_svc_cb("ct_item", SERVICE_ID, server_id, _token(query.from_user.id, cname)),
        )])

    rows.append([InlineKeyboardButton("➕ Запустить контейнер", callback_data=_svc_cb("ct_new", SERVICE_ID, server_id))])
    rows.append([
        InlineKeyboardButton("🔄 Обновить", callback_data=_svc_cb("ct_list", SERVICE_ID, server_id)),
        InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("view", SERVICE_ID, server_id)),
    ])
    await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))


# ==============================================================
# §9 Карточка контейнера
# ==============================================================

async def _container_card(query, server_id: str, cname: str) -> None:
    st = await _get_state(server_id)
    containers = st.get("containers") or []
    c = next((x for x in containers if x.get("name") == cname), None)
    if c is None:
        await _edit(
            query,
            f"⚠️ Контейнер «{cname}» не найден.\nВозможно, он удалён — обновите список.",
            InlineKeyboardMarkup([[InlineKeyboardButton(
                "⬅️ К контейнерам", callback_data=_svc_cb("ct_list", SERVICE_ID, server_id))]]),
        )
        return

    running = c.get("state") == "running"
    icon = _state_icon(c.get("state"))
    lines = [f"🐳 {cname}", "", f"{icon} {c.get('status') or c.get('state') or '—'}"]
    if running:
        lines.append(f"⏱ Uptime: {_fmt_uptime(c.get('uptime_seconds'))}")
    lines += ["", "Образ:", c.get("image") or "—"]

    ports = c.get("ports") or []
    if ports:
        lines += ["", "Порты:"]
        lines += [f"  {p}" for p in ports]
    if running and (c.get("cpu") or c.get("mem")):
        lines += ["", f"CPU: {c.get('cpu') or '—'}", f"MEM: {c.get('mem') or '—'}"]
    if running and (c.get("net_in") or c.get("net_out")):
        lines.append(f"↓ {c.get('net_in') or '—'}   ↑ {c.get('net_out') or '—'}")

    tok = _token(query.from_user.id, cname)
    rows: List[List[InlineKeyboardButton]] = []
    if running:
        rows.append([
            InlineKeyboardButton("⏹ Остановить", callback_data=_svc_cb("ct_stop", SERVICE_ID, server_id, tok)),
            InlineKeyboardButton("🔄 Перезапустить", callback_data=_svc_cb("ct_restart", SERVICE_ID, server_id, tok)),
        ])
    else:
        rows.append([InlineKeyboardButton("▶ Запустить", callback_data=_svc_cb("ct_start", SERVICE_ID, server_id, tok))])
    rows.append([
        InlineKeyboardButton("📜 Логи", callback_data=_svc_cb("ct_logs", SERVICE_ID, server_id, tok)),
        InlineKeyboardButton("🗑 Удалить", callback_data=_svc_cb("ct_confirm_rm", SERVICE_ID, server_id, tok)),
    ])
    # «Открыть сервис» — прямая ссылка в приложение контейнера (не в Web Bot4VPS).
    url = c.get("service_url")
    if running and url:
        rows.append([InlineKeyboardButton("🌐 Открыть сервис", url=url)])
    rows.append([
        InlineKeyboardButton("🔄 Обновить", callback_data=_svc_cb("ct_item", SERVICE_ID, server_id, tok)),
        InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("ct_list", SERVICE_ID, server_id)),
    ])
    await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _container_logs(query, server_id: str, cname: str) -> None:
    await _edit(query, f"📜 Логи «{cname}»\n\n⏳ Читаю…")
    try:
        logs = await integrator.call(SERVICE_ID, server_id, "fetch_logs", cname, 40) or ""
    except Exception as e:
        logs = f"Не удалось получить логи: {e}"
    body = logs.strip() or "(логи пусты)"
    text = f"📜 Логи «{cname}»\n(последние строки)\n\n{body}"
    tok = _token(query.from_user.id, cname)
    rows = [[
        InlineKeyboardButton("🔄 Обновить", callback_data=_svc_cb("ct_logs", SERVICE_ID, server_id, tok)),
        InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("ct_item", SERVICE_ID, server_id, tok)),
    ]]
    await _edit(query, text, InlineKeyboardMarkup(rows))


async def _quick_action(query, server_id: str, action: str, params: Dict[str, Any],
                        back_cb: str, done_cb) -> None:
    """Секундная операция без очереди задач: вызвать do_* и обновить карточку.

    Очередь (enqueue + live-лог) оправдана для установки Docker или деплоя
    Compose — там минуты вывода. Для start/stop/restart/rm контейнера она лишь
    заставляет уходить в лог задачи и возвращаться руками, поэтому такие
    операции выполняем напрямую: «⏳ Выполняю…» → результат → свежая карточка.

    done_cb — корутина отрисовки экрана после успеха.
    """
    await _edit(query, "⏳ Выполняю…")
    try:
        result = await integrator.call(SERVICE_ID, server_id, f"do_{action}", params, _noop_progress)
        ok = bool(result and getattr(result, "success", False))
        err = getattr(result, "error", None) if result else "Неизвестная ошибка"
    except Exception as e:
        ok, err = False, str(e)

    if not ok:
        rows = [[InlineKeyboardButton("⬅️ Назад", callback_data=back_cb)]]
        await _edit(query, f"❌ Не удалось выполнить\n\n{err}", InlineKeyboardMarkup(rows))
        return

    # Кэш обновляем, чтобы списки серверов показывали свежие счётчики.
    try:
        await integrator.sync(SERVICE_ID, server_id)
    except Exception as e:
        print(f"[DOCKER-TG] sync после {action}: {e}", flush=True)
    await done_cb()


async def _container_confirm_rm(query, server_id: str, cname: str) -> None:
    tok = _token(query.from_user.id, cname)
    text = (
        f"⚠️ Удалить контейнер «{cname}»?\n\n"
        f"Он будет остановлен и удалён. Тома с данными сохранятся."
    )
    rows = [
        [InlineKeyboardButton("✅ Удалить", callback_data=_svc_cb("ct_rm", SERVICE_ID, server_id, tok))],
        [InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("ct_item", SERVICE_ID, server_id, tok))],
    ]
    await _edit(query, text, InlineKeyboardMarkup(rows))


# ==============================================================
# §10-14 Мастер запуска контейнера
#
# Пошагово, без больших форм и без ввода Docker CLI. Значения проверяются
# валидаторами Core (services/docker/impl/validation.py) — здесь не дублируем
# бизнес-правила, только просим ввод и показываем ошибку.
# ==============================================================

_WZ_IMAGE, _WZ_NAME, _WZ_PORTS, _WZ_ENV, _WZ_RESTART = "image", "name", "ports", "env", "restart"

_RESTART_CHOICES = [
    ("no", "❌ no — не перезапускать"),
    ("unless-stopped", "🔄 unless-stopped — кроме ручной остановки"),
    ("always", "🔄 always — всегда"),
    ("on-failure", "⚠ on-failure — только при ошибке"),
]


def _wizard_validate(kind: str, text: str) -> tuple[bool, str]:
    """Проверить ввод валидатором Core. (ok, сообщение об ошибке).

    Импорт локальный: UI не должен тянуть импл сервиса на уровне модуля.
    """
    try:
        from services.docker.impl import validation
        from core.integrator import StepError
    except Exception:
        return True, ""   # без валидатора не блокируем пользователя
    try:
        if kind == _WZ_IMAGE:
            validation.validate_image(text)
        elif kind == _WZ_NAME:
            validation.validate_name(text)
        elif kind == _WZ_PORTS:
            validation.validate_port(text)
        elif kind == _WZ_ENV:
            validation.validate_env(text)
        return True, ""
    except StepError as e:
        return False, getattr(e, "detail", "") or str(e)
    except Exception as e:
        return False, str(e)


def _wizard_kb(step: str, server_id: str, has_items: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура шага: пропуск/добавление + Назад/Отмена."""
    rows: List[List[InlineKeyboardButton]] = []
    if step == _WZ_PORTS:
        if has_items:
            rows.append([InlineKeyboardButton("➡ Далее", callback_data=_svc_cb("wz_next", SERVICE_ID, server_id))])
        else:
            rows.append([InlineKeyboardButton("⏭ Без портов", callback_data=_svc_cb("wz_next", SERVICE_ID, server_id))])
    elif step == _WZ_ENV:
        if has_items:
            rows.append([InlineKeyboardButton("➡ Далее", callback_data=_svc_cb("wz_next", SERVICE_ID, server_id))])
        else:
            rows.append([InlineKeyboardButton("⏭ Пропустить", callback_data=_svc_cb("wz_next", SERVICE_ID, server_id))])
    elif step == _WZ_RESTART:
        for value, label in _RESTART_CHOICES:
            rows.append([InlineKeyboardButton(
                label, callback_data=_svc_cb("wz_restart", SERVICE_ID, server_id, value),
            )])
    ctl = []
    if step != _WZ_IMAGE:
        ctl.append(InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("wz_back", SERVICE_ID, server_id)))
    ctl.append(InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("wz_cancel", SERVICE_ID, server_id)))
    rows.append(ctl)
    return InlineKeyboardMarkup(rows)


def _wizard_text(state: Dict[str, Any]) -> str:
    """Текст текущего шага мастера."""
    step = state["step"]
    ports = state.get("ports") or []
    env = state.get("env") or []
    if step == _WZ_IMAGE:
        return (
            "🚀 Запуск контейнера · шаг 1/5\n\n"
            "Введите Docker-образ сообщением.\n\n"
            "Например:\n  nginx:alpine\n  louislam/uptime-kuma:latest"
        )
    if step == _WZ_NAME:
        return (
            f"🚀 Запуск контейнера · шаг 2/5\n\n"
            f"Образ: {state.get('image')}\n\n"
            f"Введите имя контейнера.\n\nНапример:\n  my-nginx"
        )
    if step == _WZ_PORTS:
        lines = [
            "🚀 Запуск контейнера · шаг 3/5", "",
            "Введите порт в формате host:container.", "",
            "Например:\n  8080:80",
        ]
        if ports:
            lines += ["", "Уже добавлено:"] + [f"  • {p}" for p in ports]
            lines += ["", "Пришлите ещё порт или нажмите «Далее»."]
        else:
            lines += ["", "Если порты не нужны — «Без портов»."]
        return "\n".join(lines)
    if step == _WZ_ENV:
        lines = [
            "🚀 Запуск контейнера · шаг 4/5", "",
            "Введите переменную окружения в формате KEY=VALUE.", "",
            "Например:\n  TZ=Europe/Amsterdam",
        ]
        if env:
            lines += ["", "Уже добавлено:"] + [f"  • {e}" for e in env]
            lines += ["", "Пришлите ещё переменную или нажмите «Далее»."]
        else:
            lines += ["", "Если переменные не нужны — «Пропустить»."]
        return "\n".join(lines)
    return "🚀 Запуск контейнера · шаг 5/5\n\nВыберите политику перезапуска:"


async def _wizard_start(query, server_id: str) -> None:
    uid = query.from_user.id
    # См. _compose_upload_prompt: держим активным только один текстовый flow.
    DOCKER_COMPOSE_UPLOAD.pop(uid, None)
    DOCKER_RUN_WIZARD[uid] = {
        "step": _WZ_IMAGE, "server": server_id,
        "image": None, "name": None, "ports": [], "env": [], "restart": None,
    }
    await _edit(query, _wizard_text(DOCKER_RUN_WIZARD[uid]), _wizard_kb(_WZ_IMAGE, server_id))


async def _wizard_show(target, user_id: int) -> None:
    """Отрисовать текущий шаг (target — query или message)."""
    state = DOCKER_RUN_WIZARD.get(user_id)
    if not state:
        return
    step = state["step"]
    has_items = bool(state.get("ports") if step == _WZ_PORTS else state.get("env"))
    kb = _wizard_kb(step, state["server"], has_items)
    text = _wizard_text(state)
    if hasattr(target, "edit_message_text"):
        await _edit(target, text, kb)
    else:
        await target.reply_text(_trim(text), reply_markup=kb)


async def _wizard_summary(target, user_id: int) -> None:
    """§13: итог перед запуском — пользователь видит, что именно создаётся."""
    state = DOCKER_RUN_WIZARD.get(user_id)
    if not state:
        return
    server = find_server(state["server"])
    sname = server["name"] if server else state["server"]
    ports = state.get("ports") or []
    env = state.get("env") or []
    lines = [
        "🚀 Новый контейнер", "",
        f"Сервер:\n  🖥 {sname}", "",
        f"Образ:\n  {state.get('image')}", "",
        f"Имя:\n  {state.get('name')}", "",
        "Порты:",
    ]
    lines += [f"  {p}" for p in ports] if ports else ["  —"]
    lines += ["", "Переменные:"]
    lines += [f"  {e}" for e in env] if env else ["  —"]
    lines += ["", f"Restart:\n  {state.get('restart') or 'no'}"]
    rows = [
        [InlineKeyboardButton("🚀 Запустить", callback_data=_svc_cb("wz_run", SERVICE_ID, state["server"]))],
        [
            InlineKeyboardButton("⬅️ Изменить", callback_data=_svc_cb("wz_back", SERVICE_ID, state["server"])),
            InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("wz_cancel", SERVICE_ID, state["server"])),
        ],
    ]
    kb = InlineKeyboardMarkup(rows)
    text = "\n".join(lines)
    if hasattr(target, "edit_message_text"):
        await _edit(target, text, kb)
    else:
        await target.reply_text(_trim(text), reply_markup=kb)


_WZ_ORDER = [_WZ_IMAGE, _WZ_NAME, _WZ_PORTS, _WZ_ENV, _WZ_RESTART]


async def _wizard_advance(target, user_id: int) -> None:
    """Перейти к следующему шагу (или к сводке, если шаги кончились)."""
    state = DOCKER_RUN_WIZARD.get(user_id)
    if not state:
        return
    idx = _WZ_ORDER.index(state["step"])
    if idx + 1 < len(_WZ_ORDER):
        state["step"] = _WZ_ORDER[idx + 1]
        await _wizard_show(target, user_id)
    else:
        state["step"] = "summary"
        await _wizard_summary(target, user_id)


async def _wizard_back(target, user_id: int) -> None:
    state = DOCKER_RUN_WIZARD.get(user_id)
    if not state:
        return
    step = state["step"]
    if step == "summary":
        state["step"] = _WZ_RESTART
        await _wizard_show(target, user_id)
        return
    idx = _WZ_ORDER.index(step)
    if idx > 0:
        state["step"] = _WZ_ORDER[idx - 1]
        # при возврате на шаг-список очищаем накопленное, чтобы не путать
        if state["step"] == _WZ_PORTS:
            state["ports"] = []
        elif state["step"] == _WZ_ENV:
            state["env"] = []
        await _wizard_show(target, user_id)


# ==============================================================
# §15 Образы
# ==============================================================

async def _image_list(query, server_id: str) -> None:
    server = find_server(server_id)
    name = server["name"] if server else server_id
    try:
        images = await integrator.call(SERVICE_ID, server_id, "get_images") or []
    except Exception as e:
        images = []
        await _edit(query, f"⚠️ Не удалось получить образы:\n{e}")

    lines = [f"🐳 Docker · {name}", "", "🖼 Образы", ""]
    rows: List[List[InlineKeyboardButton]] = []
    if not images:
        lines.append("Образов нет.")
    for img in images[:40]:   # ограничиваем длину сообщения и число кнопок
        full = f"{img.get('repository')}:{img.get('tag')}"
        lines.append(f"• {full}  ({img.get('size') or '—'})")
        rows.append([InlineKeyboardButton(
            full, callback_data=_svc_cb("im_item", SERVICE_ID, server_id, _token(query.from_user.id, full)),
        )])
    if len(images) > 40:
        lines.append(f"\n…и ещё {len(images) - 40}. Полный список — в Web UI.")

    rows.append([InlineKeyboardButton("📥 Скачать образ", callback_data=_svc_cb("im_pull", SERVICE_ID, server_id))])
    rows.append([
        InlineKeyboardButton("🧹 Очистить неиспользуемые", callback_data=_svc_cb("im_confirm_prune", SERVICE_ID, server_id)),
    ])
    rows.append([
        InlineKeyboardButton("🔄 Обновить", callback_data=_svc_cb("im_list", SERVICE_ID, server_id)),
        InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("view", SERVICE_ID, server_id)),
    ])
    await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _image_card(query, server_id: str, full: str) -> None:
    try:
        images = await integrator.call(SERVICE_ID, server_id, "get_images") or []
    except Exception:
        images = []
    img = next(
        (i for i in images if f"{i.get('repository')}:{i.get('tag')}" == full), None
    )
    if img is None:
        await _edit(
            query, f"⚠️ Образ «{full}» не найден — обновите список.",
            InlineKeyboardMarkup([[InlineKeyboardButton(
                "⬅️ К образам", callback_data=_svc_cb("im_list", SERVICE_ID, server_id))]]),
        )
        return
    lines = [
        f"🖼 {full}", "",
        f"ID: {img.get('id') or '—'}",
        f"Размер: {img.get('size') or '—'}",
        f"Создан: {img.get('created') or '—'}",
    ]
    tok = _token(query.from_user.id, full)
    rows = [
        [InlineKeyboardButton("🗑 Удалить", callback_data=_svc_cb("im_confirm_rm", SERVICE_ID, server_id, tok))],
        [InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("im_list", SERVICE_ID, server_id))],
    ]
    await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))


# ==============================================================
# §16-18 Compose внутри сервера: две библиотеки
# ==============================================================

async def _compose_tabs(query, server_id: str) -> None:
    server = find_server(server_id)
    name = server["name"] if server else server_id
    text = (
        f"🐳 Docker · {name}\n\n"
        f"📋 Compose\n\n"
        f"📚 Bot4VPS — проекты из библиотеки, можно развернуть на этот сервер.\n"
        f"🖥 Сервер — проекты, фактически находящиеся на сервере (включая внешние)."
    )
    rows = [
        [InlineKeyboardButton("📚 Bot4VPS", callback_data=_svc_cb("cp_lib", SERVICE_ID, server_id))],
        [InlineKeyboardButton("🖥 Сервер", callback_data=_svc_cb("cp_srv", SERVICE_ID, server_id))],
        [InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("view", SERVICE_ID, server_id))],
    ]
    await _edit(query, text, InlineKeyboardMarkup(rows))


async def _compose_lib_on_server(query, server_id: str) -> None:
    """📚 Bot4VPS: библиотека в контексте сервера — только запуск (§16.1).

    Статус каждой локальной копии на этом сервере — из rows (§4): развёрнут /
    нет. Загрузка живёт в верхнеуровневом разделе Compose, редактирование — в Web.
    """
    try:
        data = await integrator.call(SERVICE_ID, server_id, "get_stacks") or {}
    except Exception as e:
        await _edit(query, f"⚠️ Не удалось получить список:\n{e}")
        return
    # Библиотечные проекты = строки с in_library; их статус на сервере виден
    # прямо здесь (running/stopped/absent/conflict).
    lib_rows = [r for r in (data.get("rows") or []) if r.get("in_library")]
    by_name: Dict[str, Dict[str, Any]] = {}
    for r in lib_rows:
        by_name.setdefault(r.get("name"), r)
        # серверная строка информативнее заглушки — предпочитаем её
        if r.get("source") == "server":
            by_name[r.get("name")] = r

    lines = ["📚 Bot4VPS · библиотека", ""]
    rows: List[List[InlineKeyboardButton]] = []
    if not lib_rows:
        lines.append("Библиотека пуста.")
        lines.append("Загрузить проект: 🐳 Docker → 📋 Compose → 📥 Загрузить.")
    for nm, r in by_name.items():
        st = r.get("status")
        mark = {"running": "🟢", "stopped": "⚪", "absent": "⚫"}.get(st, "⚠️")
        lines.append(f"{mark} {nm}")
        if st == "running":
            lines.append(f"    контейнеры: {r.get('containers_running', 0)}/{r.get('containers_total', 0)}")
        elif st == "stopped":
            lines.append("    развёрнут, не запущен")
        elif st == "absent":
            lines.append("    на сервере отсутствует")
        else:
            lines.append(f"    конфликт имён ({r.get('conflict_count', '?')})")
        lines.append("")
        rows.append([InlineKeyboardButton(
            f"{mark} {nm}",
            callback_data=_svc_cb("cp_lib_item", SERVICE_ID, server_id, _token(query.from_user.id, nm)),
        )])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("cp_tabs", SERVICE_ID, server_id))])
    await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _compose_lib_item_on_server(query, server_id: str, name: str) -> None:
    """Карточка библиотечного проекта в контексте сервера.

    Только развёртывание: импорт здесь не нужен — проект уже в библиотеке,
    а редактирование файлов живёт в Web UI.
    """
    tok = _token(query.from_user.id, name)
    lines = [f"📦 {name}", "", "Проект библиотеки Bot4VPS"]

    # Состав проекта: пользователю полезно видеть, что развернётся (compose,
    # .env, config/…), а не только имя.
    st = next((s for s in _library() if s.get("name") == name), None)
    if st:
        files = [st.get("compose_file") or "docker-compose.yml"]
        files += list(st.get("extra_files") or [])
        lines.append("")
        lines += [f"  {f}" for f in files[:12]]
        if len(files) > 12:
            lines.append(f"  …и ещё {len(files) - 12}")
        services = st.get("services") or []
        if services:
            lines += ["", "Сервисы: " + ", ".join(services)]

    lines += ["", "Запуск развернёт проект на этот сервер и поднимет контейнеры."]
    rows = [
        [InlineKeyboardButton("🚀 Развернуть", callback_data=_svc_cb("cp_lib_up", SERVICE_ID, server_id, tok))],
        [InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("cp_lib", SERVICE_ID, server_id))],
    ]
    await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _compose_server_list(query, server_id: str) -> None:
    """🖥 Проекты на сервере (docs/compose-model.md §4-5): три статуса + метка
    локальной копии; деления «Managed/Внешний» больше нет."""
    try:
        data = await integrator.call(SERVICE_ID, server_id, "get_stacks") or {}
    except Exception as e:
        await _edit(query, f"⚠️ Не удалось получить список:\n{e}")
        return
    rows_data = [r for r in (data.get("rows") or []) if r.get("source") == "server"]
    accessible = data.get("server_accessible")

    lines = ["🖥 Compose на сервере", ""]
    rows: List[List[InlineKeyboardButton]] = []
    if not accessible:
        lines.append("⚠️ Сервер недоступен по SSH.")
    elif not rows_data:
        lines.append("Compose-проектов не обнаружено.")
    for rec in rows_data:
        nm = rec.get("name")
        icon = _stack_icon(rec)
        lines.append(f"{icon} {nm}")
        lines.append(f"    {rec.get('working_dir') or '—'}")
        # Метка локальной копии (§5): ✅/⚠️/—.
        match = rec.get("lib_match")
        if match is True:
            lines.append("    🟢 копия совпадает")
        elif match is False:
            lines.append("    🟡 копия расходится")
        else:
            lines.append("    — нет в библиотеке")
        total = int(rec.get("containers_total") or 0)
        running = int(rec.get("containers_running") or 0)
        if total:
            lines.append(f"    контейнеры: {running}/{total}")
        lines.append("")
        # key нужен, чтобы одноимённые проекты из разных каталогов не путались
        rows.append([InlineKeyboardButton(
            f"{icon} {nm}",
            callback_data=_svc_cb("cp_srv_item", SERVICE_ID, server_id,
                                  _token(query.from_user.id, rec.get("key") or nm)),
        )])
    rows.append([
        InlineKeyboardButton("🔄 Обновить", callback_data=_svc_cb("cp_srv", SERVICE_ID, server_id)),
        InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("cp_tabs", SERVICE_ID, server_id)),
    ])
    await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _compose_server_item(query, server_id: str, key: str) -> None:
    """Карточка проекта на сервере (docs/compose-model.md §4-6)."""
    try:
        data = await integrator.call(SERVICE_ID, server_id, "get_stacks") or {}
    except Exception as e:
        await _edit(query, f"⚠️ Не удалось получить проект:\n{e}")
        return
    rec = next((r for r in (data.get("rows") or [])
                if r.get("source") == "server" and r.get("server", {}).get("key") == key), None)
    if rec is None:
        await _edit(
            query, "⚠️ Проект не найден — обновите список.",
            InlineKeyboardMarkup([[InlineKeyboardButton(
                "⬅️ К списку", callback_data=_svc_cb("cp_srv", SERVICE_ID, server_id))]]),
        )
        return

    nm = rec.get("name")
    srv = rec.get("server") or {}
    icon = _stack_icon(rec)
    total = int(rec.get("containers_total") or 0)
    running = int(rec.get("containers_running") or 0)
    lines = [f"📦 {nm}", "", rec.get("working_dir") or srv.get("working_dir") or "—"]
    cfgs = srv.get("config_files") or []
    if cfgs:
        lines.append("")
        lines.append("Compose: " + ", ".join(c.rsplit("/", 1)[-1] for c in cfgs))

    # Метка локальной копии (§5) — от неё зависит, предлагать ли импорт.
    in_lib = bool(rec.get("in_library"))
    match = rec.get("lib_match")
    lines.append("")
    if not in_lib:
        lines.append("📚 Локальная копия: нет")
    elif match is True:
        lines.append("✅ Локальная копия совпадает")
    elif match is False:
        lines.append("⚠️ Локальная копия расходится")
    else:
        lines.append("📚 Локальная копия есть (не сравнена)")

    lines.append("")
    if total:
        lines.append(f"{icon} Контейнеры: {running}/{total}")
    else:
        lines.append(f"{icon} Не запущен (файлы на месте)")

    tok = _token(query.from_user.id, key)
    rows: List[List[InlineKeyboardButton]] = []
    if total:
        rows.append([
            InlineKeyboardButton("⏹ Остановить", callback_data=_svc_cb("cp_srv_down", SERVICE_ID, server_id, tok)),
            InlineKeyboardButton("🔄 Перезапустить", callback_data=_svc_cb("cp_srv_restart", SERVICE_ID, server_id, tok)),
        ])
        rows.append([InlineKeyboardButton("📜 Логи", callback_data=_svc_cb("cp_srv_logs", SERVICE_ID, server_id, tok))])
    else:
        rows.append([InlineKeyboardButton("▶ Запустить", callback_data=_svc_cb("cp_srv_up", SERVICE_ID, server_id, tok))])

    # Импорт предлагаем, когда он осмыслен: проекта в библиотеке нет либо
    # серверная версия отличается. При полном совпадении кнопку скрываем —
    # иначе легко случайно перезаписать локальную копию тем же содержимым.
    if match is not True:
        label = "📥 Импортировать" if not in_lib else "📥 Обновить копию с сервера"
        rows.append([InlineKeyboardButton(
            label, callback_data=_svc_cb("cp_srv_import", SERVICE_ID, server_id, tok))])

    rows.append([InlineKeyboardButton("🚫 Игнорировать", callback_data=_svc_cb("cp_srv_ignore", SERVICE_ID, server_id, tok))])
    rows.append([InlineKeyboardButton("🗑 Удалить с сервера", callback_data=_svc_cb("cp_srv_confirm_rm", SERVICE_ID, server_id, tok))])
    rows.append([
        InlineKeyboardButton("🔄 Обновить", callback_data=_svc_cb("cp_srv_item", SERVICE_ID, server_id, tok)),
        InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("cp_srv", SERVICE_ID, server_id)),
    ])
    await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _compose_server_logs(query, server_id: str, key: str) -> None:
    name = key.split("|", 1)[0]
    await _edit(query, f"📜 Логи «{name}»\n\n⏳ Читаю…")
    try:
        logs = await integrator.call(
            SERVICE_ID, server_id, "fetch_stack_logs", name, 40, SOURCE_SERVER, key,
        ) or ""
    except Exception as e:
        logs = f"Не удалось получить логи: {e}"
    body = logs.strip() or "(логи пусты)"
    tok = _token(query.from_user.id, key)
    rows = [[
        InlineKeyboardButton("🔄 Обновить", callback_data=_svc_cb("cp_srv_logs", SERVICE_ID, server_id, tok)),
        InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("cp_srv_item", SERVICE_ID, server_id, tok)),
    ]]
    await _edit(query, f"📜 Логи «{name}»\n\n{body}", InlineKeyboardMarkup(rows))


async def _compose_import_start(query, server_id: str, key: str) -> None:
    """Импорт проекта с сервера в библиотеку: при перезаписи — подтверждение.

    Копируется весь каталог проекта (compose + .env + config/…), а не только
    YAML — этим занимается compose.import_from_server.
    """
    name = key.split("|", 1)[0]
    wd = key.split("|")[1] if "|" in key else ""
    tok = _token(query.from_user.id, key)

    in_lib = False
    match = None
    try:
        data = await integrator.call(SERVICE_ID, server_id, "get_stacks") or {}
        rec = next((r for r in (data.get("rows") or [])
                    if r.get("source") == "server" and r.get("server", {}).get("key") == key), None)
        if rec:
            in_lib = bool(rec.get("in_library"))
            match = rec.get("lib_match")
    except Exception:
        pass

    # Проекта в библиотеке нет — импортируем сразу, подтверждать нечего.
    if not in_lib:
        await _compose_import_run(query, server_id, key, overwrite=False)
        return

    diff = "Серверная версия отличается." if match is False else "Сравнить версии не удалось."
    text = (
        f"⚠️ Перезапись в библиотеке\n\n"
        f"Проект «{name}» уже есть в библиотеке Bot4VPS.\n{diff}\n\n"
        f"Источник:\n{wd}\n\n"
        f"Локальная копия будет заменена версией с сервера."
    )
    rows = [
        [InlineKeyboardButton("📥 Да, импортировать", callback_data=_svc_cb("cp_srv_import_run", SERVICE_ID, server_id, tok))],
        [InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("cp_srv_item", SERVICE_ID, server_id, tok))],
    ]
    await _edit(query, text, InlineKeyboardMarkup(rows))


async def _compose_import_run(query, server_id: str, key: str, overwrite: bool) -> None:
    """Импорт проекта с сервера в библиотеку — напрямую, без очереди задач.

    Слишком крупные каталоги отсекаются на стороне сервиса (PROJECT_READ_LIMIT)
    до чтения, поэтому здесь операция всегда короткая.
    """
    name = key.split("|", 1)[0]
    tok = _token(query.from_user.id, key)
    params = {"stack": name, "key": key, "overwrite": overwrite}
    # Импортируемый проект всегда меньше лимита чтения (крупнее — сразу отказ),
    # так что операция короткая: секунды на tar+base64 нескольких мегабайт.
    # Очередь тут только мешала бы — уводила в лог задачи и обратно руками.
    # Остаёмся на карточке проекта на сервере: пользователь пришёл оттуда.
    back = _svc_cb("cp_srv_item", SERVICE_ID, server_id, tok)
    done = lambda: _compose_server_item(query, server_id, key)
    await _quick_action(query, server_id, "compose_import", params, back, done)


async def _compose_server_confirm_rm(query, server_id: str, key: str) -> None:
    name = key.split("|", 1)[0]
    wd = key.split("|")[1] if "|" in key else ""
    tok = _token(query.from_user.id, key)
    text = (
        f"⚠️ Удалить проект «{name}» с сервера?\n\n"
        f"{wd}\n\n"
        f"Сначала выполняется остановка (тома сохраняются), и только при её успехе "
        f"каталог проекта удаляется.\n"
        f"Библиотека Bot4VPS не изменится."
    )
    rows = [
        [InlineKeyboardButton("✅ Удалить", callback_data=_svc_cb("cp_srv_rm", SERVICE_ID, server_id, tok))],
        [InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("cp_srv_item", SERVICE_ID, server_id, tok))],
    ]
    await _edit(query, text, InlineKeyboardMarkup(rows))


async def _compose_ignore(query, server_id: str, key: str) -> None:
    """Игнорировать проект (§11): строка и его контейнеры скрываются.

    Подтверждение не нужно — действие обратимое (Web: модалка «Игнорируемые»;
    здесь — после игнора показываем список, где проекта больше нет).
    """
    name = key.split("|", 1)[0]
    try:
        await integrator.call(SERVICE_ID, server_id, "set_ignored", name, key)
    except Exception as e:
        await _edit(query, f"⚠️ Не удалось игнорировать:\n{e}")
        return
    await _compose_server_list(query, server_id)


# ==============================================================
# §3-6 Верхнеуровневый раздел Compose (локальная библиотека, без сервера)
# ==============================================================

def _library() -> List[Dict[str, Any]]:
    """Список проектов библиотеки. Локальный ФС — сервер не нужен."""
    try:
        from services.docker.impl import compose_store
        return compose_store.list_stacks()
    except Exception:
        return []


async def _compose_library(query) -> None:
    library = _library()
    lines = ["📋 Compose", "", "📚 Локальная библиотека Bot4VPS", ""]
    rows: List[List[InlineKeyboardButton]] = []
    if not library:
        lines.append("Проектов нет.")
        lines.append("Пришлите Compose-файл или ZIP-проект кнопкой «Загрузить».")
    for st in library:
        nm = st.get("name")
        extra = st.get("files", 1)
        lines.append(f"📦 {nm}  (файлов: {extra})")
        rows.append([InlineKeyboardButton(
            f"📦 {nm}",
            callback_data=_svc_cb("cl_item", SERVICE_ID, "-", _token(query.from_user.id, nm)),
        )])
    lines += ["", "Редактирование Compose — в Web UI."]
    rows.append([InlineKeyboardButton("📥 Загрузить", callback_data=_svc_cb("cl_upload", SERVICE_ID, "-"))])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("dk_hub", SERVICE_ID, "-"))])
    await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _compose_library_item(query, name: str) -> None:
    st = next((s for s in _library() if s.get("name") == name), None)
    if st is None:
        await _edit(
            query, f"⚠️ Проект «{name}» не найден.",
            InlineKeyboardMarkup([[InlineKeyboardButton(
                "⬅️ К списку", callback_data=_svc_cb("cl_list", SERVICE_ID, "-"))]]),
        )
        return
    services = st.get("services") or []
    lines = [
        f"📦 {name}", "", "Compose Project",
        f"Файлов: {st.get('files', 1)}",
    ]
    if services:
        lines.append("Сервисы: " + ", ".join(services))
    if st.get("has_env"):
        lines.append("Есть .env")
    tok = _token(query.from_user.id, name)
    rows = [
        [InlineKeyboardButton("🚀 Развернуть", callback_data=_svc_cb("cl_deploy", SERVICE_ID, "-", tok))],
        [InlineKeyboardButton("🗑 Удалить", callback_data=_svc_cb("cl_confirm_rm", SERVICE_ID, "-", tok))],
        [InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("cl_list", SERVICE_ID, "-"))],
    ]
    await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _compose_deploy_targets(query, name: str) -> None:
    """§6: раздел не привязан к серверу — спрашиваем, куда развернуть."""
    rows: List[List[InlineKeyboardButton]] = []
    for s in load_servers():
        status = await _get_status(s["id"])
        if status.get("installed") is not True:
            continue   # не предлагаем сервер без Docker
        rows.append([InlineKeyboardButton(
            f"🖥 {s['name']}",
            callback_data=_svc_cb("cl_deploy_to", SERVICE_ID, s["id"], _token(query.from_user.id, name)),
        )])
    lines = [f"📦 {name}", "", "Куда развернуть?"]
    if not rows:
        lines.append("")
        lines.append("Нет серверов с установленным Docker.")
        lines.append("Сначала «🛠 Установить Docker».")
    rows.append([InlineKeyboardButton(
        "❌ Отмена", callback_data=_svc_cb("cl_item", SERVICE_ID, "-", _token(query.from_user.id, name)))])
    await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _compose_confirm_rm(query, name: str) -> None:
    tok = _token(query.from_user.id, name)
    text = (
        f"⚠️ Удалить проект «{name}» из библиотеки Bot4VPS?\n\n"
        f"Уже развёрнутые на серверах контейнеры продолжат работать — "
        f"это удаление только локальной копии."
    )
    rows = [
        [InlineKeyboardButton("✅ Удалить", callback_data=_svc_cb("cl_rm", SERVICE_ID, "-", tok))],
        [InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("cl_item", SERVICE_ID, "-", tok))],
    ]
    await _edit(query, text, InlineKeyboardMarkup(rows))


# ---- §4 Загрузка Compose-файла или ZIP-проекта ----

async def _compose_upload_prompt(query) -> None:
    uid = query.from_user.id
    # Два текстовых flow одновременно = чужой ввод перехватывается «зависшим»
    # состоянием. Вход в загрузку сбрасывает незакрытый мастер.
    DOCKER_RUN_WIZARD.pop(uid, None)
    DOCKER_COMPOSE_UPLOAD[uid] = {"stage": "await_file"}
    text = (
        "📥 Загрузка Compose-проекта\n\n"
        "Пришлите файл документом:\n"
        "  • docker-compose.yml / compose.yaml — один файл\n"
        "  • ZIP-архив — проект целиком (compose + .env + config/)\n\n"
        "Имя проекта возьму из имени файла или каталога в архиве."
    )
    rows = [[InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("cl_upload_cancel", SERVICE_ID, "-"))]]
    await _edit(query, text, InlineKeyboardMarkup(rows))


def _project_name_from_filename(filename: str) -> str:
    """Имя проекта из имени файла: «My Stack.zip» → «my-stack».

    Для compose.yml/docker-compose.yml осмысленного имени нет — вернём пустое,
    тогда спросим у пользователя.
    """
    import re
    base = re.sub(r"\.(zip|ya?ml)$", "", filename, flags=re.I)
    slug = re.sub(r"[^a-z0-9_-]+", "-", base.lower()).strip("-")
    if slug in ("compose", "docker-compose", ""):
        return ""
    return slug[:63]


def _kb_upload_cancel() -> InlineKeyboardMarkup:
    """Клавиатура для сообщений в процессе загрузки Compose.

    Пользователь остаётся в режиме ожидания файла, поэтому у КАЖДОГО ответа
    (в т.ч. при ошибке) должна быть кнопка выхода — иначе текст обещает
    «нажмите Отмена», а нажимать нечего.
    """
    return InlineKeyboardMarkup([[InlineKeyboardButton(
        "❌ Отмена", callback_data=_svc_cb("cl_upload_cancel", SERVICE_ID, "-"))]])


def _kb_wizard_cancel(server_id: str) -> InlineKeyboardMarkup:
    """Клавиатура для сообщений мастера: назад к шагам + отмена."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("wz_back", SERVICE_ID, server_id)),
        InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("wz_cancel", SERVICE_ID, server_id)),
    ]])


async def _compose_save_upload(message, user_id: int, name: str,
                               filename: str, data: bytes) -> None:
    """Сохранить присланный файл в библиотеку (§4) и показать результат."""
    is_zip = filename.lower().endswith(".zip")
    try:
        from services.docker.impl import compose_store
        if is_zip:
            info = compose_store.import_zip(name, data)
        else:
            info = compose_store.write_stack(name, data.decode("utf-8"))
    except UnicodeDecodeError:
        await message.reply_text(
            "❌ Файл не в кодировке UTF-8.\n"
            "Сохраните Compose-файл в UTF-8 и пришлите снова.",
            reply_markup=_kb_upload_cancel(),
        )
        return
    except Exception as e:
        detail = getattr(e, "detail", "") or str(e)
        title = getattr(e, "title", "") or "Не удалось сохранить"
        await message.reply_text(
            f"❌ {title}\n\n{detail}\n\nПришлите исправленный файл или отмените загрузку.",
            reply_markup=_kb_upload_cancel(),
        )
        return

    DOCKER_COMPOSE_UPLOAD.pop(user_id, None)
    nm = info.get("name", name)
    services = info.get("services") or []
    lines = ["✅ Compose-проект сохранён", "", f"📦 {nm}"]
    files_n = info.get("files")
    if files_n:
        lines.append(f"Файлов: {files_n}")
    if services:
        lines.append("Сервисы: " + ", ".join(services))
    tok = _token(user_id, nm)
    rows = [
        [InlineKeyboardButton("🚀 Развернуть", callback_data=_svc_cb("cl_deploy", SERVICE_ID, "-", tok))],
        [InlineKeyboardButton("🗑 Удалить", callback_data=_svc_cb("cl_confirm_rm", SERVICE_ID, "-", tok))],
        [InlineKeyboardButton("⬅️ К библиотеке", callback_data=_svc_cb("cl_list", SERVICE_ID, "-"))],
    ]
    await message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(rows))


# ==============================================================
# ServiceUI: регистрация и маршрутизация
# ==============================================================

class DockerUI(ServiceUI):
    """Telegram-отображение сервиса Docker."""

    service_id = SERVICE_ID
    #: Docker рисует хаб раздела сам: проверка / установка / Compose / серверы.
    owns_hub = True
    #: У Docker нет экрана "settings" — кнопка удаления стоит прямо на карточке
    #: сервера, поэтому отказ от удаления возвращает на неё.
    cancel_remove_op = "view"
    claims_ops = {
        # хаб, выбор сервера, установка
        "hub", "view", "dk_view", "dk_hub",
        "dk_manage_list", "dk_install_list", "dk_install_one", "dk_install_run",
        # контейнеры
        "ct_list", "ct_item", "ct_start", "ct_stop", "ct_restart",
        "ct_logs", "ct_confirm_rm", "ct_rm",
        # мастер запуска
        "ct_new", "wz_next", "wz_back", "wz_cancel", "wz_restart", "wz_run",
        # образы
        "im_list", "im_item", "im_confirm_rm", "im_rm",
        "im_pull", "im_confirm_prune", "im_prune",
        # compose внутри сервера
        "cp_tabs", "cp_lib", "cp_lib_item", "cp_lib_up",
        "cp_srv", "cp_srv_item", "cp_srv_up", "cp_srv_down", "cp_srv_restart",
        "cp_srv_logs", "cp_srv_import", "cp_srv_import_run",
        "cp_srv_confirm_rm", "cp_srv_rm", "cp_srv_ignore",
        # compose-библиотека (верхний уровень)
        "cl_list", "cl_item", "cl_deploy", "cl_deploy_to",
        "cl_confirm_rm", "cl_rm", "cl_upload", "cl_upload_cancel",
    }

    async def handle_callback(self, ctx: CallbackCtx) -> bool:
        op, query, uid = ctx.op, ctx.query, ctx.user_id
        srv, src = ctx.server_id, ctx.src
        tok = ctx.name

        # ---- хаб, выбор сервера, установка ----
        if op in ("hub", "dk_hub"):
            await _hub(query)
            return True
        if op == "view":
            await _server_card(query, srv, src=src)
            return True
        if op == "dk_view":
            await _server_card(query, srv, src=src, from_docker_hub=True)
            return True
        if op == "dk_manage_list":
            await _server_list(query, "manage")
            return True
        if op == "dk_install_list":
            await _server_list(query, "install")
            return True
        if op == "dk_install_one":
            await _install_confirm(query, srv)
            return True
        if op == "dk_install_run":
            await _enqueue_watch_query(query, SERVICE_ID, srv, "install", {}, src=src)
            return True

        # ---- контейнеры ----
        if op == "ct_list":
            await _container_list(query, srv)
            return True
        if op in ("ct_item", "ct_start", "ct_stop", "ct_restart",
                  "ct_logs", "ct_confirm_rm", "ct_rm"):
            cname = _resolve_token(uid, tok)
            if not cname:
                await _container_list(query, srv)
                return True
            if op == "ct_item":
                await _container_card(query, srv, cname)
            elif op == "ct_logs":
                await _container_logs(query, srv, cname)
            elif op == "ct_confirm_rm":
                await _container_confirm_rm(query, srv, cname)
            else:
                # start/stop/restart/rm — секунды, поэтому без очереди задач:
                # выполнили и сразу показали обновлённый экран.
                action = {
                    "ct_start": "container_start", "ct_stop": "container_stop",
                    "ct_restart": "container_restart", "ct_rm": "container_rm",
                }[op]
                if op == "ct_rm":
                    # контейнера больше нет — возвращаемся к списку
                    back = _svc_cb("ct_list", SERVICE_ID, srv)
                    done = lambda: _container_list(query, srv)
                else:
                    back = _svc_cb("ct_item", SERVICE_ID, srv, tok)
                    done = lambda: _container_card(query, srv, cname)
                await _quick_action(query, srv, action, {"name": cname}, back, done)
            return True

        # ---- мастер запуска контейнера ----
        if op == "ct_new":
            await _wizard_start(query, srv)
            return True
        if op == "wz_cancel":
            DOCKER_RUN_WIZARD.pop(uid, None)
            await _container_list(query, srv)
            return True
        if op == "wz_next":
            await _wizard_advance(query, uid)
            return True
        if op == "wz_back":
            await _wizard_back(query, uid)
            return True
        if op == "wz_restart":
            state = DOCKER_RUN_WIZARD.get(uid)
            if state:
                state["restart"] = tok or "no"
                state["step"] = "summary"
                await _wizard_summary(query, uid)
            else:
                await _container_list(query, srv)
            return True
        if op == "wz_run":
            state = DOCKER_RUN_WIZARD.pop(uid, None)
            if not state:
                await _container_list(query, srv)
                return True
            params: Dict[str, Any] = {
                "image": state.get("image"), "name": state.get("name"),
                "restart": state.get("restart") or "no",
            }
            if state.get("ports"):
                params["ports"] = state["ports"]
            if state.get("env"):
                params["env"] = state["env"]
            await _enqueue_watch_query(query, SERVICE_ID, srv, "container_run", params, src=src)
            return True

        # ---- образы ----
        if op == "im_list":
            await _image_list(query, srv)
            return True
        if op in ("im_item", "im_confirm_rm", "im_rm"):
            full = _resolve_token(uid, tok)
            if not full:
                await _image_list(query, srv)
                return True
            if op == "im_item":
                await _image_card(query, srv, full)
            elif op == "im_confirm_rm":
                rows = [
                    [InlineKeyboardButton("✅ Удалить", callback_data=_svc_cb("im_rm", SERVICE_ID, srv, tok))],
                    [InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("im_item", SERVICE_ID, srv, tok))],
                ]
                await _edit(query, f"⚠️ Удалить образ «{full}»?", InlineKeyboardMarkup(rows))
            else:
                # Удаление образа — тоже секунды, без очереди.
                await _quick_action(
                    query, srv, "image_rm", {"image": full},
                    _svc_cb("im_item", SERVICE_ID, srv, tok),
                    lambda: _image_list(query, srv),
                )
            return True
        if op == "im_pull":
            DOCKER_COMPOSE_UPLOAD.pop(uid, None)   # один активный текстовый flow
            DOCKER_RUN_WIZARD[uid] = {"step": "pull_image", "server": srv}
            rows = [[InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("im_list", SERVICE_ID, srv))]]
            await _edit(
                query,
                "📥 Скачать образ\n\nПришлите имя образа сообщением.\n\n"
                "Например:\n  nginx:alpine\n  redis:7-alpine",
                InlineKeyboardMarkup(rows),
            )
            return True
        if op == "im_confirm_prune":
            rows = [
                [InlineKeyboardButton("✅ Очистить", callback_data=_svc_cb("im_prune", SERVICE_ID, srv))],
                [InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("im_list", SERVICE_ID, srv))],
            ]
            await _edit(
                query,
                "⚠️ Удалить все образы, не используемые контейнерами?\n\n"
                "Образы с тегами тоже будут удалены, если к ним нет контейнеров.",
                InlineKeyboardMarkup(rows),
            )
            return True
        if op == "im_prune":
            await _quick_action(
                query, srv, "image_prune", {},
                _svc_cb("im_list", SERVICE_ID, srv),
                lambda: _image_list(query, srv),
            )
            return True

        # ---- compose внутри сервера ----
        if op == "cp_tabs":
            await _compose_tabs(query, srv)
            return True
        if op == "cp_lib":
            await _compose_lib_on_server(query, srv)
            return True
        if op in ("cp_lib_item", "cp_lib_up"):
            name = _resolve_token(uid, tok)
            if not name:
                await _compose_lib_on_server(query, srv)
                return True
            if op == "cp_lib_item":
                await _compose_lib_item_on_server(query, srv, name)
            else:
                await _enqueue_watch_query(
                    query, SERVICE_ID, srv, "compose_up",
                    {"stack": name, "source": SOURCE_LIBRARY}, src=src,
                )
            return True
        if op == "cp_srv":
            await _compose_server_list(query, srv)
            return True
        if op in ("cp_srv_item", "cp_srv_up", "cp_srv_down", "cp_srv_restart",
                  "cp_srv_logs", "cp_srv_import", "cp_srv_import_run",
                  "cp_srv_confirm_rm", "cp_srv_rm", "cp_srv_ignore"):
            key = _resolve_token(uid, tok)
            if not key:
                await _compose_server_list(query, srv)
                return True
            name = key.split("|", 1)[0]
            if op == "cp_srv_item":
                await _compose_server_item(query, srv, key)
            elif op == "cp_srv_logs":
                await _compose_server_logs(query, srv, key)
            elif op == "cp_srv_confirm_rm":
                await _compose_server_confirm_rm(query, srv, key)
            elif op == "cp_srv_ignore":
                # Игнор (§11): скрыть проект и его контейнеры. Мгновенная
                # операция с локальным кэшем — без очереди.
                await _compose_ignore(query, srv, key)
            elif op == "cp_srv_import":
                # Если такой проект уже в библиотеке — сначала подтверждение:
                # импорт перезапишет локальную копию.
                await _compose_import_start(query, srv, key)
            elif op == "cp_srv_import_run":
                # импорт — размер определяет маршрут (быстрый/очередь)
                await _compose_import_run(query, srv, key, overwrite=True)
            else:
                action = {
                    "cp_srv_up": "compose_up", "cp_srv_down": "compose_down",
                    "cp_srv_restart": "compose_restart", "cp_srv_rm": "compose_delete_remote",
                }[op]
                # up — долгая (pull образов), остальные быстрые
                if op == "cp_srv_up":
                    await _enqueue_watch_query(
                        query, SERVICE_ID, srv, action,
                        {"stack": name, "source": SOURCE_SERVER, "key": key}, src=src,
                    )
                else:
                    # down / restart / delete_remote — секунды, без очереди
                    back = _svc_cb("cp_srv_item", SERVICE_ID, srv, tok)
                    if op == "cp_srv_rm":
                        # проект удалён — возврат к списку
                        done = lambda: _compose_server_list(query, srv)
                    else:
                        # обновлённая карточка проекта
                        done = lambda: _compose_server_item(query, srv, key)
                    await _quick_action(
                        query, srv, action,
                        {"stack": name, "source": SOURCE_SERVER, "key": key},
                        back, done,
                    )
            return True

        # ---- compose-библиотека (верхний уровень) ----
        if op == "cl_list":
            await _compose_library(query)
            return True
        if op == "cl_upload":
            await _compose_upload_prompt(query)
            return True
        if op == "cl_upload_cancel":
            DOCKER_COMPOSE_UPLOAD.pop(uid, None)
            await _compose_library(query)
            return True
        if op in ("cl_item", "cl_deploy", "cl_confirm_rm", "cl_rm", "cl_deploy_to"):
            name = _resolve_token(uid, tok)
            if not name:
                await _compose_library(query)
                return True
            if op == "cl_item":
                await _compose_library_item(query, name)
            elif op == "cl_deploy":
                await _compose_deploy_targets(query, name)
            elif op == "cl_deploy_to":
                # srv здесь — выбранный сервер назначения
                await _enqueue_watch_query(
                    query, SERVICE_ID, srv, "compose_up",
                    {"stack": name, "source": SOURCE_LIBRARY}, src=src,
                )
            elif op == "cl_confirm_rm":
                await _compose_confirm_rm(query, name)
            else:
                try:
                    from services.docker.impl import compose_store
                    compose_store.delete_stack(name)
                    await query.answer("Проект удалён")
                except Exception as e:
                    await query.answer("Не удалось удалить", show_alert=True)
                    print(f"[DOCKER-TG] delete_stack({name}): {e}", flush=True)
                await _compose_library(query)
            return True

        return False

    # ----------------------------------------------------------
    # Текстовый ввод: мастер запуска контейнера, pull образа, имя проекта
    # ----------------------------------------------------------

    def owns_message(self, user_id: int) -> bool:
        return user_id in DOCKER_RUN_WIZARD or user_id in DOCKER_COMPOSE_UPLOAD

    async def handle_message(self, ctx: MessageCtx) -> bool:
        uid = ctx.user_id
        message = ctx.update.message
        text = (message.text or "").strip()

        # имя проекта для загруженного файла (когда из имени файла не вывелось)
        up = DOCKER_COMPOSE_UPLOAD.get(uid)
        if up and up.get("stage") == "await_name":
            pending = up.get("pending") or {}
            try:
                from services.docker.impl import compose_store
                name = compose_store.validate_stack_name(text)
            except Exception as e:
                detail = getattr(e, "detail", "") or str(e)
                await message.reply_text(
                    f"❌ {detail}\n\nПришлите другое имя.",
                    reply_markup=_kb_upload_cancel(),
                )
                return True
            await _compose_save_upload(
                message, uid, name,
                pending.get("filename", ""), pending.get("data", b""),
            )
            return True

        state = DOCKER_RUN_WIZARD.get(uid)
        if not state:
            return False

        srv = state.get("server", "-")

        # pull образа — отдельный однослойный ввод (у него своя кнопка выхода)
        if state.get("step") == "pull_image":
            ok, err = _wizard_validate(_WZ_IMAGE, text)
            if not ok:
                await message.reply_text(
                    f"❌ {err}\n\nПришлите имя образа ещё раз.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                        "❌ Отмена", callback_data=_svc_cb("im_list", SERVICE_ID, srv))]]),
                )
                return True
            DOCKER_RUN_WIZARD.pop(uid, None)
            await _enqueue_watch_message(
                message, ctx.context.bot, SERVICE_ID, srv, "image_pull", {"image": text},
            )
            return True

        # Ошибки шагов мастера: пользователь остаётся на шаге, поэтому у ответа
        # всегда есть «Назад» и «Отмена» — иначе из flow не выйти.
        step = state.get("step")
        hints = {
            _WZ_IMAGE: "Пришлите образ ещё раз.",
            _WZ_NAME: "Пришлите имя ещё раз.",
            _WZ_PORTS: "Формат: 8080:80",
            _WZ_ENV: "Формат: KEY=VALUE",
        }
        if step in (_WZ_IMAGE, _WZ_NAME, _WZ_PORTS, _WZ_ENV):
            ok, err = _wizard_validate(step, text)
            if not ok:
                await message.reply_text(
                    f"❌ {err}\n\n{hints[step]}",
                    reply_markup=_kb_wizard_cancel(srv),
                )
                return True
            if step == _WZ_IMAGE:
                state["image"] = text
                await _wizard_advance(message, uid)
            elif step == _WZ_NAME:
                state["name"] = text
                await _wizard_advance(message, uid)
            else:
                key = "ports" if step == _WZ_PORTS else "env"
                state.setdefault(key, []).append(text)
                await _wizard_show(message, uid)   # предложим добавить ещё или «Далее»
            return True
        return False

    # ----------------------------------------------------------
    # Документы: Compose-файл или ZIP-проект (§4)
    # ----------------------------------------------------------

    def owns_document(self, user_id: int) -> bool:
        st = DOCKER_COMPOSE_UPLOAD.get(user_id)
        return bool(st and st.get("stage") in ("await_file", "await_name"))

    async def handle_document(self, ctx: DocumentCtx) -> bool:
        uid = ctx.user_id
        message = ctx.update.message
        filename = ctx.filename
        lower = filename.lower()

        if not (lower.endswith(".zip") or lower.endswith(".yml") or lower.endswith(".yaml")):
            await message.reply_text(
                f"❌ Файл «{filename}» не подходит.\n\n"
                f"Ожидается Compose-файл (.yml / .yaml) или ZIP-архив проекта.\n"
                f"Пришлите другой файл или отмените загрузку.",
                reply_markup=_kb_upload_cancel(),
            )
            return True

        name = _project_name_from_filename(filename)
        if not name:
            # docker-compose.yml не даёт имени — спрашиваем у пользователя
            DOCKER_COMPOSE_UPLOAD[uid] = {
                "stage": "await_name",
                "pending": {"filename": filename, "data": ctx.data},
            }
            await message.reply_text(
                "📦 Как назвать проект?\n\n"
                "Пришлите имя сообщением: строчные латинские буквы, цифры, дефис.\n"
                "Например: uptime-kuma",
                reply_markup=_kb_upload_cancel(),
            )
            return True

        await _compose_save_upload(message, uid, name, filename, ctx.data)
        return True


register_service_ui(DockerUI())
