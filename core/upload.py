"""
Универсальный загрузчик файлов Bot4VPS.

Профиль описывает куда и как сохранять;
движок только: получить → проверить → сохранить → callback.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional, Set

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

# user_id → активный профиль загрузки
UPLOAD_STATE: dict[int, "UploadProfile"] = {}


ValidatorFn = Callable[[Path, bytes], Optional[str]]
# returns error message or None if ok

SuccessFn = Callable[[Path], Awaitable[None]]


@dataclass
class UploadProfile:
    id: str
    title: str
    destination: Path
    allowed_extensions: Set[str]

    max_size: int = 512 * 1024
    overwrite: bool = True

    cancel_callback: str = "main"
    success_callback: str = "main"

    success_button: str = "Продолжить"
    back_button: str = "⬅️ Назад"

    validator: Optional[ValidatorFn] = None
    hint: str = ""

def validate_shell_script(path: Path, data: bytes) -> Optional[str]:
    """Базовая проверка .sh для SCRIPT_UPLOAD."""
    if path.suffix.lower() != ".sh":
        return "Ожидается файл с расширением .sh"

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "Файл должен быть в UTF-8"

    if "\r\n" in text or text.startswith("\ufeff"):
        # soft: warn via allowing but we could reject CRLF
        if "\r\n" in text:
            return "Файл содержит Windows-переводы строк (CRLF). Сохраните как LF."

    first = text.lstrip().split("\n", 1)[0] if text.strip() else ""
    if first and not first.startswith("#!"):
        # не жёстко — многие скрипты без shebang всё ещё ок
        pass

    if len(text.strip()) == 0:
        return "Файл пустой"

    return None


# Готовые профили
SCRIPT_UPLOAD = UploadProfile(
    id="script",
    title="Загрузка скрипта",
    destination=Path("scripts"),
    allowed_extensions={".sh"},
    max_size=1024 * 1024,
    overwrite=True,

    cancel_callback="scripts",
    success_callback="scripts_list",

    success_button="📜 Список скриптов",
    back_button="⬅️ Скрипты",

    validator=validate_shell_script,
    hint="Пришлите файл .sh (документ в Telegram).",
)
UPLOAD_PROFILES = {
    SCRIPT_UPLOAD.id: SCRIPT_UPLOAD,
}

# Пример на будущее:
# KEY_UPLOAD = UploadProfile(
#     id="ssh_key",
#     title="Импорт SSH-ключа",
#     destination=Path("keys"),
#     allowed_extensions={".pem", ".key", ""},
#     validator=validate_private_key,
#     cancel_callback="keys",
#     success_callback="keys",
# )


def start_upload_state(user_id: int, profile: UploadProfile) -> None:
    UPLOAD_STATE[user_id] = profile


def cancel_upload(user_id: int) -> None:
    UPLOAD_STATE.pop(user_id, None)


def get_upload_profile(user_id: int) -> Optional[UploadProfile]:
    return UPLOAD_STATE.get(user_id)

def get_upload_profile_def(profile_id: str) -> Optional[UploadProfile]:
    return UPLOAD_PROFILES.get(profile_id)

def _cancel_keyboard(profile: UploadProfile) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data=f"upload_cancel:{profile.id}")],
    ])


async def _upload_error(message, profile: UploadProfile, text: str) -> None:
    await message.reply_text(
        f"❌ {text}",
        reply_markup=_cancel_keyboard(profile),
    )

async def prompt_upload(query, profile: UploadProfile) -> None:
    """Показать инструкцию и перевести пользователя в режим ожидания файла."""
    start_upload_state(query.from_user.id, profile)
    profile.destination.mkdir(parents=True, exist_ok=True)

    text = (
        f"📤 {profile.title}\n\n"
        f"{profile.hint or 'Пришлите файл как документ.'}\n\n"
        f"Допустимо: {', '.join(sorted(profile.allowed_extensions)) or 'любое'}\n"
        f"Макс. размер: {profile.max_size // 1024} КБ"
    )
    await query.edit_message_text(
        text,
        reply_markup=_cancel_keyboard(profile),
    )

async def process_upload_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Обработка входящего документа.
    Возвращает True, если сообщение обработано загрузчиком.
    """
    user = update.effective_user
    message = update.message
    if not user or not message or not message.document:
        return False

    profile = get_upload_profile(user.id)
    if not profile:
        return False

    doc = message.document
    name = doc.file_name or "file"
    ext = Path(name).suffix.lower()

    # extension
    if profile.allowed_extensions and ext not in profile.allowed_extensions:
        await _upload_error(
            message,
            profile,
            f"Недопустимое расширение «{ext or '(нет)'}».\n"
            f"Нужно: {', '.join(sorted(profile.allowed_extensions))}"
        )
        return True

    if doc.file_size and doc.file_size > profile.max_size:
        await _upload_error(
            message,
            profile,
            f"Файл слишком большой ({doc.file_size // 1024} КБ).\n"
            f"Лимит: {profile.max_size // 1024} КБ"
        )
        return True

    # download
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        data = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        await _upload_error(
            message,
            profile,
            f"Не удалось скачать файл:\n{e}"
        )
        return True

    dest_dir = profile.destination
    dest_dir.mkdir(parents=True, exist_ok=True)
    # sanitize filename
    safe_name = re.sub(r"[^\w.\-]", "_", Path(name).name)
    if not safe_name:
        safe_name = f"upload{ext}"
    dest = dest_dir / safe_name

    if dest.exists() and not profile.overwrite:
        await _upload_error(
            message,
            profile,
            f"Файл «{safe_name}» уже есть. Перезапись запрещена."
        )
        return True

    if profile.validator:
        err = profile.validator(dest, data)
        if err:
            await _upload_error(
                message,
                profile,
                f"Проверка не пройдена:\n{err}"
            )
            return True

    try:
        dest.write_bytes(data)
        # scripts often need +x
        if ext == ".sh":
            os.chmod(dest, 0o755)
    except Exception as e:
        await _upload_error(
            message,
            profile,
            f"Ошибка записи:\n{e}"
        )
        return True

    cancel_upload(user.id)

    await message.reply_text(
        f"✅ Загружено: `{safe_name}`\n📁 {dest_dir}/",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(profile.success_button, callback_data=profile.success_callback)],
            [InlineKeyboardButton(profile.back_button, callback_data=profile.cancel_callback)],
            [InlineKeyboardButton("🏠 Меню", callback_data="main")],
        ]),
    )
    return True


async def process_upload_callback(query, data: str) -> bool:
    """upload_cancel:profile_id — снять режим ожидания файла."""
    if not data.startswith("upload_cancel:"):
        return False
    cancel_upload(query.from_user.id)
    profile_id = data.split(":", 1)[1]
    profile = get_upload_profile_def(profile_id)
    if profile:
        back = profile.cancel_callback
        label = profile.back_button
    else:
        back = "main"
        label = "🏠 Меню"
    await query.edit_message_text(
        "❌ Загрузка отменена.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(label, callback_data=back)],
        ]),
    )
    return True
