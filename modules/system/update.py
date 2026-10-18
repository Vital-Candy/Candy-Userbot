"""Модуль команды .update.

Синтаксис: ``.update`` (проверить и установить) и ``.update check`` (только проверить).
Вызывать могут только пользователи с уровнем ADMIN. Сама установка: core/updater.py.
"""
from __future__ import annotations

from core.access import require
from core.errors import UserError
from core.module import Module
from core.reply import answer
from storage.permissions import PermissionLevel
from utils.logger import logger

USAGE = "Использование:\n.update — проверить и установить обновление\n.update check — только проверить"


DETAILS = """\
Обновление userbot из репозитория GitHub (по умолчанию ветка main, сменить можно в .env: CANDY_UPDATE_REPO и CANDY_UPDATE_BRANCH).

.update — проверить версию и, если есть новая, скачать и установить; после установки userbot сам перезапустится
.update check — только проверить, ничего не устанавливая

Версию понижать нельзя: если на сервере версия ниже или равна вашей, обновления не будет.
Не затрагиваются: data, logs, plugins, .env и ваш logo.txt. Прежние файлы сохраняются в data/update; если установка не удалась, всё возвращается назад.
Если изменился requirements.txt, в ответе будет напоминание выполнить pip install -r requirements.txt.

Права: администратор (владелец аккаунта им является всегда)."""


def describe(info) -> str:
    """Текст о результате проверки версии по ``info.state`` (newer/current/иначе: на сервере ниже)."""
    if info.state == "newer":
        return f"🆕 Доступна версия {info.remote} (сейчас {info.local})."
    if info.state == "current":
        return f"✅ Установлена последняя версия: {info.local}."
    return (
        f"ℹ️ На сервере версия {info.remote} ниже установленной ({info.local}). "
        "Понижать версию нельзя, обновление не требуется."
    )


class UpdateModule(Module):
    """Команда ``.update``: проверка и установка обновления."""

    name = "system.update"
    description = "Команда .update: обновление из GitHub"
    # Необязательный: без него userbot работает, просто нет обновления из Telegram.

    async def start(self) -> None:
        """Регистрирует команду ``.update`` (только для ADMIN)."""
        self.app.dispatcher.register_command(
            "update",
            self.update_command,
            description="обновление из GitHub",
            usage=".update [check]",
            priority=90,
            details=DETAILS,
            filters=(require(self.app, PermissionLevel.ADMIN),),
        )

    async def stop(self) -> None:
        """Снимает регистрацию команды ``.update``."""
        self.app.dispatcher.unregister_command("update")

    async def update_command(self, event) -> None:
        """``.update`` ставит обновление, ``.update check`` только проверяет; после установки просит рестарт."""
        command = self.app.dispatcher.get_command(event)
        args = [item.lower() for item in (command.args if command else [])]
        if args not in ([], ["check"]):
            await answer(event, USAGE)
            return
        try:
            await answer(event, "🔄 Проверяю обновления...")
            info = await self.app.check_update()
            if not info.available or args == ["check"]:
                await answer(event, describe(info))
                return
            await answer(event, f"⬇️ Скачиваю версию {info.remote}...")
            result = await self.app.install_update(info)
        except UserError as exc:
            await answer(event, f"❌ {exc}")
            return
        # Широкий except намеренный: любой сбой сети/распаковки не должен ронять обработчик команды.
        except Exception:
            logger.exception("Ошибка обновления.")
            await answer(event, "❌ Обновление не удалось. Подробности в логе.")
            return

        text = f"✅ Обновлено: {result.old} → {result.new} (файлов: {result.files}). Перезапускаюсь..."
        if result.notes:
            text += "\n⚠️ " + "\n⚠️ ".join(result.notes)
        await answer(event, text)
        await self.app.request_restart()
