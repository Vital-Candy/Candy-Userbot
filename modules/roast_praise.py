# modules/roast_praise.py
import json
import os
import random
import asyncio
import logging
from telethon import events
from core.dispatcher import register_command
from core.client import client
from utils.tools import get_args

logger = logging.getLogger("roast_praise")
DATA_DIR = os.path.join(os.path.dirname(__file__), "phrase_data", "roast_praise")

phrase_cache = {}
_registered_handlers = []

def load_phrases(filename):
    if filename not in phrase_cache:
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            logger.error(f"Файл не найден: {path}")
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                phrase_cache[filename] = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Ошибка чтения JSON в файле {filename}: {e}")
            # Чтобы не ронять бота, возвращаем пустой список
            phrase_cache[filename] = []
    return phrase_cache[filename]

def init():
    global _registered_handlers
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []

    register_command("roast", "Отругать [-ru/-uz/-en]", 
                     ".roast [@тег] [кол-во] [флаги]", category="приколы")
    register_command("praise", "Похвалить [-ru/-uz/-en]", 
                     ".praise [@тег] [кол-во] [флаги]", category="приколы")

    h_roast = client.add_event_handler(roast_cmd, events.NewMessage(outgoing=True, pattern=r"^\.roast(?: (.+))?"))
    h_praise = client.add_event_handler(praise_cmd, events.NewMessage(outgoing=True, pattern=r"^\.praise(?: (.+))?"))
    _registered_handlers.append(h_roast)
    _registered_handlers.append(h_praise)
    logger.info("Модуль roast/praise зарегистрирован (с защитой JSON)")

def shutdown():
    global _registered_handlers
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []
    logger.info("Модуль roast/praise: обработчики удалены")

async def get_target(event, args):
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        if reply_msg and reply_msg.sender_id:
            try:
                user = await client.get_entity(reply_msg.sender_id)
                if user.username:
                    return f"@{user.username}"
                else:
                    return f"[{user.first_name}](tg://user?id={user.id})"
            except:
                return None
    for arg in args:
        if arg.startswith("@"):
            return arg
    return None

def get_count(args):
    for arg in args:
        if arg.isdigit():
            return max(1, min(10, int(arg)))
    return 1

def get_flags(args):
    lang = "ru"
    female = False
    for arg in args:
        if arg in ("-ru", "-uz", "-en"):
            lang = arg[1:]
        elif arg == "-g":
            female = True
    return lang, female

def select_phrases(lang, female, is_roast, count):
    if lang == "ru":
        if is_roast:
            suffix = "roast_ru_f" if female else "roast_ru_m"
        else:
            suffix = "praise_ru_f" if female else "praise_ru_m"
    elif lang == "uz":
        suffix = "roast_uz" if is_roast else "praise_uz"
    else:  # en
        suffix = "roast_en" if is_roast else "praise_en"
    
    phrases = load_phrases(f"{suffix}.json")
    if not phrases:
        return ["⚠️ Словарь пуст или отсутствует."]
    # Берём случайные фразы без повторений
    return random.sample(phrases, min(count, len(phrases)))

def format_phrase(phrase, target):
    if target:
        if "{target}" in phrase:
            return phrase.replace("{target}", target)
        else:
            # Если маркера нет, просто добавляем обращение в начале
            return f"{target}, {phrase[0].lower()}{phrase[1:]}"
    return phrase

async def send_phrases(event, phrases):
    for phrase in phrases:
        await client.send_message(event.chat_id, phrase, parse_mode='markdown')
        await asyncio.sleep(0.15)

async def roast_cmd(event):
    args = get_args(event)
    target = await get_target(event, args)
    count = get_count(args)
    lang, female = get_flags(args)

    phrases = select_phrases(lang, female, is_roast=True, count=count)
    phrases = [format_phrase(p, target) for p in phrases]

    await event.delete()
    await send_phrases(event, phrases)

async def praise_cmd(event):
    args = get_args(event)
    target = await get_target(event, args)
    count = get_count(args)
    lang, female = get_flags(args)

    phrases = select_phrases(lang, female, is_roast=False, count=count)
    phrases = [format_phrase(p, target) for p in phrases]

    await event.delete()
    await send_phrases(event, phrases)