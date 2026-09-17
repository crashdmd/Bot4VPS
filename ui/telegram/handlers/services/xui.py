# -*- coding: utf-8 -*-
"""Telegram presentation and routing for the 3x-ui service."""
from __future__ import annotations

import hashlib
import string
from io import BytesIO
from pathlib import Path
from secrets import choice, randbelow, token_hex
from typing import Any, Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile

from core import integrator
from core.storage import find_server
from state import XUI_TG_STATE

from ._shared import (
    _back_from_service,
    _enqueue_watch_message,
    _enqueue_watch_query,
    _svc_cb,
)
from .base import CallbackCtx, DocumentCtx, MessageCtx, ServiceUI, register_service_ui

SERVICE_ID = "3x-ui"
_MAX_DB_IMPORT_SIZE = 5 * 1024 * 1024
_TEXT_KINDS = frozenset({
    "account_username", "account_password", "account_port", "account_path",
    "update_version", "cert_domain", "cert_ip", "fakesite_domain",
})
_TOKEN_OPS = frozenset({"xui_cren", "xui_crem"})


def _cb(op: str, server_id: str, name: str | None = None, src: str | None = None) -> str:
    return _svc_cb(op, SERVICE_ID, server_id, name, src)


def _trim(text: str, limit: int = 3900) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + "\n…(обрезано)"


async def _edit(query, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    try:
        await query.edit_message_text(_trim(text), reply_markup=kb)
    except Exception:
        try:
            await query.message.reply_text(_trim(text), reply_markup=kb)
        except Exception:
            pass


async def _state(server_id: str) -> Dict[str, Any]:
    try:
        return await integrator.call(SERVICE_ID, server_id, "get_state") or {}
    except Exception as exc:
        return {"installed": False, "error": str(exc)}


def _server_name(server_id: str) -> str:
    server = find_server(server_id)
    return str(server.get("name") or server_id) if server else server_id


def _active_line(value: Any) -> str:
    return "🟢 Активен" if value else "🔴 Неактивен"


def _geo_date(geo: Any, name: str) -> str:
    return str((geo or {}).get(name) or "—")


def _cert_records(cert: Any) -> list[dict[str, str]]:
    cert = cert if isinstance(cert, dict) else {}
    records: list[dict[str, str]] = []
    for domain, expires in (cert.get("domains") or {}).items():
        domain = str(domain or "").strip()
        if domain:
            records.append({"domain": domain, "engine": "acme", "expires": str(expires or "—")})
    for domain in cert.get("certbot_domains") or []:
        domain = str(domain or "").strip()
        if domain:
            records.append({"domain": domain, "engine": "certbot", "expires": "—"})
    return records


def _cert_token(user_id: int, record: dict[str, str]) -> str:
    token = hashlib.sha256(
        f"{record['domain']}:{record['engine']}".encode("utf-8")
    ).hexdigest()[:10]
    state = XUI_TG_STATE.setdefault(user_id, {})
    state.setdefault("cert_tokens", {})[token] = record
    return token


def _back_card(server_id: str, src: str | None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("← Назад", callback_data=_back_from_service(SERVICE_ID, server_id, src))],
    ])


async def _card(query, user_id: int, server_id: str, src: str | None) -> None:
    state = await _state(server_id)
    name = _server_name(server_id)
    if not state.get("installed"):
        text = f"🌐 3x-ui · {name}\n\n⚪ Не установлен"
        if state.get("error"):
            text += f"\n\n⚠️ {state['error']}"
        rows = [
            [InlineKeyboardButton("🟢 Установить 3x-ui", callback_data=_cb("xui_install", server_id, src=src))],
            [InlineKeyboardButton("← Назад", callback_data=_back_from_service(SERVICE_ID, server_id, src))],
        ]
        await _edit(query, text, InlineKeyboardMarkup(rows))
        return

    panel_url = str(state.get("panel_url") or "").strip()
    panel_button = (
        InlineKeyboardButton("🌐 Открыть панель", url=panel_url)
        if panel_url.startswith(("http://", "https://"))
        else InlineKeyboardButton("🌐 Открыть панель", callback_data=_cb("xui_panel", server_id, src=src))
    )
    rows = [
        [
            InlineKeyboardButton("⚙️ Сервис", callback_data=_cb("xui_service", server_id, src=src)),
            InlineKeyboardButton("🔐 Аккаунт панели", callback_data=_cb("xui_account", server_id, src=src)),
        ],
        [
            InlineKeyboardButton("📜 Сертификат", callback_data=_cb("xui_cert", server_id, src=src)),
            InlineKeyboardButton("🖥 Система", callback_data=_cb("xui_system", server_id, src=src)),
        ],
        [
            InlineKeyboardButton("🛠 Дополнительно", callback_data=_cb("xui_more", server_id, src=src)),
            panel_button,
        ],
        [InlineKeyboardButton("← Назад", callback_data=_back_from_service(SERVICE_ID, server_id, src))],
    ]
    await _edit(
        query,
        f"🌐 3x-ui · {name}\n\n{_active_line(state.get('active'))}\n{state.get('version') or '—'}\n\nГлавное меню:",
        InlineKeyboardMarkup(rows),
    )


async def _service_menu(query, server_id: str, src: str | None) -> None:
    state = await _state(server_id)
    enabled = bool(state.get("enabled"))
    rows = [
        [InlineKeyboardButton(
            "⏹ Выключить" if enabled else "▶ Включить",
            callback_data=_cb("xui_auto_off" if enabled else "xui_auto_on", server_id, src=src),
        ), InlineKeyboardButton(
            "⏹ Остановить" if state.get("active") else "▶ Запустить",
            callback_data=_cb("xui_stop" if state.get("active") else "xui_start", server_id, src=src),
        )],
        [InlineKeyboardButton("🔄 Рестарт", callback_data=_cb("xui_restart", server_id, src=src)),
         InlineKeyboardButton("📄 Логи", callback_data=_cb("xui_logs", server_id, src=src))],
        [InlineKeyboardButton("⬆️ Обновить", callback_data=_cb("xui_update", server_id, src=src)),
         InlineKeyboardButton("🔢 Другая версия", callback_data=_cb("xui_version", server_id, src=src))],
        [InlineKeyboardButton("← Назад", callback_data=_cb("view", server_id, src=src))],
    ]
    await _edit(
        query,
        f"⚙️ Сервис\n\n{'🟢' if enabled else '🔴'} Автозагрузка: {'включена' if enabled else 'выключена'}",
        InlineKeyboardMarkup(rows),
    )


async def _account_menu(query, server_id: str, src: str | None) -> None:
    await _edit(query, "🔐 Аккаунт панели", InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👤 Сменить логин", callback_data=_cb("xui_login", server_id, src=src)),
            InlineKeyboardButton("🔑 Сменить пароль", callback_data=_cb("xui_password", server_id, src=src)),
        ],
        [
            InlineKeyboardButton("🔌 Сменить порт", callback_data=_cb("xui_port", server_id, src=src)),
            InlineKeyboardButton("🔗 Изменить web base path", callback_data=_cb("xui_path", server_id, src=src)),
        ],
        [InlineKeyboardButton("← Назад", callback_data=_cb("view", server_id, src=src))],
    ]))


async def _cert_menu(query, user_id: int, server_id: str, src: str | None) -> None:
    state = await _state(server_id)
    cert = state.get("cert") if isinstance(state.get("cert"), dict) else {}
    records = _cert_records(cert)
    XUI_TG_STATE.pop(user_id, None)
    lines = ["📜 Сертификат", "", state.get("scheme", "http").upper()]
    if cert.get("panel_expires"):
        lines.append(f"Панель: до {cert['panel_expires']}")
    if records:
        lines.append("\nУправляемые сертификаты:")
        lines.extend(f"• {r['domain']} ({r['engine']}, до {r['expires']})" for r in records)
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton("🔒 Выпустить Let's Encrypt", callback_data=_cb("xui_cert_domain", server_id, src=src)),
            InlineKeyboardButton("📍 Выпустить для IP", callback_data=_cb("xui_cert_ip", server_id, src=src)),
        ],
    ]
    for record in records:
        token = _cert_token(user_id, record)
        rows.append([
            InlineKeyboardButton(f"🔄 Продлить {record['domain']}", callback_data=_cb("xui_cren", server_id, token, src)),
            InlineKeyboardButton(f"🗑 Удалить {record['domain']}", callback_data=_cb("xui_crem", server_id, token, src)),
        ])
    rows.append([InlineKeyboardButton("← Назад", callback_data=_cb("view", server_id, src=src))])
    await _edit(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _system_menu(query, server_id: str, src: str | None) -> None:
    state = await _state(server_id)
    bbr = state.get("bbr") or {}
    geo = state.get("geo") or {}
    enabled = bool(bbr.get("enabled"))
    await _edit(query, "\n".join([
        "🖥 Система", "",
        f"BBR: {'🟢 Включен' if enabled else '🔴 Выключен'}",
        f"geoip.dat: {_geo_date(geo, 'geoip.dat')}",
        f"geosite.dat: {_geo_date(geo, 'geosite.dat')}",
    ]), InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ Выключить BBR" if enabled else "⚡ Включить BBR", callback_data=_cb("xui_bbr_off" if enabled else "xui_bbr_on", server_id, src=src)),
            InlineKeyboardButton("🌍 Обновить geo-файлы", callback_data=_cb("xui_geo", server_id, src=src)),
        ],
        [InlineKeyboardButton("← Назад", callback_data=_cb("view", server_id, src=src))],
    ]))


async def _more_menu(query, server_id: str, src: str | None) -> None:
    fakesite: dict[str, Any] = {}
    try:
        data = await integrator.call(SERVICE_ID, server_id, "card_fakesite_info", {}) or {}
        fakesite = data.get("fakesite") or {}
    except Exception:
        pass
    present = bool(fakesite.get("present"))
    text = "🛠 Дополнительно"
    if present:
        text += f"\n\nSelfSNI: {fakesite.get('domain') or 'установлен'}"
    rows = [
        [
            InlineKeyboardButton("📤 Экспорт БД", callback_data=_cb("xui_db_export", server_id, src=src)),
            InlineKeyboardButton("📥 Импорт БД", callback_data=_cb("xui_db_import", server_id, src=src)),
        ],
        [
            InlineKeyboardButton("🗑 Удалить SelfSNI" if present else "🌐 Сайт-заглушка (SelfSNI)", callback_data=_cb("xui_fs_remove" if present else "xui_fs_install", server_id, src=src)),
            InlineKeyboardButton("🗑 Удалить 3x-ui", callback_data=_cb("xui_rm_confirm", server_id, src=src)),
        ],
        [InlineKeyboardButton("← Назад", callback_data=_cb("view", server_id, src=src))],
    ]
    await _edit(query, text, InlineKeyboardMarkup(rows))


async def _panel(query, server_id: str, src: str | None) -> None:
    state = await _state(server_id)
    url = str(state.get("panel_url") or "").strip()
    text = f"🌐 Открыть панель\n\n{url or 'Адрес панели пока недоступен.'}"
    await _edit(query, text, InlineKeyboardMarkup([
        [InlineKeyboardButton("← Назад", callback_data=_cb("view", server_id, src=src))],
    ]))


async def _direct_query(query, server_id: str, method: str, params: dict, back_op: str, src: str | None) -> None:
    await _edit(query, "⏳ Выполняю…")
    try:
        result = await integrator.call(SERVICE_ID, server_id, method, params)
        ok = bool(isinstance(result, dict) and result.get("success"))
        output = (result or {}).get("output") if isinstance(result, dict) else None
        error = (result or {}).get("error") if isinstance(result, dict) else None
        if ok:
            try:
                await integrator.sync(SERVICE_ID, server_id)
            except Exception:
                pass
    except Exception as exc:
        ok, output, error = False, None, str(exc)
    await _edit(query, f"{'✅' if ok else '❌'} {output or error or 'Неизвестная ошибка'}", InlineKeyboardMarkup([
        [InlineKeyboardButton("← Назад", callback_data=_cb(back_op, server_id, src=src))],
    ]))


async def _direct_message(message, bot, server_id: str, method: str, params: dict, back_op: str, src: str | None) -> None:
    try:
        result = await integrator.call(SERVICE_ID, server_id, method, params)
        ok = bool(isinstance(result, dict) and result.get("success"))
        output = (result or {}).get("output") if isinstance(result, dict) else None
        error = (result or {}).get("error") if isinstance(result, dict) else None
        if ok:
            try:
                await integrator.sync(SERVICE_ID, server_id)
            except Exception:
                pass
    except Exception as exc:
        ok, output, error = False, None, str(exc)
    await message.reply_text(f"{'✅' if ok else '❌'} {output or error or 'Неизвестная ошибка'}", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("← Назад", callback_data=_cb(back_op, server_id, src=src))],
    ]))


async def _prompt(query, user_id: int, server_id: str, src: str | None, kind: str, text: str, back_op: str) -> None:
    XUI_TG_STATE[user_id] = {"kind": kind, "server": server_id, "src": src, "back_op": back_op}
    await _edit(query, text, InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data=_cb(back_op, server_id, src=src))],
    ]))


_INSTALL_TEXT_KINDS = frozenset({
    "install_username", "install_password", "install_port", "install_path",
    "install_domain", "install_ipv6", "install_custom_domain",
    "install_custom_cert", "install_custom_key",
})
_INSTALL_OPS = frozenset({
    "xui_i_access", "xui_i_edit", "xui_i_ssl", "xui_i_mode",
    "xui_i_ip_skip", "xui_i_bind", "xui_i_summary", "xui_i_confirm",
    "xui_i_cancel",
})


def _install_params() -> dict[str, Any]:
    password_alphabet = string.ascii_letters + string.digits + "_-"
    path_alphabet = string.ascii_letters + string.digits
    return {
        "username": "admin",
        "password": "".join(choice(password_alphabet) for _ in range(16)),
        "port": 10000 + randbelow(55000),
        "web_base_path": "".join(choice(path_alphabet) for _ in range(18)),
    }


def _install_state(user_id: int, server_id: str, *kinds: str) -> dict[str, Any] | None:
    state = XUI_TG_STATE.get(user_id)
    if (
        not state
        or state.get("flow") != "install"
        or state.get("server") != server_id
        or (kinds and state.get("kind") not in kinds)
    ):
        XUI_TG_STATE.pop(user_id, None)
        return None
    return state


async def _install_stale(query, server_id: str, src: str | None) -> None:
    await _edit(
        query,
        "⚠️ Мастер установки устарел. Откройте установку 3x-ui заново.",
        _back_card(server_id, src),
    )


async def _install_render(target, text: str, rows: list[list[InlineKeyboardButton]]) -> None:
    keyboard = InlineKeyboardMarkup(rows)
    if hasattr(target, "edit_message_text"):
        await _edit(target, text, keyboard)
    else:
        await target.reply_text(_trim(text), reply_markup=keyboard)


async def _install_access(target, state: dict[str, Any], *, reveal_password: bool = False) -> None:
    params = state["params"]
    server_id, src = state["server"], state.get("src")
    password_line = (
        f"🔑 Пароль: {params['password']}\n\n"
        "Сохраните пароль: после перехода дальше он не будет показан снова."
        if reveal_password else "🔑 Пароль: скрыт"
    )
    text = "\n".join([
        "🌐 Установка 3x-ui",
        "",
        "Данные доступа:",
        f"👤 Логин: {params['username']}",
        password_line,
        f"🔌 Порт: {params['port']}",
        f"🔗 Web base path: {params['web_base_path']}",
    ])
    rows = [
        [
            InlineKeyboardButton("👤 Логин", callback_data=_cb("xui_i_edit", server_id, "username", src)),
            InlineKeyboardButton("🔑 Пароль", callback_data=_cb("xui_i_edit", server_id, "password", src)),
        ],
        [
            InlineKeyboardButton("🔌 Порт", callback_data=_cb("xui_i_edit", server_id, "port", src)),
            InlineKeyboardButton("🔗 Web path", callback_data=_cb("xui_i_edit", server_id, "path", src)),
        ],
        [InlineKeyboardButton("➡️ Настроить SSL", callback_data=_cb("xui_i_ssl", server_id, src=src))],
        [InlineKeyboardButton("❌ Отмена", callback_data=_cb("xui_i_cancel", server_id, src=src))],
    ]
    await _install_render(target, text, rows)


async def _install_ssl_menu(target, state: dict[str, Any]) -> None:
    server_id, src = state["server"], state.get("src")
    await _install_render(target, "\n".join([
        "🔒 SSL для панели",
        "",
        "Выберите режим:",
        "• Домен — Let's Encrypt для домена",
        "• IP — короткоживущий Let's Encrypt сертификат",
        "• Свой — существующие сертификат и ключ",
        "• Без SSL — панель будет доступна по HTTP",
    ]), [
        [
            InlineKeyboardButton("🌐 Домен", callback_data=_cb("xui_i_mode", server_id, "domain", src)),
            InlineKeyboardButton("📍 IP", callback_data=_cb("xui_i_mode", server_id, "ip", src)),
        ],
        [
            InlineKeyboardButton("📄 Свой сертификат", callback_data=_cb("xui_i_mode", server_id, "custom", src)),
            InlineKeyboardButton("⚠️ Без SSL", callback_data=_cb("xui_i_mode", server_id, "none", src)),
        ],
        [InlineKeyboardButton("← Данные доступа", callback_data=_cb("xui_i_access", server_id, src=src))],
        [InlineKeyboardButton("❌ Отмена", callback_data=_cb("xui_i_cancel", server_id, src=src))],
    ])


async def _install_prompt(target, state: dict[str, Any], kind: str, text: str, back_op: str) -> None:
    state["kind"] = kind
    server_id, src = state["server"], state.get("src")
    await _install_render(target, text, [
        [InlineKeyboardButton("← Назад", callback_data=_cb(back_op, server_id, src=src))],
        [InlineKeyboardButton("❌ Отмена", callback_data=_cb("xui_i_cancel", server_id, src=src))],
    ])


async def _install_summary(target, state: dict[str, Any], error: str | None = None) -> None:
    state["kind"] = "install_summary"
    params = state["params"]
    mode = str(params.get("ssl_mode") or "")
    labels = {
        "domain": "Let's Encrypt для домена",
        "ip": "Let's Encrypt для IP",
        "custom": "Свой сертификат",
        "none": "Без SSL (HTTP)",
    }
    lines = [
        "📋 Установка 3x-ui",
        "",
        f"👤 Логин: {params['username']}",
        "🔑 Пароль: скрыт",
        f"🔌 Порт: {params['port']}",
        f"🔗 Web base path: {params['web_base_path']}",
        f"🔒 SSL: {labels.get(mode, 'не выбран')}",
    ]
    if mode in {"domain", "custom"}:
        lines.append(f"🌐 Домен: {params.get('domain') or '—'}")
    if mode == "ip" and params.get("ipv6"):
        lines.append(f"📍 IPv6: {params['ipv6']}")
    if mode == "custom":
        lines.extend((
            f"📄 Сертификат: {params.get('cert_file') or '—'}",
            f"🔑 Ключ: {params.get('key_file') or '—'}",
        ))
    if mode == "none":
        lines.append("🔒 Только localhost" if params.get("bind_local") else "🌐 Доступ извне по HTTP")
    if error:
        lines.extend(("", f"❌ {error}", "Исправьте параметры и повторите."))
    server_id, src = state["server"], state.get("src")
    await _install_render(target, "\n".join(lines), [
        [InlineKeyboardButton("🚀 Установить", callback_data=_cb("xui_i_confirm", server_id, src=src))],
        [
            InlineKeyboardButton("🔐 Доступ", callback_data=_cb("xui_i_access", server_id, src=src)),
            InlineKeyboardButton("🔒 SSL", callback_data=_cb("xui_i_ssl", server_id, src=src)),
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data=_cb("xui_i_cancel", server_id, src=src))],
    ])


async def _start_install_wizard(query, user_id: int, server_id: str, src: str | None) -> None:
    state = await _state(server_id)
    params = _install_params()
    if state.get("arch"):
        params["arch"] = str(state["arch"])
    wizard = {
        "flow": "install", "kind": "install_access", "server": server_id,
        "src": src, "params": params,
    }
    XUI_TG_STATE[user_id] = wizard
    await _install_access(query, wizard, reveal_password=True)


async def _handle_install_callback(ctx: CallbackCtx) -> bool:
    op, query, uid, server_id = ctx.op, ctx.query, ctx.user_id, ctx.server_id
    state = _install_state(uid, server_id)
    if not state:
        await _install_stale(query, server_id, ctx.src)
        return True
    src = state.get("src")
    params = state["params"]

    if op == "xui_i_cancel":
        XUI_TG_STATE.pop(uid, None)
        await _card(query, uid, server_id, src)
    elif op == "xui_i_access":
        state["kind"] = "install_access"
        await _install_access(query, state)
    elif op == "xui_i_ssl":
        state["kind"] = "install_ssl"
        await _install_ssl_menu(query, state)
    elif op == "xui_i_edit":
        prompts = {
            "username": ("install_username", "👤 Логин\n\nВведите логин панели."),
            "password": ("install_password", "🔑 Пароль\n\nВведите пароль панели."),
            "port": ("install_port", "🔌 Порт\n\nВведите порт панели."),
            "path": ("install_path", "🔗 Web base path\n\nВведите путь без адреса."),
        }
        prompt = prompts.get(ctx.name or "")
        if not prompt:
            XUI_TG_STATE.pop(uid, None)
            await _install_stale(query, server_id, src)
        else:
            await _install_prompt(query, state, *prompt, "xui_i_access")
    elif op == "xui_i_mode":
        mode = ctx.name or ""
        if state.get("kind") != "install_ssl" or mode not in {"domain", "ip", "custom", "none"}:
            XUI_TG_STATE.pop(uid, None)
            await _install_stale(query, server_id, src)
        else:
            for key in ("domain", "ipv6", "cert_file", "key_file", "bind_local"):
                params.pop(key, None)
            params["ssl_mode"] = mode
            if mode == "domain":
                await _install_prompt(query, state, "install_domain", "🌐 Домен\n\nВведите DNS-домен для Let's Encrypt.", "xui_i_ssl")
            elif mode == "ip":
                state["kind"] = "install_ipv6"
                await _install_render(query, "📍 IPv6\n\nВведите IPv6 для сертификата или пропустите этот шаг.", [
                    [InlineKeyboardButton("Пропустить", callback_data=_cb("xui_i_ip_skip", server_id, src=src))],
                    [InlineKeyboardButton("← SSL", callback_data=_cb("xui_i_ssl", server_id, src=src))],
                    [InlineKeyboardButton("❌ Отмена", callback_data=_cb("xui_i_cancel", server_id, src=src))],
                ])
            elif mode == "custom":
                await _install_prompt(query, state, "install_custom_domain", "🌐 Домен\n\nВведите домен сертификата.", "xui_i_ssl")
            else:
                state["kind"] = "install_none"
                await _install_render(query, "⚠️ Без SSL\n\nПанель будет доступна по HTTP. Выберите область доступа.", [
                    [
                        InlineKeyboardButton("🔒 Только localhost", callback_data=_cb("xui_i_bind", server_id, "local", src)),
                        InlineKeyboardButton("🌐 Доступ извне", callback_data=_cb("xui_i_bind", server_id, "public", src)),
                    ],
                    [InlineKeyboardButton("← SSL", callback_data=_cb("xui_i_ssl", server_id, src=src))],
                    [InlineKeyboardButton("❌ Отмена", callback_data=_cb("xui_i_cancel", server_id, src=src))],
                ])
    elif op == "xui_i_ip_skip":
        if state.get("kind") != "install_ipv6":
            XUI_TG_STATE.pop(uid, None)
            await _install_stale(query, server_id, src)
        else:
            params.pop("ipv6", None)
            await _install_summary(query, state)
    elif op == "xui_i_bind":
        if state.get("kind") != "install_none" or ctx.name not in {"local", "public"}:
            XUI_TG_STATE.pop(uid, None)
            await _install_stale(query, server_id, src)
        else:
            params["bind_local"] = ctx.name == "local"
            await _install_summary(query, state)
    elif op == "xui_i_summary":
        await _install_summary(query, state)
    elif op == "xui_i_confirm":
        if state.get("kind") != "install_summary":
            XUI_TG_STATE.pop(uid, None)
            await _install_stale(query, server_id, src)
        else:
            try:
                normalized = await integrator.call(
                    SERVICE_ID, server_id, "prepare_install_params", dict(params)
                )
            except Exception as exc:
                await _install_summary(query, state, str(exc))
            else:
                XUI_TG_STATE.pop(uid, None)
                await _enqueue_watch_query(
                    query, SERVICE_ID, server_id, "install", normalized, src=src
                )
    return True


class XuiUI(ServiceUI):
    service_id = SERVICE_ID
    claims_ops = {
        "view", "xui_install", "xui_service", "xui_account", "xui_cert", "xui_system", "xui_more", "xui_panel",
        "xui_auto_on", "xui_auto_off", "xui_start", "xui_stop", "xui_restart", "xui_logs", "xui_update", "xui_version",
        "xui_login", "xui_password", "xui_port", "xui_path", "xui_bbr_on", "xui_bbr_off", "xui_geo",
        "xui_cert_domain", "xui_cert_ip", "xui_cren", "xui_crem", "xui_db_export", "xui_db_import",
        "xui_fs_install", "xui_fs_remove", "xui_rm_confirm", "xui_rm_keep", "xui_rm_data",
        *_INSTALL_OPS,
    }

    def owns_message(self, user_id: int) -> bool:
        state = XUI_TG_STATE.get(user_id) or {}
        return state.get("kind") in _TEXT_KINDS | _INSTALL_TEXT_KINDS

    def owns_document(self, user_id: int) -> bool:
        return (XUI_TG_STATE.get(user_id) or {}).get("kind") == "db_import"

    async def handle_callback(self, ctx: CallbackCtx) -> bool:
        op, query, uid, server_id, src = ctx.op, ctx.query, ctx.user_id, ctx.server_id, ctx.src
        if op in _INSTALL_OPS:
            return await _handle_install_callback(ctx)
        if op not in _TOKEN_OPS:
            XUI_TG_STATE.pop(uid, None)

        if op == "view":
            await _card(query, uid, server_id, src)
        elif op == "xui_install":
            await _start_install_wizard(query, uid, server_id, src)
        elif op == "xui_service":
            await _service_menu(query, server_id, src)
        elif op == "xui_account":
            await _account_menu(query, server_id, src)
        elif op == "xui_cert":
            await _cert_menu(query, uid, server_id, src)
        elif op == "xui_system":
            await _system_menu(query, server_id, src)
        elif op == "xui_more":
            await _more_menu(query, server_id, src)
        elif op == "xui_panel":
            await _panel(query, server_id, src)
        elif op in {"xui_auto_on", "xui_auto_off"}:
            await _direct_query(query, server_id, "card_set_autostart", {"enabled": op == "xui_auto_on"}, "xui_service", src)
        elif op in {"xui_start", "xui_stop", "xui_restart"}:
            action = {"xui_start": "start", "xui_stop": "stop", "xui_restart": "restart"}[op]
            await _direct_query(query, server_id, "card_unit_action", {"action": action}, "xui_service", src)
        elif op == "xui_logs":
            try:
                logs = await integrator.call(SERVICE_ID, server_id, "fetch_logs", "x-ui", 200)
                text = f"📄 Логи 3x-ui\n\n{_trim(logs)}"
            except Exception as exc:
                text = f"❌ Не удалось получить логи:\n{exc}"
            await _edit(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data=_cb("xui_service", server_id, src=src))]]))
        elif op == "xui_update":
            await _enqueue_watch_query(query, SERVICE_ID, server_id, "update", {}, src=src)
        elif op == "xui_version":
            await _prompt(query, uid, server_id, src, "update_version", "🔢 Другая версия\n\nВведите тег версии, например: 3.8.0", "xui_service")
        elif op == "xui_login":
            await _prompt(query, uid, server_id, src, "account_username", "👤 Сменить логин\n\nВведите новый логин.", "xui_account")
        elif op == "xui_password":
            await _prompt(query, uid, server_id, src, "account_password", "🔑 Сменить пароль\n\nВведите новый пароль.", "xui_account")
        elif op == "xui_port":
            await _prompt(query, uid, server_id, src, "account_port", "🔌 Сменить порт\n\nВведите новый порт панели.", "xui_account")
        elif op == "xui_path":
            await _prompt(query, uid, server_id, src, "account_path", "🔗 Изменить web base path\n\nВведите новый путь без адреса. Пустое сообщение создаст случайный путь.", "xui_account")
        elif op in {"xui_bbr_on", "xui_bbr_off"}:
            await _direct_query(query, server_id, "card_set_bbr", {"enabled": op == "xui_bbr_on"}, "xui_system", src)
        elif op == "xui_geo":
            await _direct_query(query, server_id, "card_update_geo", {"restart": True}, "xui_system", src)
        elif op == "xui_cert_domain":
            await _prompt(query, uid, server_id, src, "cert_domain", "🔒 Выпустить Let's Encrypt\n\nВведите домен.", "xui_cert")
        elif op == "xui_cert_ip":
            await _prompt(query, uid, server_id, src, "cert_ip", "📍 Выпустить для IP\n\nВведите IPv4. IPv6 можно указать после запятой.", "xui_cert")
        elif op in _TOKEN_OPS:
            token = ctx.name or ""
            record = ((XUI_TG_STATE.get(uid) or {}).get("cert_tokens") or {}).get(token)
            XUI_TG_STATE.pop(uid, None)
            if not record:
                await _edit(query, "⚠️ Список сертификатов устарел. Откройте его заново.", _back_card(server_id, src))
            else:
                await _enqueue_watch_query(query, SERVICE_ID, server_id, "cert_renew" if op == "xui_cren" else "cert_remove", {"domain": record["domain"], "engine": record["engine"]}, src=src)
        elif op == "xui_db_export":
            try:
                result = await integrator.call(SERVICE_ID, server_id, "card_export_db", {}) or {}
                if not result.get("data"):
                    raise RuntimeError(result.get("error") or "Экспорт не создан")
                await query.message.reply_document(
                    document=InputFile(BytesIO(result["data"]), filename=result.get("filename") or "x-ui.db"),
                    caption="✅ Экспорт базы 3x-ui",
                )
                await _edit(query, "✅ Экспорт базы отправлен.", InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data=_cb("xui_more", server_id, src=src))]]))
            except Exception as exc:
                await _edit(query, f"❌ Не удалось экспортировать БД:\n{exc}", InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data=_cb("xui_more", server_id, src=src))]]))
        elif op == "xui_db_import":
            XUI_TG_STATE[uid] = {"kind": "db_import", "server": server_id, "src": src, "back_op": "xui_more"}
            await _edit(query, "📥 Импорт БД\n\nПришлите файл .db или .dump размером до 5 МиБ.", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=_cb("xui_more", server_id, src=src))]]))
        elif op == "xui_fs_install":
            await _prompt(query, uid, server_id, src, "fakesite_domain", "🌐 Сайт-заглушка (SelfSNI)\n\nВведите домен сайта-заглушки.", "xui_more")
        elif op == "xui_fs_remove":
            await _enqueue_watch_query(query, SERVICE_ID, server_id, "fakesite_remove", {}, src=src)
        elif op == "xui_rm_confirm":
            await _edit(query, "⚠️ Удалить 3x-ui?\n\nБез удаления данных каталог /etc/x-ui, база, инбаунды и пользователи сохранятся.", InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🗑 Удалить сервис", callback_data=_cb("xui_rm_keep", server_id, src=src)),
                    InlineKeyboardButton("🗑 Удалить всё", callback_data=_cb("xui_rm_data", server_id, src=src)),
                ],
                [InlineKeyboardButton("← Назад", callback_data=_cb("xui_more", server_id, src=src))],
            ]))
        elif op in {"xui_rm_keep", "xui_rm_data"}:
            await _enqueue_watch_query(query, SERVICE_ID, server_id, "remove", {"remove_data": op == "xui_rm_data"}, src=src)
        else:
            return False
        return True

    async def handle_message(self, ctx: MessageCtx) -> bool:
        state = XUI_TG_STATE.get(ctx.user_id)
        if state and state.get("flow") == "install" and state.get("kind") in _INSTALL_TEXT_KINDS:
            text = str(getattr(ctx.update.message, "text", "") or "")
            params = state["params"]
            kind = state["kind"]
            if kind == "install_username":
                params["username"] = text
                state["kind"] = "install_access"
                await _install_access(ctx.update.message, state)
            elif kind == "install_password":
                params["password"] = text
                state["kind"] = "install_access"
                await _install_access(ctx.update.message, state)
            elif kind == "install_port":
                params["port"] = text
                state["kind"] = "install_access"
                await _install_access(ctx.update.message, state)
            elif kind == "install_path":
                params["web_base_path"] = text
                state["kind"] = "install_access"
                await _install_access(ctx.update.message, state)
            elif kind == "install_domain":
                params["domain"] = text
                await _install_summary(ctx.update.message, state)
            elif kind == "install_ipv6":
                params["ipv6"] = text
                await _install_summary(ctx.update.message, state)
            elif kind == "install_custom_domain":
                params["domain"] = text
                await _install_prompt(
                    ctx.update.message, state, "install_custom_cert",
                    "📄 Сертификат\n\nВведите абсолютный путь к файлу сертификата.",
                    "xui_i_ssl",
                )
            elif kind == "install_custom_cert":
                params["cert_file"] = text
                await _install_prompt(
                    ctx.update.message, state, "install_custom_key",
                    "🔑 Ключ\n\nВведите абсолютный путь к файлу ключа.",
                    "xui_i_ssl",
                )
            elif kind == "install_custom_key":
                params["key_file"] = text
                await _install_summary(ctx.update.message, state)
            return True

        state = XUI_TG_STATE.pop(ctx.user_id, None)
        if not state or state.get("kind") not in _TEXT_KINDS:
            return False
        text = str(getattr(ctx.update.message, "text", "") or "").strip()
        server_id, src = state["server"], state.get("src")
        kind = state["kind"]
        if kind == "account_username":
            await _direct_message(ctx.update.message, ctx.context.bot, server_id, "card_change_username", {"username": text, "restart": True}, "xui_account", src)
        elif kind == "account_password":
            await _direct_message(ctx.update.message, ctx.context.bot, server_id, "card_change_password", {"password": text, "restart": True}, "xui_account", src)
        elif kind == "account_port":
            await _direct_message(ctx.update.message, ctx.context.bot, server_id, "card_change_port", {"port": text, "restart": True, "close_old_port": True}, "xui_account", src)
        elif kind == "account_path":
            await _direct_message(ctx.update.message, ctx.context.bot, server_id, "card_change_path", {"path": text, "restart": True}, "xui_account", src)
        elif kind == "update_version":
            await _enqueue_watch_message(ctx.update.message, ctx.context.bot, SERVICE_ID, server_id, "update", {"tag": text}, src=src)
        elif kind == "cert_domain":
            await _enqueue_watch_message(ctx.update.message, ctx.context.bot, SERVICE_ID, server_id, "cert_issue_domain", {"domain": text, "engine": "acme", "port": 80, "set_panel": True}, src=src)
        elif kind == "cert_ip":
            values = [value.strip() for value in text.split(",", 1)]
            params = {"ip": values[0], "port": 80, "set_panel": True}
            if len(values) == 2 and values[1]:
                params["ipv6"] = values[1]
            await _enqueue_watch_message(ctx.update.message, ctx.context.bot, SERVICE_ID, server_id, "cert_issue_ip", params, src=src)
        elif kind == "fakesite_domain":
            await _enqueue_watch_message(ctx.update.message, ctx.context.bot, SERVICE_ID, server_id, "fakesite_install", {"domain": text}, src=src)
        return True

    async def handle_document(self, ctx: DocumentCtx) -> bool:
        state = XUI_TG_STATE.pop(ctx.user_id, None)
        if not state or state.get("kind") != "db_import":
            return False
        filename = str(ctx.filename or "")
        suffix = Path(filename).suffix.lower()
        data = ctx.data or b""
        if suffix not in {".db", ".dump"}:
            await ctx.update.message.reply_text("❌ Нужен файл .db или .dump.")
            return True
        if not data:
            await ctx.update.message.reply_text("❌ Файл пуст.")
            return True
        if len(data) > _MAX_DB_IMPORT_SIZE:
            await ctx.update.message.reply_text("❌ Файл больше 5 МиБ.")
            return True

        tmp_dir = Path.cwd() / "data" / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        local_path = tmp_dir / f"xui-db-import-{token_hex(16)}{suffix}"
        try:
            local_path.write_bytes(data)
            task = await _enqueue_watch_message(
                ctx.update.message, ctx.context.bot, SERVICE_ID, state["server"], "db_import",
                {"local_path": str(local_path)}, src=state.get("src"),
            )
            if task is None:
                local_path.unlink(missing_ok=True)
        except Exception as exc:
            local_path.unlink(missing_ok=True)
            await ctx.update.message.reply_text(f"❌ Не удалось подготовить импорт: {exc}")
        return True


register_service_ui(XuiUI())
