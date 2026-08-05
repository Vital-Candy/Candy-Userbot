from __future__ import annotations

import asyncio
import logging
import shlex

from telethon import errors, events

import core.client as client_state
from core.dispatcher import register_command


logger = logging.getLogger("spam")

TASK = "spam"

_handler = None
_account = None


def _parse_arguments(raw: str) -> tuple[str, int, float] | None:
    """
    Формат:
        .spam <текст> [-c количество] [-s задержка]

    По умолчанию:
        количество — 5
        задержка — 1 секунда

    Примеры:
        .spam Привет
        .spam Привет -c 10
        .spam Текст 123 -c 10 -s 0.5
        .spam "Привет, как дела?" -c 5
    """

    try:
        parts = shlex.split(raw)
    except ValueError:
        return None

    if not parts:
        return None

    count = 5
    delay = 1.0
    text_parts: list[str] = []

    index = 0

    while index < len(parts):
        part = parts[index]

        if part == "-c":
            if index + 1 >= len(parts):
                return None

            try:
                count = int(parts[index + 1])
            except ValueError:
                return None

            index += 2
            continue

        if part == "-s":
            if index + 1 >= len(parts):
                return None

            try:
                delay = float(parts[index + 1])
            except ValueError:
                return None

            index += 2
            continue

        text_parts.append(part)
        index += 1

    text = " ".join(text_parts).strip()

    if not text:
        return None

    if count < 1 or count > 50:
        return None

    if delay <= 0:
        return None

    return text, count, delay


async def _worker(
    chat_id: int,
    text: str,
    count: int,
    delay: float,
) -> None:
    """
    Отправляет сообщения.

    При FloodWait ожидает нужное время
    и повторяет текущее сообщение.
    """

    client = client_state.client

    if client is None:
        logger.error("TelegramClient не установлен")
        return

    try:
        for number in range(count):
            try:
                await client.send_message(
                    chat_id,
                    text,
                )

            except errors.FloodWaitError as error:
                logger.warning(
                    "FloodWait: ожидание %s секунд",
                    error.seconds,
                )

                await asyncio.sleep(
                    error.seconds
                )

                await client.send_message(
                    chat_id,
                    text,
                )

            if number < count - 1:
                await asyncio.sleep(delay)

    except asyncio.CancelledError:
        logger.info("Спам остановлен")
        raise

    except Exception:
        logger.exception(
            "Ошибка во время спама"
        )


async def _command(event) -> None:
    raw = (
        event.pattern_match.group(1) or ""
    ).strip()

    if raw.lower() == "stop":
        stopped = await _account.background.stop(
            TASK
        )

        if stopped:
            await event.edit(
                "⏹ <b>Спам остановлен.</b>",
                parse_mode="html",
            )
        else:
            await event.edit(
                "⚠️ <b>Активного спама нет.</b>",
                parse_mode="html",
            )

        return

    parsed = _parse_arguments(raw)

    if parsed is None:
        await event.edit(
            "❌ <b>Неверный формат.</b>\n\n"
            "<code>.spam Привет</code>\n"
            "<code>.spam Привет -c 10</code>\n"
            "<code>.spam Привет -c 10 -s 0.5</code>\n"
            "<code>.spam Текст 123 -c 5</code>\n"
            "<code>.spam stop</code>\n\n"
            "По умолчанию:\n"
            "Количество: <b>5</b>\n"
            "Задержка: <b>1 секунда</b>\n\n"
            "Максимум: <b>50 сообщений</b>",
            parse_mode="html",
        )

        return

    text, count, delay = parsed

    await _account.background.stop(
        TASK
    )

    chat_id = event.chat_id

    await event.delete()

    started = await _account.background.start(
        TASK,
        lambda: _worker(
            chat_id,
            text,
            count,
            delay,
        ),
    )

    if not started:
        logger.warning(
            "Не удалось запустить спам: "
            "задача уже существует"
        )


def init() -> None:
    global _handler
    global _account

    if client_state.client is None:
        raise RuntimeError(
            "TelegramClient не установлен"
        )

    from core.app import current_account

    _account = current_account()

    register_command(
        "spam",
        "Многократная отправка сообщений",
        ".spam <текст> [-c количество] "
        "[-s задержка]",
        category="инструменты",
    )

    _handler = (
        client_state.client.add_event_handler(
            _command,
            events.NewMessage(
                outgoing=True,
                pattern=(
                    r"^\.spam"
                    r"(?:\s+(.*))?$"
                ),
            ),
        )
    )

    logger.info(
        "Модуль spam зарегистрирован"
    )


async def shutdown() -> None:
    global _handler
    global _account

    if _account is not None:
        await _account.background.stop(
            TASK
        )

    if (
        client_state.client is not None
        and _handler is not None
    ):
        client_state.client.remove_event_handler(
            _handler
        )

    _handler = None
    _account = None

    logger.info(
        "Модуль spam остановлен"
    )