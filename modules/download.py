# modules/download.py
"""
Сохраняет исчезающее медиа (фото, видео, кружочки).
Использование: ответь на исчезающее сообщение и напиши .save
"""
import logging, os
from telethon import events
from core.dispatcher import register_command
from core.client import client
from utils.paths import CACHE_DIR

logger = logging.getLogger("download")
_registered_handlers: list = []


def init():
    global _registered_handlers
    for h in _registered_handlers:
        client.remove_event_handler(h)
    _registered_handlers = []

    register_command(
        "save",
        "Сохранить исчезающее медиа",
        ".save  (reply на фото / видео / кружочек)",
        "Скачивает медиа из реплая и отправляет обратно без ограничения на просмотр.",
        category="инструменты",
    )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    h = client.add_event_handler(
        save_handler,
        events.NewMessage(outgoing=True, pattern=r"^\.save$"),
    )
    _registered_handlers.append(h)
    logger.info("Модуль download (save) зарегистрирован")


def shutdown():
    for h in _registered_handlers:
        client.remove_event_handler(h)
    _registered_handlers.clear()
    logger.info("Модуль download: обработчики удалены")


async def save_handler(event):
    if not event.is_reply:
        return await event.edit("❌ Ответь на медиа которое хочешь сохранить")

    reply = await event.get_reply_message()

    if not reply or not reply.media:
        return await event.edit("❌ В сообщении нет медиа")

    msg = await event.edit("💾 Сохраняю...")

    try:
        path = await reply.download_media(file=str(CACHE_DIR))

        if not path or not os.path.exists(path):
            return await msg.edit("❌ Не удалось скачать медиа")

        await msg.delete()
        await client.send_file(event.chat_id, path)
        logger.info(f"Медиа сохранено: {os.path.basename(path)}")

    except Exception as e:
        logger.error(f"save_handler error: {e}")
        await msg.edit(f"❌ Ошибка: {e}")
