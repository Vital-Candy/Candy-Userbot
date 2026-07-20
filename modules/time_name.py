# modules/time_name.py
import asyncio
import json
import logging
from datetime import datetime, timedelta
from telethon import events, functions, errors
from core.dispatcher import register_command
from core.client import client
from utils.tools import get_args

logger = logging.getLogger("time_name")

STATE_FILE = "time_name_state.json"

STYLE_MAPS = {
    1: str.maketrans("0123456789", "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"),
    2: str.maketrans("0123456789", "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡"),
    3: str.maketrans("0123456789", "①②③④⑤⑥⑦⑧⑨⓪"),
    4: str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉"),
    5: str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹"),
}

original_first_name = None
active_task = None
current_style = 1
_registered_handlers = []

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"running": False, "original_name": None, "style": 1}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

async def restore_name():
    """Восстанавливает оригинальное имя, если клиент ещё подключён."""
    if not client.is_connected():
        logger.warning("Клиент отключён, восстановление имени невозможно")
        return
    state = load_state()
    orig = state.get("original_name")
    if orig:
        try:
            await client(functions.account.UpdateProfileRequest(first_name=orig))
            logger.info("Имя восстановлено")
        except Exception as e:
            logger.error(f"Ошибка восстановления имени: {e}")

async def shutdown():
    """Безопасно отключает часы, восстанавливает имя и снимает обработчики."""
    global active_task, _registered_handlers
    if active_task and not active_task.done():
        active_task.cancel()
        try:
            await active_task
        except asyncio.CancelledError:
            pass
        active_task = None
    await restore_name()
    state = load_state()
    state["running"] = False
    save_state(state)
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []

def init():
    global original_first_name, active_task, current_style, _registered_handlers
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []
    h = client.add_event_handler(time_handler, events.NewMessage(outgoing=True, pattern=r"^\.time(?: (.+))?"))
    _registered_handlers.append(h)

    register_command(
    "time",
    "Живые часы в имени",
    ".time on [стиль] | .time off",
    "Меняет имя в реальном времени стилизованными цифрами.\n"
    "Стили: 1–5 (жирные, контурные, обведённые, подстрочные, надстрочные).",
    category="дизайн"
    )
    state = load_state()
    if state.get("running"):
        original_first_name = state.get("original_name")
        current_style = state.get("style", 1)
        if active_task and not active_task.done():
            active_task.cancel()
        active_task = asyncio.create_task(update_name_loop())
        logger.info("Часы автоматически перезапущены после перезагрузки")
    else:
        if active_task and not active_task.done():
            active_task.cancel()
        active_task = None
    logger.info("Модуль time_name инициализирован")

def format_time(style: int, now_time: str) -> str:
    return now_time.translate(STYLE_MAPS.get(style, STYLE_MAPS[1]))

async def update_name_loop():
    global original_first_name, current_style
    state = load_state()
    original_first_name = state.get("original_name")
    try:
        now = datetime.now()
        seconds_until_next_minute = 60 - now.second
        await asyncio.sleep(seconds_until_next_minute)
        while True:
            now = datetime.now()
            styled_time = format_time(current_style, now.strftime("%H:%M"))
            display_name = f"{original_first_name} | {styled_time}"
            try:
                await client(functions.account.UpdateProfileRequest(first_name=display_name))
            except errors.FloodWaitError as e:
                logger.warning(f"FloodWait {e.seconds}с")
                await asyncio.sleep(e.seconds)
                continue
            except Exception as e:
                logger.error(f"Ошибка обновления: {e}")
                await asyncio.sleep(5)
                continue
            next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
            wait_seconds = (next_minute - datetime.now()).total_seconds()
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
    except asyncio.CancelledError:
        raise

async def time_handler(event):
    global original_first_name, active_task, current_style
    args = get_args(event)
    if not args:
        await event.edit("❌ Используй: .time on [стиль] или .time off")
        return

    action = args[0].lower()
    if action == "off":
        if active_task and not active_task.done():
            active_task.cancel()
            try:
                await active_task
            except asyncio.CancelledError:
                pass
            active_task = None
        await restore_name()
        state = load_state()
        state["running"] = False
        save_state(state)
        await event.edit("⏹ Часы отключены. Имя восстановлено.")
        return

    if action == "on":
        if active_task and not active_task.done():
            await event.edit("⏳ Часы уже работают.")
            return

        style = 1
        if len(args) >= 2:
            try:
                style = int(args[1])
                if style not in STYLE_MAPS:
                    style = 1
            except:
                pass
        current_style = style

        me = await client.get_me()
        original_first_name = me.first_name or ""
        save_state({
            "running": True,
            "original_name": original_first_name,
            "style": style
        })

        active_task = asyncio.create_task(update_name_loop())

        now = datetime.now()
        styled_time = format_time(style, now.strftime("%H:%M"))
        display_name = f"{original_first_name} | {styled_time}"
        try:
            await client(functions.account.UpdateProfileRequest(first_name=display_name))
            await event.edit(f"✅ Часы в имени включены (стиль {style}).")
        except Exception as e:
            logger.error(f"Не удалось сразу обновить имя: {e}")
            await event.edit(f"⚠️ Часы запущены, но обновление отложено.")
    else:
        await event.edit("❌ Действие должно быть 'on' или 'off'.")