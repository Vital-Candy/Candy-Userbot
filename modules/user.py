from __future__ import annotations

import logging
import shlex
from telethon import events
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import RPCError

import core.client as client_state
from core.dispatcher import register_command

logger = logging.getLogger("user")
_handler = None


def _parse_args(raw: str) -> tuple[bool, str | None]:
    """
    Разбирает аргументы команды.

    Возвращает (hide_phone, target)
    hide_phone — True если указан флаг -n
    target — строка с @username, ID или None
    """
    if not raw:
        return False, None

    parts = shlex.split(raw)
    hide_phone = "-n" in parts
    if hide_phone:
        parts.remove("-n")
    target = parts[0] if parts else None
    return hide_phone, target


async def _get_entity(target: str | None):
    """Получает сущность пользователя по цели."""
    if target is None:
        return await client_state.client.get_me()
    return await client_state.client.get_entity(target)


async def user_command(event) -> None:
    """Обработчик команды .user."""
    try:
        raw = (event.pattern_match.group(1) or "").strip()
        hide_phone, target = _parse_args(raw)

        # Получаем сущность пользователя
        entity = await _get_entity(target)
        full = await client_state.client(GetFullUserRequest(entity))
        me = await client_state.client.get_me()
        is_self = (entity.id == me.id)

        # Формируем информацию
        info = "👤 <b>Информация о пользователе</b>\n\n"
        if entity.first_name:
            info += f"<b>Имя:</b> {entity.first_name}\n"
        if entity.last_name:
            info += f"<b>Фамилия:</b> {entity.last_name}\n"
        if entity.username:
            info += f"<b>Юзернейм:</b> @{entity.username}\n"
        info += f"<b>ID:</b> <code>{entity.id}</code>\n"

        # Телефон показываем только для себя и если не скрыт
        if is_self and not hide_phone and hasattr(entity, 'phone') and entity.phone:
            info += f"<b>Телефон:</b> <code>{entity.phone}</code>\n"
        elif is_self and hide_phone:
            info += "<b>Телефон:</b> скрыт\n"

        if full.full_user.about:
            info += f"<b>Био:</b> {full.full_user.about}\n"

        if hasattr(entity, 'premium') and entity.premium:
            info += "✅ <b>Premium</b>\n"

        if not is_self:
            try:
                common = await client_state.client.get_common_chats(entity)
                if common:
                    info += f"<b>Общих чатов:</b> {len(common)}\n"
            except RPCError:
                pass

        await event.edit(info, parse_mode="html")

    except Exception as e:
        logger.exception("Ошибка в .user: %s", e)
        await event.edit(f"❌ <b>Ошибка:</b> <code>{str(e)}</code>", parse_mode="html")


def init() -> None:
    """Инициализация модуля."""
    global _handler
    if client_state.client is None:
        raise RuntimeError("TelegramClient не установлен")

    register_command(
        "user",
        "Информация о пользователе",
        ".user [-n] [@username или ID]",
        category="Инструменты",
    )
    _handler = client_state.client.add_event_handler(
        user_command,
        events.NewMessage(outgoing=True, pattern=r"^\.user(?:\s+(.*))?$"),
    )
    logger.info("Модуль user зарегистрирован")


async def shutdown() -> None:
    """Остановка модуля."""
    global _handler
    if client_state.client is not None and _handler is not None:
        client_state.client.remove_event_handler(_handler)
        _handler = None
        logger.info("Модуль user остановлен")