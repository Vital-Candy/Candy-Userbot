"""Модуль команды .backup.

Синтаксис: ``.backup create [id|@имя]``, ``.backup list``, ``.backup restore <файл.zip>``.
Команду вызывает владелец аккаунта (отдельный фильтр прав не задан); архивы собирает
accounts/backup.py через accounts/control.py.
"""
from __future__ import annotations

from core.errors import UserError
from core.module import Module
from core.reply import answer

USAGE = "Использование: .backup create [id|@имя] | .backup list | .backup restore <файл.zip>"

DETAILS = """\
Резервные копии аккаунтов (сессия и профиль в zip-архиве, папка data/backups).

.backup create — архив активного аккаунта
.backup create <id|@имя> — архив другого сохранённого аккаунта
.backup list — список архивов
.backup restore <файл.zip> — восстановить аккаунт из архива (имя файла из .backup list)

Восстановление не перезаписывает существующий аккаунт и не переключает на него: после него выполните .account use <id>.
Архив содержит сессию Telegram, храните его в секрете.

Права: только владелец аккаунта."""


class BackupModule(Module):
    """Команда ``.backup``: создание, список и восстановление резервных копий аккаунтов."""

    name = "system.backup"
    required = True  # системный модуль: сбой запуска останавливает userbot
    description = "Команда .backup: резервные копии аккаунтов"

    async def start(self) -> None:
        """Регистрирует команду ``.backup``."""
        self.app.dispatcher.register_command(
            "backup",
            self.backup_command,
            description="резервные копии аккаунтов",
            usage=".backup create [id|@имя] | list | restore <файл.zip>",
            priority=90,
            details=DETAILS,
        )

    async def stop(self) -> None:
        """Снимает регистрацию команды ``.backup``."""
        self.app.dispatcher.unregister_command("backup")

    async def backup_command(self, event) -> None:
        """Обрабатывает ``.backup``; ошибки файла и аккаунта отвечает текстом."""
        command = self.app.dispatcher.get_command(event)
        args = command.args if command else ()
        control = self.app.account_control
        action = args[0].lower() if args else ""

        try:
            if action == "create" and len(args) <= 2:
                path = control.backup_create(args[1] if len(args) == 2 else None)
                await answer(event, 
                    f"💾 Backup создан: {path.name}\n"
                    "Архив содержит сессию аккаунта. Храните его в секрете."
                )
            elif action == "list" and len(args) == 1:
                files = control.backup_list()
                if not files:
                    await answer(event, "💾 Backup-ов пока нет.")
                else:
                    await answer(event, "💾 Backup-ы:\n" + "\n".join(f.name for f in files))
            elif action == "restore" and len(args) == 2:
                account = control.backup_restore(args[1])
                await answer(event, 
                    f"✅ Аккаунт {account.display_name} восстановлен. "
                    f"Переключиться: .account use {account.account_id}"
                )
            else:
                await answer(event, USAGE)
        except FileNotFoundError:
            await answer(event, "❌ Файл backup не найден.")
        except (LookupError, ValueError, FileExistsError, UserError) as exc:
            await answer(event, f"❌ {exc}")
