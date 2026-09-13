from __future__ import annotations

"""Общая диагностика доставки Telegram.

Модуль не создаёт события, уведомления или Backup Operation. Он выполняет
только явную проверку транспорта и хранит безопасный runtime-снимок результата
для той пары Token + chat ID, которая действительно проверялась.
"""

from collections import OrderedDict
import asyncio
from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import (
    BadRequest,
    Forbidden,
    InvalidToken,
    NetworkError,
    RetryAfter,
    TelegramError,
    TimedOut,
)


OK = "OK"
DISABLED = "DISABLED"
NOT_CONFIGURED = "NOT_CONFIGURED"
TOKEN_MISSING = "TOKEN_MISSING"
CHAT_ID_MISSING = "CHAT_ID_MISSING"
INVALID_TOKEN = "INVALID_TOKEN"
API_UNAVAILABLE = "API_UNAVAILABLE"
CHAT_UNAVAILABLE = "CHAT_UNAVAILABLE"
BOT_BLOCKED = "BOT_BLOCKED"
SEND_ERROR = "SEND_ERROR"
API_ERROR = "API_ERROR"

TEST_MESSAGE = (
    "Проверка Telegram Bot4VPS\n\n"
    "Тестовое сообщение успешно отправлено."
)

# Уникальный callback_data кнопки [ОК] под тестовым сообщением. Значение
# определено здесь, а роутится в ui/telegram/bot_handlers.py::button() к уже
# существующему show_main_menu: зависимость идёт ui → core, как и везде.
TEST_MESSAGE_OK_CALLBACK = "tg_health_ok"


def build_test_message_keyboard() -> InlineKeyboardMarkup:
    """Inline-клавиатура [ОК] под тестовым сообщением проверки Telegram."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("ОК", callback_data=TEST_MESSAGE_OK_CALLBACK)]]
    )


_REASON = {
    OK: "Тестовое сообщение успешно отправлено.",
    DISABLED: "Telegram выключен в общих настройках Bot4VPS.",
    NOT_CONFIGURED: "Telegram для сохранённых настроек ещё не проверен.",
    TOKEN_MISSING: "Не указан токен Telegram-бота.",
    CHAT_ID_MISSING: "Не указан ID пользователя/чата.",
    INVALID_TOKEN: "Токен Telegram-бота недействителен.",
    API_UNAVAILABLE: "Telegram API временно недоступен.",
    CHAT_UNAVAILABLE: "Указанный пользователь/чат не существует или недоступен боту.",
    BOT_BLOCKED: "Пользователь заблокировал Telegram-бота.",
    SEND_ERROR: "Telegram не принял тестовое сообщение.",
    API_ERROR: "Telegram API вернул ошибку.",
}

_SETTINGS_CODES = {
    DISABLED,
    NOT_CONFIGURED,
    TOKEN_MISSING,
    CHAT_ID_MISSING,
    INVALID_TOKEN,
    CHAT_UNAVAILABLE,
    BOT_BLOCKED,
}

# Runtime-кэш намеренно не хранит Token. Ключ — односторонний fingerprint пары
# Token + chat ID. Несколько записей нужны, чтобы проверка несохранённых значений
# не стирала известное состояние текущей сохранённой конфигурации.
_HEALTH_CACHE_LIMIT = 8
_PROBE_TIMEOUT_SECONDS = 15.0
_SHUTDOWN_TIMEOUT_SECONDS = 5.0
_health_by_fingerprint: OrderedDict[str, dict[str, Any]] = OrderedDict()

# Формат Bot Token: <bot_id>:<base64url-подобный секрет>. Токен может
# оказаться в тексте исключения PTB («The token `…` was rejected») или в
# URL API внутри сообщения NetworkError — журнал не должен его получать.
_TOKEN_RE = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{30,}")


def mask_bot_token(text: Any) -> str:
    """Заменить вхождения Bot Token на *** (остальное сообщение — как есть)."""
    return _TOKEN_RE.sub("***", str(text))


@dataclass(frozen=True)
class TelegramHealthResult:
    code: str
    reason: str
    phase: str | None = None

    @property
    def ok(self) -> bool:
        return self.code == OK

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "code": self.code,
            "reason": self.reason,
            "can_fix_in_settings": self.code in _SETTINGS_CODES,
        }


def _result(code: str, *, phase: str | None = None) -> TelegramHealthResult:
    return TelegramHealthResult(code=code, reason=_REASON[code], phase=phase)


def _fingerprint(token: str, chat_id: int) -> str:
    value = f"{token}\0{chat_id}".encode("utf-8")
    return sha256(value).hexdigest()


def _remember(token: str, chat_id: int, result: TelegramHealthResult) -> None:
    key = _fingerprint(token, chat_id)
    _health_by_fingerprint[key] = result.as_dict()
    _health_by_fingerprint.move_to_end(key)
    while len(_health_by_fingerprint) > _HEALTH_CACHE_LIMIT:
        _health_by_fingerprint.popitem(last=False)


def health_for_configuration(
    *,
    enabled: bool,
    token: str,
    chat_id: int | None,
) -> dict[str, Any]:
    """Вернуть безопасное состояние именно сохранённой конфигурации."""
    if not enabled:
        return _result(DISABLED).as_dict()
    if not token:
        return _result(TOKEN_MISSING).as_dict()
    if chat_id is None:
        return _result(CHAT_ID_MISSING).as_dict()
    cached = _health_by_fingerprint.get(_fingerprint(token, chat_id))
    return dict(cached) if cached is not None else _result(NOT_CONFIGURED).as_dict()


def classify_telegram_error(
    exc: BaseException,
    *,
    phase: str,
) -> TelegramHealthResult:
    """Нормализовать PTB/transport exception без публикации его текста."""
    if isinstance(exc, InvalidToken):
        return _result(INVALID_TOKEN, phase=phase)
    if isinstance(exc, Forbidden):
        # Текст нужен только локально для различения двух Forbidden-сценариев;
        # наружу он никогда не возвращается и не логируется.
        detail = str(exc).lower()
        if "blocked" in detail or "bot was blocked" in detail:
            return _result(BOT_BLOCKED, phase=phase)
        return _result(CHAT_UNAVAILABLE, phase=phase)
    if isinstance(exc, BadRequest):
        if phase == "chat":
            return _result(CHAT_UNAVAILABLE, phase=phase)
        if phase == "send":
            detail = str(exc).lower()
            if any(word in detail for word in ("chat not found", "user not found", "chat_id")):
                return _result(CHAT_UNAVAILABLE, phase=phase)
            return _result(SEND_ERROR, phase=phase)
        return _result(API_ERROR, phase=phase)
    if isinstance(
        exc,
        (TimedOut, RetryAfter, NetworkError, asyncio.TimeoutError, TimeoutError),
    ):
        return _result(API_UNAVAILABLE, phase=phase)
    if isinstance(exc, TelegramError):
        return _result(SEND_ERROR if phase == "send" else API_ERROR, phase=phase)
    return _result(SEND_ERROR if phase == "send" else API_ERROR, phase=phase)


async def send_telegram_message(bot, *, chat_id: int, text: str, **kwargs):
    """Единственная низкоуровневая операция send_message для Health/Notifier."""
    return await bot.send_message(chat_id=chat_id, text=text, **kwargs)


async def check_health(
    *,
    enabled: bool,
    token: str,
    chat_id: int | None,
    active_bot=None,
) -> TelegramHealthResult:
    """Проверить Token → chat → реальную отправку, ничего не сохраняя."""
    if not enabled:
        return _result(DISABLED)
    if not token:
        return _result(TOKEN_MISSING)
    if chat_id is None:
        return _result(CHAT_ID_MISSING)

    probe_bot = active_bot
    owns_bot = False
    try:
        active_token = str(getattr(active_bot, "token", "") or "")
        if probe_bot is None or active_token != token:
            try:
                probe_bot = Bot(token=token)
                owns_bot = True
            except Exception as exc:
                result = classify_telegram_error(exc, phase="token")
                _remember(token, chat_id, result)
                return result
            try:
                await asyncio.wait_for(
                    probe_bot.initialize(),
                    timeout=_PROBE_TIMEOUT_SECONDS,
                )  # initialize выполняет реальный get_me
            except Exception as exc:
                result = classify_telegram_error(exc, phase="token")
                _remember(token, chat_id, result)
                return result
        else:
            try:
                await asyncio.wait_for(
                    probe_bot.get_me(),
                    timeout=_PROBE_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                result = classify_telegram_error(exc, phase="token")
                _remember(token, chat_id, result)
                return result

        try:
            await asyncio.wait_for(
                probe_bot.get_chat(chat_id=chat_id),
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            result = classify_telegram_error(exc, phase="chat")
            _remember(token, chat_id, result)
            return result

        try:
            await asyncio.wait_for(
                send_telegram_message(
                    probe_bot,
                    chat_id=chat_id,
                    text=TEST_MESSAGE,
                    # Кнопка [ОК] прикладывается только когда проверка идёт
                    # через бота работающего приложения: его callback_query
                    # читает button(). Updates временного бота под несохранённый
                    # токен никто не опрашивает, там кнопка висла бы навсегда.
                    reply_markup=(
                        None if owns_bot else build_test_message_keyboard()
                    ),
                ),
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            result = classify_telegram_error(exc, phase="send")
            _remember(token, chat_id, result)
            return result

        result = _result(OK)
        _remember(token, chat_id, result)
        return result
    finally:
        if owns_bot and probe_bot is not None:
            try:
                await asyncio.wait_for(
                    probe_bot.shutdown(),
                    timeout=_SHUTDOWN_TIMEOUT_SECONDS,
                )
            except Exception:
                # Результат реальной отправки не подменяем ошибкой cleanup.
                pass


def record_delivery_result(
    *,
    token: str,
    chat_id: Any,
    error: BaseException | None = None,
) -> None:
    """Не влияя на доставку, обновить health-state обычного уведомления."""
    try:
        normalized_token = str(token or "")
        if not normalized_token:
            return
        normalized_chat_id = int(chat_id)
        result = (
            _result(OK)
            if error is None
            else classify_telegram_error(error, phase="send")
        )
        _remember(normalized_token, normalized_chat_id, result)
    except Exception:
        # Пассивный health-снимок не должен менять queue/delivery semantics.
        return
