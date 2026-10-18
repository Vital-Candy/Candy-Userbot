"""Ссылки на сообщения Telegram."""
from __future__ import annotations

# Telethon кодирует id каналов и супергрупп как -100<id>: вычитаем этот сдвиг.
_CHANNEL_OFFSET = 1_000_000_000_000


def message_link(chat_id: int, message_id: int) -> str | None:
    """Ссылка на сообщение по chat_id в формате Telethon, либо None, если ссылки не бывает.

    * каналы и супергруппы (``-100…``): ``https://t.me/c/<id>/<сообщение>``, откроется у участников;
    * личные чаты и «Избранное» (положительный id): ``tg://openmessage``;
    * обычные группы (маленький отрицательный id): ссылки не существует.
    """
    chat_id, message_id = int(chat_id), int(message_id)
    if chat_id <= -_CHANNEL_OFFSET:
        return f"https://t.me/c/{-chat_id - _CHANNEL_OFFSET}/{message_id}"
    if chat_id > 0:
        return f"tg://openmessage?user_id={chat_id}&message_id={message_id}"
    return None
