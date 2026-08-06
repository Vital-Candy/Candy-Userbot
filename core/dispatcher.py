from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time

from telethon import events

from config import OWNER, VERSION
from utils.paths import ASSETS_DIR, PROJECT_ROOT

_registry: dict[str, tuple[str, str, str]] = {}
_started = time.monotonic()

CATEGORY_ICONS = {
    "Система": "⚙️",
    "Инструменты": "🛠️",
    "Информация": "ℹ️",
    "Профиль": "👤",
    "Безопасность": "🛡️",
}


def register_command(
    name: str,
    description: str,
    usage: str,
    category: str = "Система",
) -> None:
    _registry[name.lower()] = (
        description,
        usage,
        category,
    )


def setup(client, on_stop: asyncio.Event) -> None:
    register_command(
        "help",
        "Список команд",
        ".help [команда]",
    )
    register_command(
        "alive",
        "Статус userbot",
        ".alive",
    )
    register_command(
        "reload",
        "Перезагрузить модули",
        ".reload",
    )
    register_command(
        "restart",
        "Перезапустить userbot",
        ".restart",
    )
    register_command(
        "stop",
        "Остановить и вернуться в меню",
        ".stop",
    )
    register_command(
        "clear",
        "Очистить кеш и лог",
        ".clear",
    )

    @client.on(
        events.NewMessage(
            outgoing=True,
            pattern=r"^\.help(?:\s+(.+))?$",
        )
    )
    async def help_cmd(event):
        arg = (
            event.pattern_match.group(1) or ""
        ).strip().lower()

        if arg:
            item = _registry.get(arg)
            if not item:
                await event.edit("❌ Команда не найдена")
                return

            await event.edit(
                f"🍬 <b>.{arg}</b>\n"
                f"{item[0]}\n"
                f"Использование: "
                f"<code>{item[1]}</code>",
                parse_mode="html",
            )
            return

        groups: dict[str, list[tuple[str, str]]] = {}
        for name, (description, _, category) in (
            _registry.items()
        ):
            groups.setdefault(category, []).append(
                (name, description)
            )

        text = "🍬 <b>Candy-Userbot — команды</b>\n"

        for category in sorted(groups):
            icon = CATEGORY_ICONS.get(category, "📁")

            text += f"\n{icon} <b>{category}</b>\n"

            for name, description in sorted(groups[category]):
                text += (
                    f"• <code>.{name}</code> — "
                    f"{description}\n"
                )

        await event.edit(
            text,
            parse_mode="html",
        )

    @client.on(
        events.NewMessage(
            outgoing=True,
            pattern=r"^\.alive$",
        )
    )
    async def alive(event):
        uptime = int(
            time.monotonic() - _started
        )
        text = (
            "🍬 <b>Candy-Userbot</b>\n"
            f"Версия: <code>{VERSION}</code>\n"
            f"Владелец: {OWNER}\n"
            "Аптайм: "
            f"<code>{uptime // 3600:02}:"
            f"{uptime % 3600 // 60:02}:"
            f"{uptime % 60:02}</code>"
        )

        logo = ASSETS_DIR / "logo.jpg"
        if logo.is_file() and os.access(
            logo,
            os.R_OK,
        ):
            await event.client.send_file(
                event.chat_id,
                logo,
                caption=text,
                parse_mode="html",
            )
            await event.delete()
        else:
            await event.edit(
                text,
                parse_mode="html",
            )

    @client.on(
        events.NewMessage(
            outgoing=True,
            pattern=r"^\.reload$",
        )
    )
    async def reload_cmd(event):
        await event.edit("🔄 Перезагрузка...")
        from core.loader import reload_modules

        names = await reload_modules()
        await event.edit(
            f"✅ Загружено модулей: {len(names)}"
        )

    @client.on(
        events.NewMessage(
            outgoing=True,
            pattern=r"^\.restart$",
        )
    )
    async def restart(event):
        await event.edit("🔄 Перезапуск...")
        await event.client.disconnect()
        os.execv(
            sys.executable,
            [sys.executable] + sys.argv,
        )

    @client.on(
        events.NewMessage(
            outgoing=True,
            pattern=r"^\.clear$",
        )
    )
    async def clear(event):
        for path in PROJECT_ROOT.rglob(
            "__pycache__"
        ):
            shutil.rmtree(
                path,
                ignore_errors=True,
            )

        (PROJECT_ROOT / "userbot.log").write_text(
            "",
            encoding="utf-8",
        )
        await event.edit(
            "✅ Кеш Python и лог очищены"
        )

    @client.on(
        events.NewMessage(
            outgoing=True,
            pattern=r"^\.stop$",
        )
    )
    async def stop(event):
        await event.edit(
            "🛑 Возвращаюсь в меню..."
        )
        on_stop.set()
