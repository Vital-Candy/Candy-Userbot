"""Модуль команды .account.

Синтаксис: ``.account [list]`` и ``.account use <id|@имя>``. Команду вызывает владелец
аккаунта (отдельный фильтр прав не задан); логика выбора аккаунтов живёт в accounts/control.py.
"""
from __future__ import annotations

from core.errors import UserError
from core.module import Module
from core.reply import answer

USAGE = "Использование: .account [list] | .account use <id|@имя>"

DETAILS = """\
Показывает сохранённые Telegram-аккаунты и переключает активный. Одновременно работает один аккаунт.

.account — список аккаунтов (● активный, ○ остальные)
.account list — то же самое
.account use <id|@имя> — сделать аккаунт активным; userbot перезапустится уже под ним

Аккаунт можно указать числовым ID или @username (как в списке).
Новый аккаунт добавляют в терминале: python main.py --add-account

Права: только владелец аккаунта."""


class AccountsModule(Module):
    """Команда ``.account``: список аккаунтов и переключение активного."""

    name = "system.accounts"
    required = True  # системный модуль: сбой запуска останавливает userbot
    description = "Команда .account: список и переключение аккаунтов"

    async def start(self) -> None:
        """Регистрирует команду ``.account``."""
        self.app.dispatcher.register_command(
            "account",
            self.account_command,
            description="аккаунты: список и переключение",
            usage=".account [list | use <id|@имя>]",
            priority=90,
            details=DETAILS,
        )

    async def stop(self) -> None:
        """Снимает регистрацию команды ``.account``."""
        self.app.dispatcher.unregister_command("account")

    async def account_command(self, event) -> None:
        """Обрабатывает ``.account``; ошибки выбора аккаунта отвечает текстом, не пробрасывает."""
        command = self.app.dispatcher.get_command(event)
        args = command.args if command else ()
        control = self.app.account_control

        if not args or args[0].lower() == "list":
            await answer(event, "👤 Аккаунты:\n" + control.describe())
            return

        if args[0].lower() == "use" and len(args) == 2:
            try:
                account = control.resolve(args[1])
                current = self.app.account
                if current is not None and account.account_id == current.account_id:
                    raise ValueError(f"аккаунт {account.display_name} уже активен")
                await answer(event, 
                    f"🔄 Переключаюсь на {account.display_name}. Userbot перезапустится."
                )
                # Ответ отправляем до переключения: после него userbot перезапускается.
                await self.app.switch_account(args[1])
            except (LookupError, ValueError, UserError) as exc:
                await answer(event, f"❌ {exc}")
            return

        await answer(event, USAGE)
