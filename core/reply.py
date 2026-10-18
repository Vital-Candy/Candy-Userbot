"""Единый помощник для ответа на сообщение/команду."""
from __future__ import annotations

import asyncio
from typing import Any

from utils.logger import logger

try:
    from telethon import errors as _errors

    _NOT_MODIFIED: tuple[type[BaseException], ...] = (_errors.MessageNotModifiedError,)
    _FLOOD: tuple[type[BaseException], ...] = (_errors.FloodWaitError,)
except (ImportError, AttributeError):  # Telethon не установлен
    _NOT_MODIFIED = _FLOOD = ()

# Дольше этого FloodWait не ждём: ответ на команду уже не нужен.
MAX_FLOOD_WAIT = 10  # секунды


async def answer(event: Any, text: str) -> bool:
    """Показывает ответ на команду и никогда не бросает исключение.

    Сначала редактирует сообщение с командой (так принято в userbot). Затем:

    * ``MessageNotModified``: текст уже такой же, это успех;
    * ``FloodWait`` до ``MAX_FLOOD_WAIT`` секунд: ждём и повторяем один раз;
    * остальные ошибки Telegram и невозможность редактировать (чужое
      сообщение): отправляем новое сообщение через ``respond``.

    Возвращает True, если пользователь увидел текст.
    """
    if getattr(event, "out", True) is False:
        # Чужое сообщение отредактировать нельзя: отвечаем на него.
        return await _respond(event, text, prefer_reply=True)
    try:
        return await _edit(event, text)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Не удалось отредактировать сообщение (%s), отправляю новое.", _name(exc))
    return await _respond(event, text)


async def _edit(event: Any, text: str) -> bool:
    """Редактирует сообщение с одним повтором после короткого FloodWait.

    Длинный FloodWait и прочие ошибки пробрасываются: ``answer`` перейдёт на новое сообщение.
    """
    try:
        await event.edit(text)
        return True
    except _NOT_MODIFIED:
        return True
    except _FLOOD as exc:
        seconds = int(getattr(exc, "seconds", 0) or 0)
        if seconds > MAX_FLOOD_WAIT:
            raise
        logger.warning("FloodWait %s с при ответе, жду.", seconds)
        await asyncio.sleep(seconds)
        # Второй попытке исключения уже не гасим, кроме «не изменено»: его вызывает повтор того же текста.
        try:
            await event.edit(text)
        except _NOT_MODIFIED:
            pass
        return True


async def _respond(event: Any, text: str, *, prefer_reply: bool = False) -> bool:
    """Отправляет новое сообщение (``reply`` или ``respond``). False, если отправить не вышло."""
    respond = getattr(event, "reply", None) if prefer_reply else None
    respond = respond or getattr(event, "respond", None)
    if respond is None:
        logger.error("Не удалось ответить пользователю: у события нет respond().")
        return False
    try:
        await respond(text)
        return True
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("Не удалось ответить пользователю: %s", _name(exc))
        return False


def _name(exc: BaseException) -> str:
    """Короткое описание ошибки для лога: тип и текст (если он есть)."""
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
