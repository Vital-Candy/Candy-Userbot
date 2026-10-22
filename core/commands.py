"""Встроенные команды userbot (.help, .stop). Подключаются при сборке приложения в app.py.

``.help`` без аргументов даёт короткий список «команда — действие», а ``.help <команда>``
показывает полное описание из поля ``details`` этой команды (аргументы, примеры, права).
"""
from __future__ import annotations

import difflib
import re

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


def with_prefix(text: str, prefix: str, names) -> str:
    """Заменяет точку перед именами известных команд на текущий префикс (если он не точка)."""
    names = sorted((re.escape(name) for name in names), key=len, reverse=True)
    if prefix == "." or not names:
        return text
    pattern = re.compile(r"(?<![\w.])\.(" + "|".join(names) + r")\b")
    return pattern.sub(lambda match: prefix + match.group(1), text)


def help_list(commands: list[Command], prefix: str = ".") -> str:
    """Короткий список команд: по строке «.имя — действие» и подсказка про подробную справку."""
    lines = ["🍬 Candy Userbot: команды", ""]
    for command in commands:
        lines.append(f".{command.name} — {command.description or 'без описания'}")
    lines += ["", "Подробнее: .help <команда>, например .help label"]
    return with_prefix("\n".join(lines), prefix, [command.name for command in commands])


def help_command_text(command: Command, prefix: str = ".", names=()) -> str:
    """Полная справка по одной команде: заголовок, использование и подробное описание."""
    return with_prefix(_command_text(command), prefix, set(names) | {command.name})


def _command_text(command: Command) -> str:
    """Справка по команде с точкой в качестве префикса."""
    lines = [f"📖 .{command.name} — {command.description or 'без описания'}"]
    lines.append(f"Использование: {command.usage or '.' + command.name}")
    if command.details:
        lines += ["", command.details]
    else:
        lines += ["", "Подробного описания у этой команды нет."]
    return "\n".join(lines)


def find_command(commands: list[Command], word: str, prefix: str = ".") -> Command | None:
    """Команда по имени из запроса: без учёта регистра и с префиксом или без него."""
    name = word.strip().lower().lstrip(".").lstrip(prefix)
    return next((command for command in commands if command.name == name), None)


def register_commands(dispatcher: Dispatcher, stop_callback) -> None:
    """Регистрирует системные команды через новый dispatcher.

    ``stop_callback``: корутинная функция остановки приложения, её вызывает ``.stop``.
    """

    async def help_command(event) -> None:
        """``.help`` показывает список, ``.help <команда>`` показывает полное описание."""
        commands = dispatcher.command_help()
        prefix = dispatcher.parser.prefix
        names = [item.name for item in commands]
        parsed = dispatcher.get_command(event)
        args = list(parsed.args) if parsed else []
        if not args:
            await answer(event, help_list(commands, prefix))
            return
        if len(args) > 1:
            await answer(event, "Использование: .help [команда]")
            return
        command = find_command(commands, args[0], prefix)
        if command is not None:
            await answer(event, help_command_text(command, prefix, names))
            return
        # Опечатку подсказываем: при похожем имени пользователь исправится сразу.
        name = args[0].strip().lower().lstrip(".").lstrip(prefix)
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
