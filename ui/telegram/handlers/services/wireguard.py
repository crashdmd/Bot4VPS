# -*- coding: utf-8 -*-
"""WireGuard-специфичный Telegram-UI.

Вся презентация WireGuard (богатая карточка сервиса с Endpoint/миграцией,
карточки/списки профилей, скачивание .conf, QR, настройки Endpoint, миграция,
quick-actions над профилями, текстовые flow добавления/переименования/endpoint)
живёт здесь. Тонкий диспетчер `service_handlers.py` ничего не знает о WireGuard —
он делегирует заявленные op в `WireGuardUI` через реестр.

Telegram-привязки (InlineKeyboard, edit_message_text, reply_document/reply_photo,
серверная state-машина текстового ввода) — сознательно Telegram-специфичны.
Бизнес-логика и данные остаются в `services/wireguard/` + `core.integrator`; этот
модуль — только отображение и маршрутизация нажатий. Web UI будет отдельным слоем
над тем же интегратором (не здесь).

Контракт: `core.integrator.call(...)` для quick-ops и данных, `enqueue(...)` — для
тяжёлых (migrate). Изменение конфигурации (Endpoint/Порт/Адрес/DNS) — через единый
`integrator.call("update_config", ...)` (частичный patch); статистика профилей — из
обогащённого кэша сервиса (connected/handshake/rx/tx/public_key/allowed_ips).
"""
from __future__ import annotations

import io
import ipaddress
import re
from io import BytesIO

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile

from core import integrator
from core.integrator import get_manifest
from core.storage import find_server
from state import SVC_PROFILE_ADD_STATE

from .base import CallbackCtx, MessageCtx, ServiceUI, register_service_ui
from ._shared import (
    _back_from_service,
    _enqueue_watch_message,
    _enqueue_watch_query,
    _extract_version,
    _fmt_bytes,
    _format_synced_at,
    _map_systemd_state,
    _noop_progress,
    _show_install_menu,
    _svc_cb,
)


def _is_private_host(host: str) -> bool:
    h = (host or "").strip()
    if not h:
        return True
    try:
        return ipaddress.ip_address(h).is_private
    except ValueError:
        return False


def _short_key(pub: str) -> str:
    """Сокращённый публичный ключ для карточки TG (иначе 44 символа base64
    удлиняют сообщение): «abc12345…wxyz»."""
    pub = (pub or "").strip()
    if len(pub) <= 16:
        return pub or "—"
    return f"{pub[:8]}…{pub[-4:]}"


class WireGuardUI(ServiceUI):
    """Telegram-отображение сервиса WireGuard."""

    service_id = "wireguard"
    claims_ops = {
        "view", "profiles", "settings", "info", "qr", "install",
        "add", "add_cancel", "item", "item_refresh", "toggle", "download",
        "reissue", "reissue_run", "rename", "confirm_delprofile", "delprofile",
        "reissue_all", "reissue_all_run",
        "ep_ip", "ep_domain", "ep_skip",
        "set_endpoint", "set_ep_ip", "set_ep_domain", "set_ep_clear",
        "config", "cfg_port", "cfg_address", "cfg_dns",
        "confirm_migrate", "migrate", "migrate_reissue",
        "migrate_use_ep", "migrate_other_ip", "migrate_other_domain", "migrate_no_ep",
    }

    # ----------------------------------------------------------
    # Данные и карточки профилей
    # ----------------------------------------------------------

    async def _get_profile_data(self, server_id, name):
        manifest = get_manifest(self.service_id)
        try:
            profiles = await integrator.call(self.service_id, server_id, "get_profiles") or []
        except Exception:
            profiles = []
        prof = next((p for p in profiles if p.get("name") == name), None)
        enabled = bool(prof.get("enabled", True)) if prof else True
        managed = bool(prof.get("managed", True)) if prof else True
        return manifest, prof, enabled, managed

    def _build_profile_text(self, manifest, prof):
        """Карточка профиля со статистикой из единого сервисного источника (ТЗ §20):
        connected/disconnected (по handshake), последний handshake, публичный ключ,
        внутренний IP (все AllowedIPs), RX/TX. Сервис отдаёт сырые байты — форматит UI."""
        name = (prof or {}).get("name", "?")
        enabled = bool((prof or {}).get("enabled", True))
        managed = bool((prof or {}).get("managed", True))
        connected = bool((prof or {}).get("connected"))
        prof = prof or {}

        if managed:
            icon = (manifest.icon + " ") if manifest and manifest.icon else ""
            svc = manifest.name if manifest else ""
            lines = [f"{icon}{svc}", f"👤 Профиль: {name}"]
        else:
            lines = [f"📦 {name}", "📦 Тип: импортированный"]

        if not enabled:
            lines.append("Статус: ⚪ Выключен")
        else:
            lines.append("Статус: 🟢 Подключён" if connected else "Статус: 🟡 Не подключён")
            lines.append(f"Последний handshake: {prof.get('last_handshake') or 'никогда'}")

        pub = prof.get("public_key")
        if pub:
            lines.append(f"Публичный ключ: {_short_key(pub)}")
        aip = prof.get("allowed_ips") or []
        if aip:
            lines.append(f"Внутренний IP: {', '.join(aip)}")
        if enabled:
            lines.append(f"↓ Получено: {_fmt_bytes(prof.get('rx_bytes', 0))}")
            lines.append(f"↑ Отправлено: {_fmt_bytes(prof.get('tx_bytes', 0))}")
        return "\n".join(lines)

    def _build_profile_rows(self, server_id, name, src, enabled, managed):
        """Клавиатура профиля.

        managed:
          🔄 Обновить | 🟢/⏸
          📱 QR       | ⬇️ Скачать
          ✏️ Переименовать | 🗑 Удалить
          ⬅️ Назад

        imported:
          🔄 Обновить | ♻️ Перевыпустить
          🟢/⏸       | ✏️ Переименовать
          ℹ️ Инфо
          🗑 Удалить
          ⬅️ Назад
        """
        toggle_label = "🟢 Включить" if not enabled else "⏸ Отключить"
        sid = self.service_id
        rows = []
        if managed:
            rows.append([
                InlineKeyboardButton("🔄 Обновить", callback_data=_svc_cb("item_refresh", sid, server_id, name, src=src)),
                InlineKeyboardButton(toggle_label, callback_data=_svc_cb("toggle", sid, server_id, name, src=src)),
            ])
            rows.append([
                InlineKeyboardButton("📱 QR", callback_data=_svc_cb("qr", sid, server_id, name, src=src)),
                InlineKeyboardButton("⬇️ Скачать", callback_data=_svc_cb("download", sid, server_id, name, src=src)),
            ])
            rows.append([
                InlineKeyboardButton("✏️ Переименовать", callback_data=_svc_cb("rename", sid, server_id, name, src=src)),
                InlineKeyboardButton("🗑 Удалить", callback_data=_svc_cb("confirm_delprofile", sid, server_id, name, src=src)),
            ])
        else:
            rows.append([
                InlineKeyboardButton("🔄 Обновить", callback_data=_svc_cb("item_refresh", sid, server_id, name, src=src)),
                InlineKeyboardButton("♻️ Перевыпустить", callback_data=_svc_cb("reissue", sid, server_id, name, src=src)),
            ])
            rows.append([
                InlineKeyboardButton(toggle_label, callback_data=_svc_cb("toggle", sid, server_id, name, src=src)),
                InlineKeyboardButton("✏️ Переименовать", callback_data=_svc_cb("rename", sid, server_id, name, src=src)),
            ])
            rows.append([
                InlineKeyboardButton("ℹ️ Инфо", callback_data=_svc_cb("info", sid, server_id, name, src=src)),
            ])
            rows.append([
                InlineKeyboardButton("🗑 Удалить", callback_data=_svc_cb("confirm_delprofile", sid, server_id, name, src=src)),
            ])
        rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("profiles", sid, server_id, src=src))])
        return rows


    async def _profile_card(self, query, server_id: str, name: str, src=None):
        manifest, prof, enabled, managed = await self._get_profile_data(server_id, name)
        text = self._build_profile_text(manifest, prof)
        rows = self._build_profile_rows(server_id, name, src, enabled, managed)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))

    async def _send_profile_card_message(self, message, server_id: str, name: str, src=None):
        manifest, prof, enabled, managed = await self._get_profile_data(server_id, name)
        text = self._build_profile_text(manifest, prof)
        rows = self._build_profile_rows(server_id, name, src, enabled, managed)
        await message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))

    async def _profile_info(self, query, server_id: str, name: str, src=None):
        text = (
            "ℹ️ Импортированный профиль\n\n"
            "Этот профиль был обнаружен во время\n"
            "миграции существующей конфигурации\n"
            "WireGuard.\n\n"
            "Bot4VPS знает параметры подключения\n"
            "этого клиента (публичный ключ, IP-адрес\n"
            "и другие настройки), однако приватный\n"
            "ключ клиента отсутствует и восстановить\n"
            "его невозможно.\n\n"
            "Поэтому для импортированных профилей\n"
            "недоступны:\n"
            "❌ Скачать конфигурацию\n"
            "❌ Показать QR-код\n\n"
            "При необходимости профиль можно\n"
            "перевыпустить.\n\n"
            "Будет создана новая пара ключей клиента,\n"
            "после чего профиль станет полностью\n"
            "управляемым Bot4VPS.\n\n"
            "После перевыпуска станут доступны:\n"
            "✅ Скачать конфигурацию\n"
            "✅ QR-код\n"
            "✅ Полное управление профилем"
        )
        rows = [
            [InlineKeyboardButton("♻️ Перевыпустить", callback_data=_svc_cb("reissue", self.service_id, server_id, name, src=src))],
            [InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("item", self.service_id, server_id, name, src=src))]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))

    async def _profiles_list(self, query, server_id: str, src=None):
        try:
            profiles = await integrator.call(self.service_id, server_id, "get_profiles") or []
        except Exception:
            profiles = []

        unmanaged = [p for p in profiles if not p.get("managed", True)]
        rows = []
        for p in profiles:
            pname = p.get("name", "?")
            enabled = p.get("enabled", True)
            managed = p.get("managed", True)
            mark = "📦 " + pname if not managed else ("✅ " if enabled else "⚪ ") + pname
            rows.append([InlineKeyboardButton(mark, callback_data=_svc_cb("item", self.service_id, server_id, pname, src=src))])

        if unmanaged:
            rows.append([InlineKeyboardButton("♻️ Перевыпустить все импортированные", callback_data=_svc_cb("reissue_all", self.service_id, server_id, src=src))])
        rows.append([InlineKeyboardButton("➕ Добавить профиль", callback_data=_svc_cb("add", self.service_id, server_id, src=src))])
        rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("view", self.service_id, server_id, src=src))])
        text = "👥 Профили WireGuard\n\nВыберите профиль:"
        if unmanaged:
            text += f"\n\n⚠️ Импортированных профилей без перевыпуска: {len(unmanaged)}. Скачивание и QR им недоступны."
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))

    # ----------------------------------------------------------
    # Карточка сервиса (богатая: Endpoint / миграция / версия)
    # ----------------------------------------------------------

    async def _card(self, query, server_id: str, src=None):
        service_id = self.service_id
        manifest = get_manifest(service_id)
        if not manifest:
            await query.edit_message_text("❌ Сервис не найден.")
            return
        server = find_server(server_id)
        server_name = server["name"] if server else server_id

        try:
            status = await integrator.call(service_id, server_id, "get_status") or {}
        except Exception as e:
            status = {}
            await query.message.reply_text(f"⚠️ Не удалось получить статус: {e}")

        try:
            profiles = await integrator.call(service_id, server_id, "get_profiles") or []
        except Exception:
            profiles = []

        installed = bool(status.get("installed"))
        synced_at = _format_synced_at(status.get("synced_at"))
        icon = manifest.icon or "🛠"
        desc = (manifest.extra or {}).get("description") or ""

        lines = [f"{icon} {manifest.name}", f"🖥 {server_name}"]
        if desc:
            lines.append(desc)
        lines.append("")
        if installed:
            lines.append("✅ Статус: установлен")
            if status.get("version"):
                lines.append(f"📦 Версия: {_extract_version(status['version'])}")
            if status.get("active"):
                emoji, state_text = _map_systemd_state(status['active'])
                lines.append(f"{emoji} Состояние: {state_text}")
            if status.get("needs_migration"):
                lines.append("")
                lines.append("⚠️ Обнаружена классическая конфигурация WireGuard.")
                n = int(status.get("classic_peer_count") or 0)
                if n:
                    lines.append(f"Peer’ов в wg0.conf: {n}")
                lines.append("Для полного управления через Bot4VPS")
                lines.append("конфигурацию можно перевести в новый формат.")
            else:
                ep = (status.get("endpoint") or "").strip()
                lines.append("🌍 Endpoint")
                lines.append(ep if ep else "не настроен")
        else:
            lines.append("⚪ Статус: не установлен")

        if synced_at != "—":
            lines.append(f"🕒 Синхронизация: {synced_at}")
        else:
            lines.append("🕒 Синхронизация: ещё не было")

        text = "\n".join(lines)

        try:
            menu = await integrator.call(service_id, server_id, "get_actions") or []
        except Exception as e:
            menu = []
            await query.message.reply_text(f"⚠️ Меню: {e}")

        menu_ops = {}
        if menu:
            if hasattr(menu[0], "id"):
                menu_ops = {item.id: item.label for item in menu}
            else:
                menu_ops = {item.get("id"): item.get("label", "") for item in menu}

        rows = []
        if installed and not status.get("needs_migration"):
            rows.append([InlineKeyboardButton(f"👥 Профили ({len(profiles)})", callback_data=_svc_cb("profiles", service_id, server_id, src=src))])
            if "sync" in menu_ops:
                rows.append([InlineKeyboardButton(menu_ops["sync"], callback_data=_svc_cb("sync", service_id, server_id, src=src))])
            rows.append([InlineKeyboardButton("⚙️ Настройки", callback_data=_svc_cb("settings", service_id, server_id, src=src))])
        else:
            for op_id, label in menu_ops.items():
                if op_id:
                    rows.append([InlineKeyboardButton(label, callback_data=_svc_cb(op_id, service_id, server_id, src=src))])

        rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=_back_from_service(service_id, server_id, src))])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))

    async def _settings_menu(self, query, server_id: str, src=None):
        text = "⚙️ Настройки сервиса"
        rows = [
            [InlineKeyboardButton("⚙️ Изменить конфигурацию", callback_data=_svc_cb("config", self.service_id, server_id, src=src))],
            [InlineKeyboardButton("🗑 Удалить сервис", callback_data=_svc_cb("confirm_remove", self.service_id, server_id, src=src))],
            [InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("view", self.service_id, server_id, src=src))]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))

    async def _config_menu(self, target, server_id: str, src=None, notice=None):
        """Меню «Изменить конфигурацию»: Endpoint / Порт / Адрес / DNS (ТЗ §14).
        Универсально для query и message. Каждый пункт → единый update_config."""
        status = {}
        try:
            status = await integrator.call(self.service_id, server_id, "get_status") or {}
        except Exception:
            pass
        addr = status.get("address") or "—"
        port = status.get("port") if status.get("port") is not None else "—"
        ep = (status.get("endpoint") or "").strip() or "не настроен"
        dns = status.get("dns") or "—"
        body = (
            f"📍 Адрес: {addr}\n"
            f"🔌 Порт: {port}\n"
            f"🌍 Endpoint: {ep}\n"
            f"🌐 DNS: {dns}\n"
        )
        text = (f"{notice}\n\n" if notice else "") + "⚙️ Изменить конфигурацию\n\n" + body
        sid = self.service_id
        rows = [
            [InlineKeyboardButton("🌍 Endpoint", callback_data=_svc_cb("set_endpoint", sid, server_id, src=src)),
             InlineKeyboardButton("🔌 Порт", callback_data=_svc_cb("cfg_port", sid, server_id, src=src))],
            [InlineKeyboardButton("📍 Адрес", callback_data=_svc_cb("cfg_address", sid, server_id, src=src)),
             InlineKeyboardButton("🌐 DNS", callback_data=_svc_cb("cfg_dns", sid, server_id, src=src))],
            [InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("settings", sid, server_id, src=src))],
        ]
        kb = InlineKeyboardMarkup(rows)
        if hasattr(target, "edit_message_text"):
            try:
                await target.edit_message_text(text, reply_markup=kb)
            except Exception:
                await target.message.reply_text(text, reply_markup=kb)
        else:
            await target.reply_text(text, reply_markup=kb)

    async def _config_update_and_show(self, target, sid, srv, *, endpoint=None, port=None, address=None, dns=None, src=None):
        """Частичное применение конфигурации через единый update_config + sync
        (ТЗ §14/§17). None = пропустить; для endpoint "" = сброс. После — в меню."""
        try:
            await integrator.call(sid, srv, "update_config", endpoint, port, address, dns)
        except Exception as e:
            await self._config_menu(target, srv, src=src, notice=f"❌ {e}")
            return
        try:
            await integrator.sync(sid, srv)
        except Exception as e:
            print(f"[SYNC ERROR] after config update: {e}")
        notice = "✅ Конфигурация обновлена"
        if port is not None or address is not None:
            notice += "\n⚠️ Интерфейс перезапущен — активные подключения кратко прервались."
        await self._config_menu(target, srv, src=src, notice=notice)

    async def _endpoint_prompt(self, query, server_id: str, src, host: str):
        text = (
            "⚠️ Обнаружен локальный IP-адрес сервера.\n\n"
            f"Основной адрес сервера:\n{host}\n\n"
            "Для подключения из Интернета необходим внешний IP-адрес или доменное имя.\n\n"
            "Что использовать в конфигурациях клиентов?"
        )
        rows = [
            [InlineKeyboardButton("🌐 Использовать внешний IP", callback_data=_svc_cb("ep_ip", self.service_id, server_id, src=src))],
            [InlineKeyboardButton("🌍 Использовать домен", callback_data=_svc_cb("ep_domain", self.service_id, server_id, src=src))],
            [InlineKeyboardButton("⏭ Настрою позже", callback_data=_svc_cb("ep_skip", self.service_id, server_id, src=src))],
            [InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("view", self.service_id, server_id, src=src))],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))

    # ----------------------------------------------------------
    # Скачивание .conf / QR
    # ----------------------------------------------------------

    async def _profile_download(self, query, server_id: str, name: str, src=None):
        try:
            st = await integrator.call(self.service_id, server_id, "get_status") or {}
            if st.get("needs_migration"):
                await query.answer()
                await query.message.reply_text("⚠️ Сначала выполните миграцию конфигурации.\nСкачивание профилей доступно только в формате Bot4VPS.")
                return
        except Exception:
            pass
        await query.answer("Скачивание…")
        try:
            data = await integrator.call(self.service_id, server_id, "fetch_profile_config", name)
        except Exception as e:
            try:
                await query.message.reply_text(f"❌ Не удалось получить конфиг:\n{e}")
            except Exception:
                pass
            return
        if not data:
            try:
                await query.message.reply_text("❌ Конфиг пуст.")
            except Exception:
                pass
            return

        caption = f"📄 {name}.conf — приватный ключ храните в секрете"
        try:
            st = await integrator.call(self.service_id, server_id, "get_status") or {}
            if not (st.get("endpoint") or "").strip():
                caption += "\n\n⚠️ Endpoint отсутствует.\nПеред использованием укажите внешний IP или домен."
        except Exception:
            pass
        await query.message.reply_document(document=InputFile(BytesIO(data), filename=f"{name}.conf"), caption=caption)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад к профилю", callback_data=_svc_cb("item", self.service_id, server_id, name, src=src))],
            [InlineKeyboardButton("⬅️ К сервису", callback_data=_svc_cb("view", self.service_id, server_id, src=src))],
        ])
        await query.message.reply_text(f"✅ Профиль «{name}» готов.", reply_markup=kb)

    async def _profile_qr(self, query, server_id: str, name: str, src=None):
        """Генерация и отправка QR-кода для конфига клиента."""
        try:
            import qrcode
        except ImportError:
            print("[QR ERROR] Библиотека qrcode не установлена. Выполните: /opt/bot4vps/venv/bin/pip install 'qrcode[pil]'")
            await query.answer()
            await query.message.reply_text("❌ На сервере бота не установлена библиотека для генерации QR-кодов. Обратитесь к администратору.")
            return

        try:
            st = await integrator.call(self.service_id, server_id, "get_status") or {}
            if st.get("needs_migration"):
                await query.answer()
                await query.message.reply_text("⚠️ Сначала выполните миграцию конфигурации.\nQR-коды доступны только для профилей в формате Bot4VPS.")
                return
        except Exception:
            pass

        await query.answer("Генерация QR-кода…")

        try:
            data = await integrator.call(self.service_id, server_id, "fetch_profile_config", name)
        except Exception as e:
            await query.message.reply_text(f"❌ Не удалось получить конфиг:\n{e}")
            return

        if not data:
            await query.message.reply_text("❌ Конфиг пуст.")
            return

        try:
            config_text = data.decode("utf-8")
        except UnicodeDecodeError:
            print(f"[QR ERROR] Не удалось декодировать конфиг профиля {name} (недопустимые байты)")
            await query.message.reply_text("❌ Ошибка: конфигурационный файл содержит недопустимые символы.")
            return

        try:
            img = qrcode.make(config_text)
            bio = io.BytesIO()
            bio.name = f"{name}_qr.png"
            img.save(bio, "PNG")
            bio.seek(0)
        except Exception as e:
            print(f"[QR ERROR] Ошибка генерации QR-кода: {e}")
            await query.message.reply_text("❌ Произошла ошибка при генерации QR-кода. Подробности в логах бота.")
            return

        caption = f"📱 QR-код для профиля «{name}»\n\nОтсканируйте его в приложении WireGuard на мобильном устройстве."
        try:
            st = await integrator.call(self.service_id, server_id, "get_status") or {}
            if not (st.get("endpoint") or "").strip():
                caption += "\n\n⚠️ Endpoint отсутствует.\nПеред использованием укажите внешний IP или домен."
        except Exception:
            pass

        await query.message.reply_photo(photo=bio, caption=caption)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад к профилю", callback_data=_svc_cb("item", self.service_id, server_id, name, src=src))],
        ])
        await query.message.reply_text("✅ QR-код готов.", reply_markup=kb)

    # ----------------------------------------------------------
    # Quick-actions над профилями (тривиальные, без очереди)
    # ----------------------------------------------------------

    async def _exec_quick_action(self, query, server_id, action, params, src=None, profile_name=None, redirect_to="profile"):
        """Прямой вызов метода сервиса (do_*) и мгновенный возврат в карточку."""
        await query.edit_message_text("⏳ Выполняю...")
        try:
            result = await integrator.call(self.service_id, server_id, f"do_{action}", params, _noop_progress)
            if not result or not result.success:
                err = result.error if result else "Неизвестная ошибка"
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("item", self.service_id, server_id, profile_name, src=src))]])
                await query.message.reply_text(f"❌ Ошибка: {err}", reply_markup=kb)
                return
        except Exception as e:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("item", self.service_id, server_id, profile_name, src=src))]])
            await query.message.reply_text(f"❌ Ошибка: {e}", reply_markup=kb)
            return

        try:
            await integrator.sync(self.service_id, server_id)
        except Exception as e:
            print(f"[SYNC ERROR] after quick action: {e}")

        if redirect_to == "profiles":
            await self._profiles_list(query, server_id, src=src)
        else:
            name = profile_name or params.get("new_name") or params.get("name")
            if name:
                await self._profile_card(query, server_id, name, src=src)
            else:
                await self._card(query, server_id, src=src)

    async def _exec_quick_action_message(self, message, bot, server_id, action, params, src=None, old_name=None):
        msg = await message.reply_text("⏳ Выполняю...")
        try:
            result = await integrator.call(self.service_id, server_id, f"do_{action}", params, _noop_progress)
            if not result or not result.success:
                err = result.error if result else "Неизвестная ошибка"
                name_to_redirect = old_name or params.get("name")
                if name_to_redirect:
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад к профилю", callback_data=_svc_cb("item", self.service_id, server_id, name_to_redirect, src=src))]])
                else:
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("view", self.service_id, server_id, src=src))]])
                await message.reply_text(f"❌ Ошибка: {err}", reply_markup=kb)
                return
        except Exception as e:
            name_to_redirect = old_name or params.get("name")
            if name_to_redirect:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад к профилю", callback_data=_svc_cb("item", self.service_id, server_id, name_to_redirect, src=src))]])
            else:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("view", self.service_id, server_id, src=src))]])
            await message.reply_text(f"❌ Ошибка: {e}", reply_markup=kb)
            return

        try:
            await integrator.sync(self.service_id, server_id)
        except Exception as e:
            print(f"[SYNC ERROR] after quick action msg: {e}")

        name = params.get("new_name") or params.get("name")
        if name:
            await self._send_profile_card_message(message, server_id, name, src=src)
        else:
            await message.reply_text("✅ Действие выполнено.")

    # ----------------------------------------------------------
    # Маршрутизация callback'ов (только WG-специфичные op)
    # ----------------------------------------------------------

    async def _migrate_reissue_menu(self, target, sid, srv, src):
        """Экран «Перевыпустить всех клиентов после миграции?».
        Универсален для query (edit_message_text) и message (reply_text) —
        финальная точка после выбора/ввода endpoint."""
        status = {}
        try:
            status = await integrator.call(sid, srv, "get_status") or {}
        except Exception:
            pass
        ep = (status.get("endpoint") or "").strip() or "не задан"
        text = (
            f"Endpoint: {ep}\n\n"
            "Перевыпустить всех клиентов после миграции?\n\n"
            "✅ Да — миграция + перевыпуск всех профилей (новые ключи, IP сохранятся).\n"
            "▢ Нет — только миграция (импортированные профили без ключей; перевыпустите позже)."
        )
        rows = [
            [InlineKeyboardButton("✅ Да, миграция + перевыпуск всех", callback_data=_svc_cb("migrate_reissue", sid, srv, src=src))],
            [InlineKeyboardButton("▢ Нет, только миграция", callback_data=_svc_cb("migrate", sid, srv, src=src))],
            [InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("view", sid, srv, src=src))],
        ]
        kb = InlineKeyboardMarkup(rows)
        if hasattr(target, "edit_message_text"):
            try:
                await target.edit_message_text(text, reply_markup=kb)
            except Exception:
                await target.message.reply_text(text, reply_markup=kb)
        else:
            await target.reply_text(text, reply_markup=kb)

    async def handle_callback(self, ctx: CallbackCtx) -> bool:
        q = ctx.query
        op = ctx.op
        srv = ctx.server_id
        name = ctx.name
        src = ctx.src
        uid = ctx.user_id
        sid = self.service_id

        if op == "view":
            await self._card(q, srv, src=src)
        elif op == "profiles":
            await self._profiles_list(q, srv, src=src)
        elif op == "settings":
            await self._settings_menu(q, srv, src=src)
        elif op == "config":
            await self._config_menu(q, srv, src=src)
        elif op == "cfg_port":
            SVC_PROFILE_ADD_STATE[uid] = {"_kind": "cfg_port", "service": sid, "server": srv, "src": src}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("config", sid, srv, src=src))]])
            await q.edit_message_text("Введите порт (1–65535):", reply_markup=kb)
        elif op == "cfg_address":
            SVC_PROFILE_ADD_STATE[uid] = {"_kind": "cfg_addr", "service": sid, "server": srv, "src": src}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("config", sid, srv, src=src))]])
            await q.edit_message_text("Введите адрес подсети (CIDR), напр. 10.8.0.1/24:", reply_markup=kb)
        elif op == "cfg_dns":
            SVC_PROFILE_ADD_STATE[uid] = {"_kind": "cfg_dns", "service": sid, "server": srv, "src": src}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("config", sid, srv, src=src))]])
            await q.edit_message_text("Введите DNS (напр. 1.1.1.1, через запятую):", reply_markup=kb)
        elif op == "info":
            await self._profile_info(q, srv, name or "", src=src)
        elif op == "qr":
            await self._profile_qr(q, srv, name or "", src=src)
        elif op == "install":
            server = find_server(srv)
            host = (server or {}).get("host", "") if server else ""
            if _is_private_host(host):
                await self._endpoint_prompt(q, srv, src, host)
            else:
                await _show_install_menu(q, uid, sid, srv, src, {"WG_ENDPOINT": host})
        elif op == "add":
            SVC_PROFILE_ADD_STATE[uid] = {"service": sid, "server": srv, "src": src}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("add_cancel", sid, srv, src=src))]])
            await q.message.reply_text(
                "Введите имя нового профиля:\n\n"
                "⚠️ Имя должно начинаться с буквы или цифры и может содержать латинские буквы, цифры, дефис (-) и подчеркивание (_).\n"
                "Длина: от 1 до 31 символа.",
                reply_markup=kb
            )
        elif op == "add_cancel":
            SVC_PROFILE_ADD_STATE.pop(uid, None)
            await self._profiles_list(q, srv, src=src)
        elif op == "item":
            await self._profile_card(q, srv, name or "", src=src)
        elif op == "item_refresh":
            # sync → актуальный кэш → карточка профиля (в т.ч. импортированные)
            try:
                await integrator.sync(self.service_id, srv)
                try:
                    await query.answer("Обновлено")
                except Exception:
                    pass
            except Exception as e:
                try:
                    await query.answer(str(e)[:180], show_alert=True)
                except Exception:
                    pass
            await self._profile_card(q, srv, name or "", src=src)
        elif op == "toggle":
            manifest, prof, enabled, managed = await self._get_profile_data(srv, name or "")
            await self._exec_quick_action(q, srv, "toggle_profile", {"name": name, "enabled": not enabled}, src=src, profile_name=name)
        elif op == "download":
            await self._profile_download(q, srv, name or "", src=src)
        elif op == "reissue":
            text = (
                "⚠️ Вы собираетесь перевыпустить ключи для этого профиля.\n\n"
                "Старый конфиг на устройстве клиента перестанет работать.\n"
                "IP-адрес останется прежним.\n\n"
                "Продолжить?"
            )
            rows = [
                [InlineKeyboardButton("✅ Да, перевыпустить", callback_data=_svc_cb("reissue_run", sid, srv, name, src=src))],
                [InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("item", sid, srv, name, src=src))],
            ]
            await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))
        elif op == "reissue_run":
            await self._exec_quick_action(q, srv, "reissue_profile", {"name": name}, src=src, profile_name=name)
        elif op == "rename":
            SVC_PROFILE_ADD_STATE[uid] = {
                "_kind": "rename_profile",
                "service": sid,
                "server": srv,
                "src": src,
                "name": name
            }
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("item", sid, srv, name, src=src))]])
            await q.message.reply_text(
                f"Текущее имя: {name}\n\nВведите новое имя профиля (латинские буквы, цифры, -, _):",
                reply_markup=kb
            )
        elif op == "confirm_delprofile":
            text = f"⚠️ Удалить профиль «{name}»?"
            rows = [
                [InlineKeyboardButton("✅ Да", callback_data=_svc_cb("delprofile", sid, srv, name, src=src))],
                [InlineKeyboardButton("❌ Нет", callback_data=_svc_cb("item", sid, srv, name, src=src))],
            ]
            await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))
        elif op == "delprofile":
            await self._exec_quick_action(q, srv, "remove_profile", {"name": name}, src=src, redirect_to="profiles")
        elif op == "ep_ip":
            SVC_PROFILE_ADD_STATE[uid] = {"_kind": "endpoint_ip", "service": sid, "server": srv, "src": src}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("view", sid, srv, src=src))]])
            await q.edit_message_text("Введите внешний IP-адрес сервера.\nНапример:\n\n203.0.113.15", reply_markup=kb)
        elif op == "ep_domain":
            SVC_PROFILE_ADD_STATE[uid] = {"_kind": "endpoint_domain", "service": sid, "server": srv, "src": src}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("view", sid, srv, src=src))]])
            await q.edit_message_text("Введите доменное имя.\nНапример:\n\nvpn.example.com", reply_markup=kb)
        elif op == "ep_skip":
            await _show_install_menu(q, uid, sid, srv, src, {"WG_ENDPOINT": ""})
        elif op == "set_endpoint":
            status = {}
            try:
                status = await integrator.call(sid, srv, "get_status") or {}
            except Exception:
                pass
            cur = (status.get("endpoint") or "").strip() or "не настроен"
            text = (
                f"✏️ Endpoint\n\nСейчас: {cur}\n\n"
                f"Новые клиентские профили будут использовать этот адрес.\n"
                f"Уже скачанные .conf нужно выдать заново."
            )
            rows = [
                [InlineKeyboardButton("🌐 Внешний IP", callback_data=_svc_cb("set_ep_ip", sid, srv, src=src))],
                [InlineKeyboardButton("🌍 Домен", callback_data=_svc_cb("set_ep_domain", sid, srv, src=src))],
                [InlineKeyboardButton("🗑 Сбросить", callback_data=_svc_cb("set_ep_clear", sid, srv, src=src))],
                [InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("config", sid, srv, src=src))],
            ]
            await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))
        elif op == "set_ep_ip":
            SVC_PROFILE_ADD_STATE[uid] = {"_kind": "set_endpoint_ip", "service": sid, "server": srv, "src": src}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("set_endpoint", sid, srv, src=src))]])
            await q.edit_message_text("Введите внешний IP-адрес.\nНапример:\n\n203.0.113.15", reply_markup=kb)
        elif op == "set_ep_domain":
            SVC_PROFILE_ADD_STATE[uid] = {"_kind": "set_endpoint_domain", "service": sid, "server": srv, "src": src}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("set_endpoint", sid, srv, src=src))]])
            await q.edit_message_text("Введите доменное имя.\nНапример:\n\nvpn.example.com", reply_markup=kb)
        elif op == "set_ep_clear":
            await q.answer()
            await self._config_update_and_show(q, sid, srv, endpoint="", src=src)
        elif op == "confirm_migrate":
            candidate = None
            try:
                candidate = await integrator.call(sid, srv, "detect_endpoint")
            except Exception:
                candidate = None
            head = (
                "Обнаружена классическая конфигурация WireGuard.\n\n"
                "Bot4VPS перенесёт существующие Peer в новый формат (будет создана резервная копия wg0.conf).\n\n"
            )
            if candidate:
                text = head + f"🌐 Обнаружен endpoint: {candidate}\nИспользовать его для клиентских конфигов?"
                rows = [
                    [InlineKeyboardButton(f"✅ Использовать {candidate}", callback_data=_svc_cb("migrate_use_ep", sid, srv, src=src))],
                    [InlineKeyboardButton("🌐 Ввести другой IP", callback_data=_svc_cb("migrate_other_ip", sid, srv, src=src))],
                    [InlineKeyboardButton("🌍 Ввести другой домен", callback_data=_svc_cb("migrate_other_domain", sid, srv, src=src))],
                    [InlineKeyboardButton("⏭ Без endpoint", callback_data=_svc_cb("migrate_no_ep", sid, srv, src=src))],
                    [InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("view", sid, srv, src=src))],
                ]
            else:
                text = head + "⚠️ Endpoint не найден. Введите внешний IP или домен для клиентских конфигов."
                rows = [
                    [InlineKeyboardButton("🌐 Ввести IP", callback_data=_svc_cb("migrate_other_ip", sid, srv, src=src))],
                    [InlineKeyboardButton("🌍 Ввести домен", callback_data=_svc_cb("migrate_other_domain", sid, srv, src=src))],
                    [InlineKeyboardButton("⏭ Без endpoint", callback_data=_svc_cb("migrate_no_ep", sid, srv, src=src))],
                    [InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("view", sid, srv, src=src))],
                ]
            await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))
        elif op == "migrate_use_ep":
            try:
                candidate = await integrator.call(sid, srv, "detect_endpoint")
                if candidate:
                    await integrator.call(sid, srv, "set_endpoint", candidate)
            except Exception as e:
                await q.message.reply_text(f"⚠️ Не удалось применить endpoint: {e}")
            await self._migrate_reissue_menu(q, sid, srv, src)
        elif op == "migrate_other_ip":
            SVC_PROFILE_ADD_STATE[uid] = {"_kind": "migrate_endpoint_ip", "service": sid, "server": srv, "src": src}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("confirm_migrate", sid, srv, src=src))]])
            await q.edit_message_text("Введите внешний IP-адрес сервера.\nНапример:\n\n203.0.113.15", reply_markup=kb)
        elif op == "migrate_other_domain":
            SVC_PROFILE_ADD_STATE[uid] = {"_kind": "migrate_endpoint_domain", "service": sid, "server": srv, "src": src}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("confirm_migrate", sid, srv, src=src))]])
            await q.edit_message_text("Введите доменное имя.\nНапример:\n\nvpn.example.com", reply_markup=kb)
        elif op == "migrate_no_ep":
            await self._migrate_reissue_menu(q, sid, srv, src)
        elif op == "migrate_reissue":
            await _enqueue_watch_query(q, sid, srv, "migrate", {"reissue": True}, src=src)
        elif op == "migrate":
            await _enqueue_watch_query(q, sid, srv, "migrate", {}, src=src)
        elif op == "reissue_all":
            text = (
                "♻️ Перевыпустить все импортированные профили?\n\n"
                "Будут созданы новые пары ключей; старые конфиги на устройствах перестанут работать. "
                "IP-адреса сохранятся.\n\nПродолжить?"
            )
            rows = [
                [InlineKeyboardButton("✅ Да, перевыпустить все", callback_data=_svc_cb("reissue_all_run", sid, srv, src=src))],
                [InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("profiles", sid, srv, src=src))],
            ]
            await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))
        elif op == "reissue_all_run":
            await _enqueue_watch_query(q, sid, srv, "reissue_all", {}, src=src)
        else:
            return False
        return True

    # ----------------------------------------------------------
    # Текстовые flow (add / rename / endpoint). State — SVC_PROFILE_ADD_STATE.
    # ----------------------------------------------------------

    def owns_message(self, user_id: int) -> bool:
        return user_id in SVC_PROFILE_ADD_STATE

    async def handle_message(self, ctx: MessageCtx) -> bool:
        user_id = ctx.user_id
        if user_id not in SVC_PROFILE_ADD_STATE:
            return False
        update = ctx.update
        context = ctx.context
        st = SVC_PROFILE_ADD_STATE.pop(user_id)
        text = update.message.text.strip()
        kind = st.get("_kind")

        if kind == "rename_profile":
            if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,30}$", text):
                await update.message.reply_text("❌ Недопустимое имя. Используйте латинские буквы, цифры, дефис и подчеркивание.")
                SVC_PROFILE_ADD_STATE[user_id] = st
                return True
            await self._exec_quick_action_message(
                update.message, context.bot, st["server"], "rename_profile",
                {"old_name": st["name"], "new_name": text}, src=st.get("src"), old_name=st["name"]
            )
            return True

        if kind == "endpoint_ip":
            try:
                ip = ipaddress.ip_address(text)
                if ip.is_private:
                    await update.message.reply_text("❌ Это снова локальный адрес. Нужен внешний (публичный) IP.")
                    SVC_PROFILE_ADD_STATE[user_id] = st
                    return True
            except ValueError:
                await update.message.reply_text("❌ Некорректный IP-адрес. Пример: 203.0.113.15")
                SVC_PROFILE_ADD_STATE[user_id] = st
                return True
            await update.message.reply_text(f"✅ Endpoint: {text}")
            await _show_install_menu(update.message, user_id, st["service"], st["server"], st.get("src"), {"WG_ENDPOINT": text})
            return True

        if kind == "endpoint_domain":
            if not re.match(r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$", text) or "." not in text:
                await update.message.reply_text("❌ Некорректный домен. Пример: vpn.example.com")
                SVC_PROFILE_ADD_STATE[user_id] = st
                return True
            await update.message.reply_text(f"✅ Endpoint: {text}")
            await _show_install_menu(update.message, user_id, st["service"], st["server"], st.get("src"), {"WG_ENDPOINT": text})
            return True

        if kind == "set_endpoint_ip":
            try:
                ip = ipaddress.ip_address(text)
                if ip.is_private:
                    await update.message.reply_text("❌ Это локальный адрес. Нужен внешний (публичный) IP.")
                    SVC_PROFILE_ADD_STATE[user_id] = st
                    return True
            except ValueError:
                await update.message.reply_text("❌ Некорректный IP. Пример: 203.0.113.15")
                SVC_PROFILE_ADD_STATE[user_id] = st
                return True
            await self._config_update_and_show(update.message, st["service"], st["server"], endpoint=text, src=st.get("src"))
            return True

        if kind == "set_endpoint_domain":
            if not re.match(r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$", text) or "." not in text:
                await update.message.reply_text("❌ Некорректный домен. Пример: vpn.example.com")
                SVC_PROFILE_ADD_STATE[user_id] = st
                return True
            await self._config_update_and_show(update.message, st["service"], st["server"], endpoint=text, src=st.get("src"))
            return True

        if kind == "cfg_port":
            if not re.match(r"^\d{1,5}$", text) or not (1 <= int(text) <= 65535):
                await update.message.reply_text("❌ Порт — число от 1 до 65535.")
                SVC_PROFILE_ADD_STATE[user_id] = st
                return True
            await self._config_update_and_show(update.message, st["service"], st["server"], port=int(text), src=st.get("src"))
            return True

        if kind == "cfg_addr":
            if not re.match(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$", text):
                await update.message.reply_text("❌ Адрес — CIDR вида 10.8.0.1/24.")
                SVC_PROFILE_ADD_STATE[user_id] = st
                return True
            await self._config_update_and_show(update.message, st["service"], st["server"], address=text, src=st.get("src"))
            return True

        if kind == "cfg_dns":
            tokens = [t.strip() for t in text.split(",") if t.strip()]
            if not tokens or any(not re.match(r"^[A-Za-z0-9._:-]+$", t) for t in tokens):
                await update.message.reply_text("❌ DNS — IP или домен (через запятую). Пример: 1.1.1.1")
                SVC_PROFILE_ADD_STATE[user_id] = st
                return True
            await self._config_update_and_show(update.message, st["service"], st["server"], dns=", ".join(tokens), src=st.get("src"))
            return True

        if kind == "migrate_endpoint_ip":
            try:
                ip = ipaddress.ip_address(text)
                if ip.is_private:
                    await update.message.reply_text("❌ Это локальный адрес. Нужен внешний (публичный) IP.")
                    SVC_PROFILE_ADD_STATE[user_id] = st
                    return True
            except ValueError:
                await update.message.reply_text("❌ Некорректный IP-адрес. Пример: 203.0.113.15")
                SVC_PROFILE_ADD_STATE[user_id] = st
                return True
            try:
                await integrator.call(st["service"], st["server"], "set_endpoint", text)
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")
                return True
            await self._migrate_reissue_menu(update.message, st["service"], st["server"], st.get("src"))
            return True

        if kind == "migrate_endpoint_domain":
            if not re.match(r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$", text) or "." not in text:
                await update.message.reply_text("❌ Некорректный домен. Пример: vpn.example.com")
                SVC_PROFILE_ADD_STATE[user_id] = st
                return True
            try:
                await integrator.call(st["service"], st["server"], "set_endpoint", text)
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")
                return True
            await self._migrate_reissue_menu(update.message, st["service"], st["server"], st.get("src"))
            return True

        # default: добавление профиля
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,30}$", text):
            await update.message.reply_text("❌ Недопустимое имя. Используйте латинские буквы, цифры, дефис и подчеркивание.")
            SVC_PROFILE_ADD_STATE[user_id] = st
            return True
        await self._exec_quick_action_message(
            update.message, context.bot, st["server"], "add_profile", {"name": text}, src=st.get("src")
        )
        return True


# Саморегистрация (side-effect импорта модуля; триггерится через services/__init__.py).
register_service_ui(WireGuardUI())
