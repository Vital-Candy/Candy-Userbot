"""Встроенные команды userbot (.help, .stop). Подключаются при сборке приложения в app.py."""
from __future__ import annotations

from core.dispatcher import Dispatcher
from core.reply import answer
from utils.logger import logger


def register_commands(dispatcher: Dispatcher, stop_callback) -> None:
    """Регистрирует системные команды через новый dispatcher.

    ``stop_callback``: корутинная функция остановки приложения, её вызывает ``.stop``.
    """

    async def help_command(event) -> None:
        """Отвечает списком всех зарегистрированных команд с описаниями."""
        lines = ["🍬 Candy Userbot", ""]
        for command in dispatcher.command_help():
            usage = command.usage or f".{command.name}"
            description = command.description or "без описания"
            lines.append(f"{usage} — {description}")
        await answer(event, "\n".join(lines))

    async def stop_command(event) -> None:
        """Сообщает об остановке и вызывает ``stop_callback``."""
        # Ответ отправляем до остановки: после неё клиент уже отключён.
        await answer(event, "Остановка...")
        logger.info("Получена команда .stop")
        await stop_callback()

    dispatcher.register_command(
        "help",
        help_command,
        description="список команд",
        usage=".help",
        priority=100,
    )
    dispatcher.register_command(
        "stop",
        stop_command,
        description="остановить userbot",
        usage=".stop",
        priority=100,
    )
