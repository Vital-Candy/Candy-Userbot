# modules/purge.py
import asyncio
import logging
from telethon import events, errors
from core.dispatcher import register_command
from core.client import client
from utils.tools import get_args

logger = logging.getLogger("purge")

active_purge_task = None
_registered_handlers = []

def init():
    global _registered_handlers
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []

    register_command(
        "purge",
        "Очистка сообщений",
        ".purge <количество> [all] | .purge stop",
        "Удаляет указанное количество последних сообщений.\n"
        "Без флага 'all' удаляет только свои сообщения.\n"
        ".purge 20 – удалит 20 ваших последних сообщений (пропускает чужие)\n"
        ".purge 5 all – удалит 5 любых последних сообщений\n"
        ".purge stop – остановить текущий процесс",
        category="инструменты"
    )
    h = client.add_event_handler(purge_handler, events.NewMessage(outgoing=True, pattern=r"^\.purge(?: (.+))?"))
    _registered_handlers.append(h)
    logger.info("Модуль purge зарегистрирован")

def shutdown():
    global _registered_handlers, active_purge_task
    if active_purge_task and not active_purge_task.done():
        active_purge_task.cancel()
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []
    logger.info("Модуль purge: обработчики удалены")

async def purge_worker(chat_id, count, all_msgs=False):
    """Удаляет ровно count сообщений, при all_msgs=False удаляет только свои."""
    deleted = 0
    limit = count * 5 if not all_msgs else count
    async for msg in client.iter_messages(chat_id, limit=limit):
        if all_msgs or msg.out:
            try:
                await msg.delete()
                deleted += 1
                if deleted >= count:
                    break
                await asyncio.sleep(0.3)
            except errors.FloodWaitError as e:
                logger.warning(f"FloodWait {e.seconds}с, жду...")
                await asyncio.sleep(e.seconds)
                await msg.delete()
                deleted += 1
                if deleted >= count:
                    break
                await asyncio.sleep(0.3)
            except asyncio.CancelledError:
                logger.info("Очистка остановлена пользователем")
                return deleted
            except Exception as e:
                logger.error(f"Ошибка удаления: {e}")
                break
    return deleted

async def purge_handler(event):
    global active_purge_task
    args = get_args(event)
    if not args:
        await event.edit("❌ Используй: .purge <количество> [all] или .purge stop")
        return

    if args[0].lower() == "stop":
        if active_purge_task and not active_purge_task.done():
            active_purge_task.cancel()
            await event.edit("⏹ Очистка остановлена.")
            active_purge_task = None
        else:
            await event.edit("⚠️ Нет активной очистки.")
        return

    if active_purge_task and not active_purge_task.done():
        active_purge_task.cancel()
        logger.info("Предыдущая очистка отменена.")

    try:
        count = int(args[0])
    except ValueError:
        await event.edit("❌ Укажи число сообщений для удаления.")
        return

    all_msgs = False
    if len(args) > 1 and args[1].lower() == "all":
        all_msgs = True

    if count > 100:
        await event.edit("❌ Максимум 100 сообщений за раз.")
        return

    if count <= 0:
        await event.edit("❌ Число должно быть положительным.")
        return

    await event.delete()
    chat_id = event.chat_id
    active_purge_task = asyncio.create_task(purge_worker(chat_id, count, all_msgs))
    try:
        deleted = await active_purge_task
        msg = await client.send_message(chat_id, f"✅ Удалено {deleted} сообщений.")
        await asyncio.sleep(2)
        await msg.delete()
    except asyncio.CancelledError:
        pass
    active_purge_task = None