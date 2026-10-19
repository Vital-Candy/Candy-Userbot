"""Модуль команды .restart: перезапуск userbot из Telegram.

Вызывать могут только пользователи с уровнем ADMIN. Сам перезапуск делает
``app.request_restart()`` (остановка модулей и повторный запуск процесса в main.py).
"""
from __future__ import annotations

from core.access import require
from core.module import Module
from core.reply import answer
from storage.permissions import PermissionLevel

USAGE = "Использование: .restart"

DETAILS = """\
Перезапускает userbot: модули корректно останавливаются (например, часы возвращают имя), затем процесс запускается заново. Полезно после смены .env или ручной правки файлов.

.restart — перезапустить

Права: администратор (владелец аккаунта им является всегда)."""


class RestartModule(Module):
    """Команда ``.restart``: корректный перезапуск процесса."""

    name = "system.restart"
    description = "Команда .restart: перезапуск userbot"
    # Необязательный: без него userbot работает, просто нет перезапуска из Telegram.

    async def start(self) -> None:
        """Регистрирует команду ``.restart`` (только для ADMIN)."""
        self.app.dispatcher.register_command(
            "restart",
            self.restart_command,
            description="перезапуск userbot",
            usage=".restart",
            priority=80,
            details=DETAILS,
            filters=(require(self.app, PermissionLevel.ADMIN),),
        )

    async def stop(self) -> None:
        """Снимает регистрацию команды ``.restart``."""
        self.app.dispatcher.unregister_command("restart")

    async def restart_command(self, event) -> None:
        """``.restart``: отвечает и просит приложение перезапуститься."""
        command = self.app.dispatcher.get_command(event)
        if command and command.args:
            await answer(event, USAGE)
            return
        await answer(event, "🔄 Перезапускаюсь...")
        await self.app.request_restart()
