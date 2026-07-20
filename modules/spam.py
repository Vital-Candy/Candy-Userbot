# modules/spam.py
import asyncio
import logging
from telethon import events, errors
from core.dispatcher import register_command
from core.client import client
from utils.tools import get_args

logger = logging.getLogger("spam")

active_spam_task = None
_registered_handlers = []

def init():
    global _registered_handlers
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []

    register_command(
    "spam",
    "Многократная отправка сообщений",
    ".spam <кол-во> <текст> [-s задержка] | .spam stop",
    "Примеры:\n.spam 5 Привет\n.spam 10 Хэй -s 0.5\n.spam stop — остановить текущий спам",
    category="инструменты"
    )
    h = client.add_event_handler(spam_handler, events.NewMessage(outgoing=True, pattern=r"^\.spam(?: (.+))?"))
    _registered_handlers.append(h)
    logger.info("Модуль spam зарегистрирован")

def shutdown():
    global _registered_handlers, active_spam_task
    if active_spam_task and not active_spam_task.done():
        active_spam_task.cancel()
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []
    logger.info("Модуль spam: обработчики удалены")

def parse_spam_args(args):
    """
    Возвращает кортеж (count, text, delay) или (None, None, None) при ошибке.
    """
    if len(args) < 2:
        return None, None, None
    try:
        count = int(args[0])
    except ValueError:
        return None, None, None

    delay = 0.8
    text_parts = []
    i = 1
    while i < len(args):
        if args[i] == "-s" and i + 1 < len(args):
            try:
                delay = float(args[i + 1])
                if delay <= 0:
                    delay = 0.8
            except ValueError:
                pass
            i += 2
            continue
        text_parts.append(args[i])
        i += 1

    text = " ".join(text_parts)
    if not text:
        return None, None, None
    return count, text, delay

async def spam_worker(event, count, text, delay):
    """Отправляет сообщения с заданной задержкой."""
    for i in range(count):
        try:
            await event.respond(text)
            logger.debug(f"Спам {i+1}/{count}")
            await asyncio.sleep(delay)
        except errors.FloodWaitError as e:
            logger.warning(f"FloodWait {e.seconds}с, ждём...")
            await asyncio.sleep(e.seconds)
            await event.respond(text)
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            logger.info("Спам остановлен пользователем")
            return
        except Exception as e:
            logger.error(f"Ошибка при спаме: {e}")
            break

async def spam_handler(event):
    global active_spam_task
    args = get_args(event)
    if not args:
        await event.edit("❌ Используй: .spam <кол-во> <текст> [-s задержка] или .spam stop")
        return

    if args[0].lower() == "stop":
        if active_spam_task and not active_spam_task.done():
            active_spam_task.cancel()
            await event.edit("⏹ Спам остановлен.")
            active_spam_task = None
        else:
            await event.edit("⚠️ Нет активного спама.")
        return

    # Правильная распаковка – ТРИ переменные
    count, text, delay = parse_spam_args(args)
    if count is None or text is None:
        await event.edit("❌ Неверный формат. Пример: .spam 5 Привет")
        return
    if count > 50:
        await event.edit("❌ Максимум 50 сообщений за раз.")
        return

    await event.delete()
    active_spam_task = asyncio.create_task(spam_worker(event, count, text, delay))
    try:
        await active_spam_task
    except asyncio.CancelledError:
        pass
    active_spam_task = None