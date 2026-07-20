# core/dispatcher.py
import time
import os
import sys
import asyncio
import logging
import shutil
from telethon import events
from .client import client
from .loader import reload_modules
from config import VERSION, OWNER
from utils.paths import ASSETS_DIR, PROJECT_ROOT, LOG_PATH, CACHE_DIR

logger = logging.getLogger("dispatcher")

start_time = time.time()

def get_uptime() -> str:
    delta = int(time.time() - start_time)
    hours, remainder = divmod(delta, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

command_registry = {}

def register_command(name: str, description: str, usage: str, details: str = "", category: str = "other"):
    # Удаляем старые записи
    for cat in list(command_registry.keys()):
        if name in command_registry[cat]:
            del command_registry[cat][name]
            if not command_registry[cat]:
                del command_registry[cat]
    if category not in command_registry:
        command_registry[category] = {}
    command_registry[category][name] = {
        "description": description,
        "usage": usage,
        "details": details
    }

def get_category_emoji(category: str) -> str:
    emojis = {
        "система": "⚙️",
        "инструменты": "🛠️",
        "дизайн": "🎨",
        "приколы": "🎭",
        "other": "📦"
    }
    return emojis.get(category, "📌")

async def animate_text(event, base_text, frames, delay=0.3):
    try:
        for frame in frames:
            await event.edit(f"{base_text} {frame}")
            await asyncio.sleep(delay)
    except Exception:
        pass

async def finalize_command(event, final_text, delete_after=2):
    try:
        await event.edit(final_text)
        await asyncio.sleep(delete_after)
        await event.delete()
    except Exception:
        pass

def setup_dispatcher():
    # Встроенные команды
    register_command("ping", "Проверка задержки", ".ping",
                     category="система")
    register_command("help", "Справка по командам", ".help [команда]",
                     category="система")
    register_command("alive", "Статус бота", ".alive",
                     category="система")
    register_command("reload", "Перезагрузить модули", ".reload",
                     category="система")
    register_command("restart", "Перезапустить бота", ".restart",
                     category="система")
    register_command("stop", "Остановить бота", ".stop",
                     category="система")
    register_command("clear", "Очистить кеш и логи", ".clear",
                     "Удаляет все файлы из папки cache/.nomedia, все папки __pycache__ и очищает userbot.log",
                     category="система")

    # Обработчики
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.ping$"))
    async def ping_handler(event):
        start = time.time()
        await event.edit("🏓 Pong!")
        end = time.time()
        delay = round((end - start) * 1000, 2)
        await event.edit(f"🏓 Pong! `{delay}ms`")
        logger.info(f"Ping: {delay}ms")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.help(?: (.+))?"))
    async def help_handler(event):
        args = event.pattern_match.group(1)
        if args:
            cmd_name = args.strip().lower()
            found = None
            for cmds in command_registry.values():
                if cmd_name in cmds:
                    found = cmds[cmd_name]
                    break
            if found:
                text = (
                    f"**📖 Команда:** `{cmd_name}`\n"
                    f"**Описание:** {found.get('description', '—')}\n"
                    f"**Использование:** `{found.get('usage', '')}`\n"
                )
                if found.get('details'):
                    text += f"**Подробнее:** {found['details']}\n"
                await event.edit(text)
            else:
                await event.edit(f"❌ Команда `{cmd_name}` не найдена.")
            return

        # Лаконичный .help с категориями
        text = f"**✨ UserBot v{VERSION} | {OWNER}**\n\n"
        order = ["система", "инструменты", "дизайн", "приколы"]
        for cat in order:
            if cat in command_registry and command_registry[cat]:
                text += f"**{get_category_emoji(cat)}  {cat.upper()}**\n"
                for cmd_name, cmd_info in command_registry[cat].items():
                    desc = cmd_info.get("description", "Нет описания")
                    text += f"• `{cmd_name}` — {desc}\n"
                text += "\n"
        for cat, cmds in command_registry.items():
            if cat not in order and cmds:
                text += f"**{get_category_emoji(cat)}  {cat.upper()}**\n"
                for cmd_name, cmd_info in cmds.items():
                    desc = cmd_info.get("description", "Нет описания")
                    text += f"• `{cmd_name}` — {desc}\n"
                text += "\n"
        text += "Для подробностей: `.help <команда>`"
        await event.edit(text)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.alive$"))
    async def alive_handler(event):
        await event.delete()
        logo_path = os.path.join(ASSETS_DIR, "logo.jpg")
        caption = (
            f"🤖 **Бот жив!**\n"
            f"👤 **Владелец:** {OWNER}\n"
            f"📦 **Версия:** {VERSION}\n"
            f"⏱ **Аптайм:** `{get_uptime()}`"
        )
        try:
            if os.path.exists(logo_path):
                await client.send_file(event.chat_id, logo_path, caption=caption, parse_mode="markdown")
            else:
                await client.send_message(event.chat_id, caption, parse_mode="markdown")
        except Exception as e:
            logger.error(f"Alive error: {e}")
            await client.send_message(event.chat_id, caption, parse_mode="markdown")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.reload$"))
    async def reload_handler(event):
        frames = ["🔄", "🔄 🔄", "🔄 🔄 🔄", "♻️"]
        await animate_text(event, "Перезагрузка модулей", frames)
        try:
            reloaded = await reload_modules()   # await добавлен
            if reloaded:
                result = f"✅ Модули перезагружены: {', '.join(reloaded)}"
            else:
                result = "⚠️ Нет загруженных модулей для перезагрузки."
        except Exception as e:
            result = f"❌ Ошибка: {e}"
            logger.exception("Reload error")
        await finalize_command(event, result, delete_after=2)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.restart$"))
    async def restart_handler(event):
        frames = ["🔁", "🔁 🔁", "🔁 🔁 🔁", "🔄"]
        await animate_text(event, "Перезапуск", frames)
        await finalize_command(event, "🔄 Бот перезапускается...", delete_after=0.5)
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.stop$"))
    async def stop_handler(event):
        frames = ["⏹", "⏹ ⏹", "⏹ ⏹ ⏹", "🛑"]
        await animate_text(event, "Остановка", frames)
        await finalize_command(event, "🛑 Бот остановлен.", delete_after=0.5)
        await asyncio.sleep(1)
        try:
            from modules.time_name import shutdown as time_name_shutdown
            await time_name_shutdown()
        except Exception as e:
            logger.error(f"Не удалось восстановить имя при остановке: {e}")
        await client.disconnect()
        sys.exit(0)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.clear$"))
    async def clear_handler(event):
        frames = ["🧹", "🧹 🧹", "🧹 🧹 🧹", "🗑️"]
        await animate_text(event, "Очистка кеша и логов", frames)

        # Очистка кеша (папка cache/.nomedia)
        cache_dir = CACHE_DIR
        deleted_files = 0
        if os.path.exists(cache_dir):
            for f in os.listdir(cache_dir):
                file_path = os.path.join(cache_dir, f)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        deleted_files += 1
                except Exception as e:
                    logger.warning(f"Не удалось удалить {file_path}: {e}")

        # Рекурсивное удаление всех папок __pycache__ в корне проекта
        project_root = PROJECT_ROOT
        for root, dirs, files in os.walk(project_root):
            if root.endswith("__pycache__"):
                try:
                    shutil.rmtree(root)
                    logger.info(f"Удалена папка __pycache__: {root}")
                except Exception as e:
                    logger.warning(f"Не удалось удалить {root}: {e}")

        # Очистка логов
        log_path = LOG_PATH
        if os.path.exists(log_path):
            try:
                with open(log_path, "w") as f:
                    f.write("")
                logger.info("Лог-файл очищен")
            except Exception as e:
                logger.error(f"Ошибка очистки лога: {e}")

        result = f"✅ Очищено: {deleted_files} файлов кеша, все __pycache__ удалены, лог-файл очищен."
        await finalize_command(event, result, delete_after=2)

    logger.info(f"Диспетчер запущен, команд в реестре: {sum(len(v) for v in command_registry.values())}")