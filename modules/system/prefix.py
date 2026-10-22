"""Модуль команды .setprefix: смена префикса команд (по умолчанию точка).

Префикс хранится отдельно для каждого аккаунта в plugin_data и применяется при запуске.
Менять его может только владелец аккаунта.
"""
from __future__ import annotations

from core.module import Module
from core.reply import answer
from utils.logger import logger

DEFAULT_PREFIX = "."
MAX_PREFIX_LENGTH = 3
PLUGIN = "core.prefix"
KEY = "prefix"
USAGE = "Использование: .setprefix [символ | reset]"

DETAILS = f"""\
Показывает или меняет символ, с которого начинаются команды (по умолчанию точка).

.setprefix — показать текущий префикс
.setprefix <символ> — задать новый, например .setprefix !
.setprefix reset — вернуть точку

Префикс: от 1 до {MAX_PREFIX_LENGTH} символов, без пробелов, букв, цифр и знака @. После смены пишите команды с новым символом (например !help). В справке .help имена команд показываются с новым префиксом; в подсказках внутри других ответов может остаться точка. Префикс хранится отдельно для каждого аккаунта и сохраняется после перезапуска.

Права: только владелец аккаунта."""


def validate_prefix(value: str) -> str:
    """Проверяет префикс; при ошибке бросает ``ValueError`` с понятным текстом."""
    if not 1 <= len(value) <= MAX_PREFIX_LENGTH:
        raise ValueError(f"префикс должен быть от 1 до {MAX_PREFIX_LENGTH} символов")
    for char in value:
        if char.isspace() or char.isalnum() or char == "@" or not char.isprintable():
            raise ValueError("префикс не может содержать пробелы, буквы, цифры и знак @")
    return value


class PrefixModule(Module):
    """Команда ``.setprefix``: показывает и меняет префикс команд."""

    name = "system.prefix"
    description = "Команда .setprefix: префикс команд"
    # Необязательный: без него userbot работает с точкой.

    def __init__(self, app) -> None:
        super().__init__(app)
        self._account_id: int | None = None

    async def start(self) -> None:
        """Применяет сохранённый префикс аккаунта и регистрирует команду."""
        self._account_id = await self.app.identity.account_id()
        saved = self.app.storage.plugin_data.get(account_id=self._account_id, plugin=PLUGIN, key=KEY)
        if isinstance(saved, str):
            try:
                self.app.dispatcher.parser.prefix = validate_prefix(saved)
            except ValueError:
                logger.warning("Сохранённый префикс '%s' недопустим, используется точка.", saved)
        self.app.dispatcher.register_command(
            "setprefix",
            self.setprefix_command,
            description="показать или сменить префикс команд",
            usage=".setprefix [символ | reset]",
            priority=50,
            details=DETAILS,
        )

    async def stop(self) -> None:
        """Снимает регистрацию команды ``.setprefix``."""
        self.app.dispatcher.unregister_command("setprefix")

    async def setprefix_command(self, event) -> None:
        """``.setprefix``: показать, ``.setprefix <символ>``: задать, ``.setprefix reset``: вернуть точку."""
        command = self.app.dispatcher.get_command(event)
        args = list(command.args) if command else []
        parser = self.app.dispatcher.parser
        if not args:
            await answer(event, f"🔧 Префикс команд: {parser.prefix}\nСменить: {parser.prefix}setprefix <символ>")
            return
        if len(args) > 1:
            await answer(event, USAGE)
            return
        wanted = DEFAULT_PREFIX if args[0].lower() == "reset" else args[0]
        try:
            new = validate_prefix(wanted)
        except ValueError as exc:
            await answer(event, f"❌ {exc}")
            return
        plugin_data = self.app.storage.plugin_data
        if new == DEFAULT_PREFIX:
            plugin_data.delete(account_id=self._account_id, plugin=PLUGIN, key=KEY)
        else:
            plugin_data.set(account_id=self._account_id, plugin=PLUGIN, key=KEY, value=new)
        parser.prefix = new
        await answer(event, f"✅ Префикс команд: {new}\nВернуть точку: {new}setprefix reset")
