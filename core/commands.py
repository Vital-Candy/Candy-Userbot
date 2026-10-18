"""Встроенные команды userbot (.help, .stop). Подключаются при сборке приложения в app.py.

``.help`` без аргументов даёт короткий список «команда — действие», а ``.help <команда>``
показывает полное описание из поля ``details`` этой команды (аргументы, примеры, права).
"""
from __future__ import annotations

import difflib

from core.dispatcher import Command, Dispatcher
from core.reply import answer
from utils.logger import logger

HELP_DETAILS = """\
Без аргументов показывает список всех команд и что они делают.
С именем команды (точку можно не писать) показывает полное описание: как пользоваться, какие бывают подкоманды и аргументы, кому доступна.

Примеры:
.help
.help label
.help account"""

STOP_DETAILS = """\
Штатно останавливает userbot: выгружает плагины и модули, сохраняет данные и отключается от Telegram.
Под run.sh после остановки бот не запустится сам. Чтобы запустить снова, выполните ./run.sh в терминале.

Права: только владелец аккаунта."""


def help_list(commands: list[Command]) -> str:
    """Короткий список команд: по строке «.имя — действие» и подсказка про подробную справку."""
    lines = ["🍬 Candy Userbot: команды", ""]
    for command in commands:
        lines.append(f".{command.name} — {command.description or 'без описания'}")
    lines += ["", "Подробнее: .help <команда>, например .help label"]
    return "\n".join(lines)


def help_command_text(command: Command) -> str:
    """Полная справка по одной команде: заголовок, использование и подробное описание."""
    lines = [f"📖 .{command.name} — {command.description or 'без описания'}"]
    lines.append(f"Использование: {command.usage or '.' + command.name}")
    if command.details:
        lines += ["", command.details]
    else:
        lines += ["", "Подробного описания у этой команды нет."]
    return "\n".join(lines)


def find_command(commands: list[Command], word: str) -> Command | None:
    """Команда по имени из запроса: без учёта регистра и с точкой или без неё."""
    name = word.strip().lower().lstrip(".")
    return next((command for command in commands if command.name == name), None)


def register_commands(dispatcher: Dispatcher, stop_callback) -> None:
    """Регистрирует системные команды через новый dispatcher.

    ``stop_callback``: корутинная функция остановки приложения, её вызывает ``.stop``.
    """

    async def help_command(event) -> None:
        """``.help`` показывает список, ``.help <команда>`` показывает полное описание."""
        commands = dispatcher.command_help()
        parsed = dispatcher.get_command(event)
        args = list(parsed.args) if parsed else []
        if not args:
            await answer(event, help_list(commands))
            return
        if len(args) > 1:
            await answer(event, "Использование: .help [команда]")
            return
        command = find_command(commands, args[0])
        if command is not None:
            await answer(event, help_command_text(command))
            return
        # Опечатку подсказываем: при похожем имени пользователь исправится сразу.
        name = args[0].strip().lower().lstrip(".")
        close = difflib.get_close_matches(name, [item.name for item in commands], n=3, cutoff=0.6)
        hint = ("Похожие: " + ", ".join("." + item for item in close) + ". ") if close else ""
        await answer(event, f"❌ Команды .{name} нет. {hint}Список: .help")

    async def stop_command(event) -> None:
        """Сообщает об остановке и вызывает ``stop_callback``."""
        # Ответ отправляем до остановки: после неё клиент уже отключён.
        await answer(event, "Остановка...")
        logger.info("Получена команда .stop")
        await stop_callback()

    dispatcher.register_command(
        "help",
        help_command,
        description="список команд и справка по каждой",
        usage=".help [команда]",
        priority=100,
        details=HELP_DETAILS,
    )
    dispatcher.register_command(
        "stop",
        stop_command,
        description="остановить userbot",
        usage=".stop",
        priority=100,
        details=STOP_DETAILS,
    )
