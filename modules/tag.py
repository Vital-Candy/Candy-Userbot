from __future__ import annotations

import asyncio
import random
import logging
import shlex

from telethon import events

import core.client as client_state
from core.dispatcher import register_command

logger = logging.getLogger("tag")
_handler = None


def _parse_args(raw: str) -> tuple[str, int | None]:
    """
    Разбирает аргументы команды.

    Возвращает (mode, count)
    mode: 'all' или 'random'
    count: количество (для random)
    """
    if not raw:
        return "", None

    parts = shlex.split(raw)
    mode = parts[0].lower()
    count = None
    if mode == "random" and len(parts) >= 2 and parts[1].isdigit():
        count = max(1, int(parts[1]))
    return mode, count


def _make_mention(user) -> str:
    """Создаёт строку упоминания: @username или [имя](tg://user?id=...)."""
    if user.username:
        return f"@{user.username}"
    name = getattr(user, 'first_name', None) or "Участник"
    # Экранируем спецсимволы для Markdown
    safe_name = name.replace('[', '').replace(']', '').replace('(', '').replace(')', '')
    return f"[{safe_name}](tg://user?id={user.id})"


async def tag_command(event) -> None:
    """Обработчик команды .tag."""
    try:
        raw = (event.pattern_match.group(1) or "").strip()

        # Проверка, что это группа
        if not event.is_group:
            await event.edit("❌ Команда .tag работает только в группах!")
            return

        if not raw:
            await event.edit("❌ Используй: `.tag all` или `.tag random <число>`")
            return

        mode, count = _parse_args(raw)
        if not mode:
            await event.edit("❌ Неизвестный режим. Используй `all` или `random`.")
            return

        await event.edit("⏳ Получаю список участников...")

        # Получаем участников (исключаем ботов и себя)
        me = await client_state.client.get_me()
        participants = []
        async for user in client_state.client.iter_participants(event.chat_id):
            if user.id != me.id and not getattr(user, 'bot', False):
                participants.append(user)

        if not participants:
            await event.edit("⚠️ В чате нет других участников.")
            return

        # Выбор участников
        if mode == "all":
            selected = participants
        elif mode == "random":
            if count is None:
                count = 5
            if count > len(participants):
                count = len(participants)
            selected = random.sample(participants, count)
        else:
            await event.edit("❌ Неизвестный режим. Используй `all` или `random`.")
            return

        # Формируем строку с упоминаниями
        mentions = [_make_mention(u) for u in selected]
        mention_text = " ".join(mentions)

        # Удаляем исходное сообщение команды
        await event.delete()

        # Отправка с разбивкой, если слишком длинное
        if len(mention_text) > 4000:
            logger.info("Tag: слишком много упоминаний, отправляю частями")
            for i in range(0, len(mentions), 50):
                chunk = " ".join(mentions[i:i+50])
                await client_state.client.send_message(
                    event.chat_id,
                    chunk,
                    parse_mode="markdown"
                )
                await asyncio.sleep(0.5)
        else:
            await client_state.client.send_message(
                event.chat_id,
                mention_text,
                parse_mode="markdown"
            )

    except Exception as e:
        logger.exception("Ошибка в .tag: %s", e)
        await event.edit(f"❌ <b>Ошибка:</b> <code>{str(e)}</code>", parse_mode="html")


def init() -> None:
    """Инициализация модуля."""
    global _handler
    if client_state.client is None:
        raise RuntimeError("TelegramClient не установлен")

    register_command(
        "tag",
        "Упомянуть участников чата",
        ".tag all | .tag random [количество]",
        category="Развлечения",
    )
    _handler = client_state.client.add_event_handler(
        tag_command,
        events.NewMessage(outgoing=True, pattern=r"^\.tag(?:\s+(.*))?$"),
    )
    logger.info("Модуль tag зарегистрирован")


async def shutdown() -> None:
    """Остановка модуля."""
    global _handler
    if client_state.client is not None and _handler is not None:
        client_state.client.remove_event_handler(_handler)
        _handler = None
        logger.info("Модуль tag остановлен")