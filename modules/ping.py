import time

from telethon import events

import core.client as client_state
from core.dispatcher import register_command

_handler = None


def init() -> None:
    global _handler

    if client_state.client is None:
        raise RuntimeError("TelegramClient не установлен")

    register_command(
        "ping",
        "Проверить задержку",
        ".ping",
        "Инструменты",
    )
    _handler = client_state.client.add_event_handler(
        handler,
        events.NewMessage(
            outgoing=True,
            pattern=r"^\.ping$",
        ),
    )


def shutdown() -> None:
    global _handler

    if client_state.client is not None and _handler is not None:
        client_state.client.remove_event_handler(
            _handler
        )
    _handler = None


async def handler(event) -> None:
    started = time.perf_counter()
    await event.edit("🏓 Ping...")
    milliseconds = (
        time.perf_counter() - started
    ) * 1000

    await event.edit(
        "🏓 <b>Pong!</b> "
        f"<code>{milliseconds:.0f} ms</code>",
        parse_mode="html",
    )
