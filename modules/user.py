# modules/user.py
import logging
from telethon import events
from telethon.tl.functions.users import GetFullUserRequest
from core.dispatcher import register_command
from core.client import client
from utils.tools import get_args

logger = logging.getLogger("user")
_registered_handlers = []

def init():
    global _registered_handlers
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []

    register_command(
    "user",
    "Информация о пользователе",
    ".user [-n] [@username или ID]",
    "Флаг -n скрывает номер. Без аргументов — информация о себе.",
    category="инструменты"
    )
    h = client.add_event_handler(user_handler, events.NewMessage(outgoing=True, pattern=r"^\.user(?: (.+))?"))
    _registered_handlers.append(h)
    logger.info("Модуль user зарегистрирован")

def shutdown():
    global _registered_handlers
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []
    logger.info("Модуль user: обработчики удалены")

async def user_handler(event):
    args = get_args(event)               # список строк после команды
    hide_phone = "-n" in args            # проверяем наличие флага
    if hide_phone:
        args.remove("-n")                # убираем флаг, остальное – цель

    target = args[0] if args else event.sender_id

    try:
        entity = await client.get_entity(target)
        full = await client(GetFullUserRequest(entity))
    except Exception as e:
        await event.edit(f"❌ Ошибка: {e}")
        return

    user = entity
    me = await client.get_me()
    is_self = (user.id == me.id)
    info = f"**👤 Информация о пользователе**\n\n"
    
    if user.first_name:
        info += f"**Имя:** {user.first_name}\n"
    if user.last_name:
        info += f"**Фамилия:** {user.last_name}\n"
    if user.username:
        info += f"**Юзернейм:** @{user.username}\n"
    info += f"**ID:** `{user.id}`\n"
    
    # Номер телефона показываем только если смотрим на себя и не стоит флаг -n
    if is_self and not hide_phone and hasattr(user, 'phone') and user.phone:
        info += f"**Телефон:** {user.phone}\n"
    elif is_self and hide_phone:
        info += "**Телефон:** скрыт\n"
    
    if full.full_user.about:
        info += f"**Био:** {full.full_user.about}\n"
    
    if hasattr(user, 'premium') and user.premium:
        info += "**Premium:** ✅ Да\n"
    
    if not is_self:
        try:
            common = await client.get_common_chats(user)
            if common:
                info += f"**Общих чатов:** {len(common)}\n"
        except Exception:
            pass

    await event.edit(info)