# core/dispatcher.py
"""
Диспетчер встроенных команд.

Этап 2: setup_dispatcher(raw_client, ctx) — принимает явный клиент и контекст.
Handlers сохраняются в ctx.handlers для чистого teardown при смене аккаунта.
"""
from __future__ import annotations
import asyncio, logging, os, shutil, sys, time
from telethon import events
from config import VERSION, OWNER
from utils.paths import ASSETS_DIR, CACHE_DIR, LOG_PATH, PROJECT_ROOT

logger = logging.getLogger("dispatcher")

command_registry: dict[str, dict] = {}
_start_time: float = time.time()


# ── Реестр ────────────────────────────────────────────────────────────

def register_command(name, description, usage, details="", category="other"):
    command_registry.setdefault(category, {})[name] = {
        "description": description, "usage": usage, "details": details,
    }

def reset_uptime():
    global _start_time; _start_time = time.time()

def get_uptime() -> str:
    s = int(time.time() - _start_time)
    h, s = divmod(s, 3600); m, s = divmod(s, 60)
    return f"{h}ч {m}м {s}с"

def _emoji(cat):
    return {"система":"⚙️","инструменты":"🔧","дизайн":"🎨","приколы":"😄"}.get(cat,"📦")

async def animate_text(event, text, frames, delay=0.3):
    try:
        for f in frames: await event.edit(f"{text} {f}"); await asyncio.sleep(delay)
    except Exception: pass

async def finalize_command(event, text, delete_after=2):
    try:
        await event.edit(text); await asyncio.sleep(delete_after); await event.delete()
    except Exception: pass


# ── Setup / Teardown ──────────────────────────────────────────────────

def setup_dispatcher(raw_client, ctx) -> None:
    """
    Регистрирует встроенные команды на raw_client.
    Handlers сохраняются в ctx.handlers.

    Этап 2: каждый аккаунт имеет свой набор handlers в ctx.
    """
    from core.loader import reload_modules

    command_registry.clear()

    register_command("ping",    "Проверка задержки",             ".ping",           category="система")
    register_command("help",    "Список команд / справка",       ".help [команда]", category="система")
    register_command("alive",   "Статус бота",                   ".alive",          category="система")
    register_command("reload",  "Горячая перезагрузка модулей",  ".reload",         category="система")
    register_command("restart", "Перезапустить процесс",         ".restart",        category="система")
    register_command("stop",    "Остановить → меню",             ".stop",           category="система")
    register_command("clear",   "Очистить кеш и логи",           ".clear",          category="система")
    register_command("backup",  "Бэкап аккаунта",                ".backup",         category="система")
    register_command("accounts","Список аккаунтов",              ".accounts",       category="система")

    # ── Handlers ──────────────────────────────────────────────────────

    async def ping_handler(event):
        t = time.time(); await event.edit("🏓 Pong!")
        await event.edit(f"🏓 Pong! `{round((time.time()-t)*1000,2)}ms`")

    async def help_handler(event):
        arg = event.pattern_match.group(1)
        if arg:
            cmd = arg.strip().lower()
            for cmds in command_registry.values():
                if cmd in cmds:
                    c = cmds[cmd]
                    txt = f"**📖 Команда:** `{cmd}`\n**Описание:** {c['description']}\n**Использование:** `{c['usage']}`\n"
                    if c.get("details"): txt += f"**Подробнее:** {c['details']}\n"
                    return await event.edit(txt)
            return await event.edit(f"❌ Команда `{cmd}` не найдена.")
        txt = f"**✨ Candy Userbot v{VERSION} | {OWNER}**\n\n"
        order = ["система","инструменты","дизайн","приколы"]
        for cat in order + [c for c in command_registry if c not in order]:
            cmds = command_registry.get(cat, {})
            if not cmds: continue
            txt += f"**{_emoji(cat)}  {cat.upper()}**\n"
            for n, i in cmds.items(): txt += f"• `{n}` — {i['description']}\n"
            txt += "\n"
        txt += "_Подробнее: `.help <команда>`_"
        await event.edit(txt)

    async def alive_handler(event):
        await event.delete()
        logo = ASSETS_DIR / "logo.jpg"
        cap  = f"🤖 **Бот жив!**\n👤 **Аккаунт:** {ctx.display_name}\n📦 **Версия:** {VERSION}\n⏱ **Аптайм:** `{get_uptime()}`"
        try:
            if logo.exists(): await raw_client.send_file(event.chat_id, str(logo), caption=cap, parse_mode="markdown")
            else:              await raw_client.send_message(event.chat_id, cap, parse_mode="markdown")
        except Exception as e: logger.error(f"alive: {e}")

    async def reload_handler(event):
        await animate_text(event, "Перезагрузка", ["🔄","🔄 🔄","🔄 🔄 🔄","♻️"])
        try:
            loaded = await reload_modules(raw_client, ctx)
            result = f"✅ Перезагружены: {', '.join(loaded)}" if loaded else "⚠️ Нет модулей."
        except Exception as e: result = f"❌ Ошибка: {e}"
        await finalize_command(event, result, delete_after=2)

    async def restart_handler(event):
        await animate_text(event, "Перезапуск", ["🔁","🔁 🔁","🔁 🔁 🔁","🔄"])
        await finalize_command(event, "🔄 Перезапускаю...", delete_after=0.5)
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    async def stop_handler(event):
        await animate_text(event, "Остановка", ["⏹","⏹ ⏹","⏹ ⏹ ⏹","🛑"])
        await finalize_command(event, "🛑 Возвращаюсь в меню...", delete_after=0.5)
        await asyncio.sleep(1)
        try:
            from modules.time_name import shutdown as tn_shutdown
            await tn_shutdown()
        except Exception: pass
        if raw_client.is_connected():
            await raw_client.disconnect()

    async def clear_handler(event):
        await animate_text(event, "Очистка", ["🧹","🧹 🧹","🧹 🧹 🧹","🗑️"])
        deleted = 0
        if CACHE_DIR.exists():
            for f in CACHE_DIR.iterdir():
                if f.is_file() and f.name != ".nomedia":
                    try: f.unlink(); deleted += 1
                    except Exception: pass
        for root, dirs, _ in os.walk(PROJECT_ROOT):
            for d in dirs:
                if d == "__pycache__":
                    try: shutil.rmtree(os.path.join(root, d))
                    except Exception: pass
        if LOG_PATH.exists():
            try: LOG_PATH.write_text("")
            except Exception: pass
        await finalize_command(event, f"✅ Удалено {deleted} файлов, __pycache__, лог очищен.", delete_after=2)

    async def backup_handler(event):
        from core.accounts import backup_account
        import json as _j
        msg = await event.edit("💾 Создаю бэкап...")
        try:
            from utils.paths import ACCOUNTS_DIR
            identifier = ctx.username or str(ctx.telegram_id or "unknown")
            pp = ACCOUNTS_DIR / identifier / "profile.json"
            if not pp.exists(): return await msg.edit("❌ Профиль не найден")
            profile = _j.loads(pp.read_text(encoding="utf-8"))
            path = backup_account(profile)
            await msg.edit(f"✅ Бэкап создан!\n\n📁 `{path}`")
        except Exception as e: await msg.edit(f"❌ Ошибка:\n`{e}`")

    async def accounts_handler(event):
        from core.account_manager import account_manager
        lines = ["**👥 Аккаунты:**\n"]
        for c in account_manager.all():
            status = "🟢" if c.is_running() else "🔴"
            active = " ← активный" if c.account_id == (account_manager.active or AccountContext).account_id else ""
            lines.append(f"{status} {c.display_name}{active}")
        await event.edit("\n".join(lines) if len(lines) > 1 else "❌ Нет аккаунтов")

    # ── Регистрация — handlers в ctx.handlers ─────────────────────────
    def _add(fn, pat):
        h = raw_client.add_event_handler(fn, events.NewMessage(outgoing=True, pattern=pat))
        ctx.handlers.append(h)

    _add(ping_handler,     r"^\.ping$")
    _add(help_handler,     r"^\.help(?: (.+))?")
    _add(alive_handler,    r"^\.alive$")
    _add(reload_handler,   r"^\.reload$")
    _add(restart_handler,  r"^\.restart$")
    _add(stop_handler,     r"^\.stop$")
    _add(clear_handler,    r"^\.clear$")
    _add(backup_handler,   r"^\.backup$")
    _add(accounts_handler, r"^\.accounts$")

    logger.info(f"[{ctx.display_name}] dispatcher: {sum(len(v) for v in command_registry.values())} команд")


def teardown_dispatcher(ctx) -> None:
    """Снимает все handlers диспетчера с аккаунта."""
    ctx.remove_all_handlers()
    command_registry.clear()
    logger.info(f"[{ctx.display_name}] dispatcher остановлен")
