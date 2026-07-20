# modules/tag.py
import asyncio
import random
import logging
from telethon import events
from core.dispatcher import register_command
from core.client import client
from utils.tools import get_args

logger = logging.getLogger("tag")
_registered_handlers = []

def init():
    global _registered_handlers
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []

    register_command(
        "tag",
        "Упомянуть участников чата",
        ".tag all | .tag random [количество]",
        "all – упомянуть всех участников (одним сообщением)\n"
        "random 5 – упомянуть 5 случайных\n"
        "Работает только в группах.",
        category="приколы"
    )
    h = client.add_event_handler(tag_cmd, events.NewMessage(outgoing=True, pattern=r"^\.tag(?: (.+))?"))
    _registered_handlers.append(h)
    logger.info("Модуль tag зарегистрирован")

def shutdown():
    global _registered_handlers
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []
    logger.info("Модуль tag: обработчики удалены")

def make_mention(user):
    """Создаёт строку упоминания: @username или [имя](tg://user?id=...)."""
    if user.username:
        return f"@{user.username}"
    name = getattr(user, 'first_name', None) or "Участник"
    safe_name = name.replace('[', '').replace(']', '').replace('(', '').replace(')', '')
    return f"[{safe_name}](tg://user?id={user.id})"

async def tag_cmd(event):
    args = get_args(event)
    if not event.is_group:
        await event.edit("❌ Команда .tag работает только в группах!")
        return

    if not args:
        await event.edit("❌ Используй: .tag all или .tag random <число>")
        return

    mode = args[0].lower()
    await event.edit("⏳ Получаю список участников...")

    try:
        me = await client.get_me()
        participants = []
        async for user in client.iter_participants(event.chat_id):
            if user.id != me.id and not user.bot:
                participants.append(user)
    except Exception as e:
        await event.edit(f"❌ Не удалось получить участников: {e}")
        return

    if not participants:
        await event.edit("⚠️ В чате нет других участников.")
        return

    if mode == "all":
        selected = participants
    elif mode == "random":
        count = 5
        if len(args) >= 2 and args[1].isdigit():
            count = int(args[1])
        if count < 1:
            count = 1
        if count > len(participants):
            count = len(participants)
        selected = random.sample(participants, count)
    else:
        await event.edit("❌ Неизвестный режим. Используй all или random.")
        return

    mentions = [make_mention(u) for u in selected]
    mention_text = " ".join(mentions)

    if len(mention_text) > 4000:
        await event.edit("⚠️ Слишком много участников, отправляю частями...")
        for i in range(0, len(mentions), 50):
            chunk = " ".join(mentions[i:i+50])
            await client.send_message(event.chat_id, chunk)
            await asyncio.sleep(0.5)
        await event.delete()
    else:
        await event.delete()
        await client.send_message(event.chat_id, mention_text)