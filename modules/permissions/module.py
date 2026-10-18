"""Модуль команды .perm.

Синтаксис: ``.perm list [id]``, ``.perm grant <id | ответом> <trusted|admin>``,
``.perm revoke <id | ответом> [trusted|admin]``. Вызывать могут только пользователи с уровнем
ADMIN (владелец всегда ADMIN). Данные хранит storage/permissions.py.
"""
from __future__ import annotations

import sqlite3

from core.access import require
from core.module import Module
from core.reply import answer
from storage.permissions import PermissionLevel
from utils.logger import logger

USAGE = (
    "Использование:\n"
    ".perm list [id]\n"
    ".perm grant <id | ответом> <trusted|admin>\n"
    ".perm revoke <id | ответом> [trusted|admin]"
)
DETAILS = """\
Права других пользователей. Уровни: user (по умолчанию, без прав) < trusted (доверенный) < admin (администратор: .update, .plugin, .perm и другие закрытые команды). Владелец аккаунта всегда admin, его права менять нельзя.

.perm list — все выданные права
.perm list <id> — уровень и права одного пользователя
.perm grant <id> <trusted|admin> — выдать уровень
.perm revoke <id> — снять все права
.perm revoke <id> <trusted|admin> — снять один уровень

Вместо ID можно ответить командой на сообщение человека: .perm grant trusted. Имена @username не поддерживаются, нужен числовой ID.

Права: администратор (владелец аккаунта им является всегда)."""
GRANTABLE = (PermissionLevel.TRUSTED, PermissionLevel.ADMIN)


class PermissionsModule(Module):
    """Команда ``.perm``: выдача и снятие уровней доступа trusted/admin для других пользователей."""

    name = "permissions"
    description = "Команда .perm: уровни доступа пользователей"

    async def start(self) -> None:
        """Регистрирует команду ``.perm`` (только для ADMIN)."""
        self.app.dispatcher.register_command(
            "perm",
            self.perm_command,
            description="права доступа пользователей",
            usage=".perm list [id] | grant <id> <уровень> | revoke <id> [уровень]",
            priority=40,
            details=DETAILS,
            # Команда управляет доступом, поэтому только ADMIN (владелец всегда им является).
            filters=(require(self.app, PermissionLevel.ADMIN),),
        )

    async def stop(self) -> None:
        """Снимает регистрацию команды ``.perm``."""
        self.app.dispatcher.unregister_command("perm")

    async def perm_command(self, event) -> None:
        """Разбирает ``.perm`` и вызывает list/grant/revoke; ошибки ввода и БД отвечает текстом."""
        command = self.app.dispatcher.get_command(event)
        args = list(command.args) if command else []
        action = args[0].lower() if args else ""
        try:
            if action == "list" and len(args) <= 2:
                await self._list(event, args[1:])
            elif action == "grant" and 1 <= len(args) <= 3:
                await self._grant(event, args[1:])
            elif action == "revoke" and 1 <= len(args) <= 3:
                await self._revoke(event, args[1:])
            else:
                await answer(event, USAGE)
        except ValueError as exc:
            await answer(event, f"❌ {exc}")
        except sqlite3.Error:
            logger.exception("Ошибка базы данных в .perm")
            await answer(event, "❌ Ошибка базы данных.")

    # ----------------------------------------------------------------- actions

    async def _list(self, event, rest: list[str]) -> None:
        """``.perm list [id]``: все выданные права аккаунта либо права одного пользователя."""
        account_id = await self.app.access.account_id()
        store = self.app.storage.permissions
        if rest:
            subject = int(await self._subject(event, rest[0], allow_reply=False))
            items = store.list_for_subject(account_id=account_id, subject_id=subject)
            level = await self.app.access.level_of(subject)
            head = f"👤 {subject}: {level.value}"
        else:
            items = store.list_all(account_id=account_id)
            head = "🔐 Выданные права:"
        lines = [head]
        if rest and not items:
            lines.append("записей нет")
        elif not rest and not items:
            lines = ["🔐 Права пока никому не выданы. Вы (владелец) всегда admin."]
        for item in items:
            lines.append(f"{item.subject_id} — {item.permission}")
        await answer(event, "\n".join(lines))

    async def _grant(self, event, rest: list[str]) -> None:
        """``.perm grant``: выдаёт уровень; на самого владельца права не выдаются."""
        subject, level = await self._subject_and_level(event, rest, need_level=True)
        account_id = await self.app.access.account_id()
        if subject == account_id:
            raise ValueError("аккаунт и так имеет уровень admin")
        self.app.storage.permissions.grant(
            account_id=account_id, subject_id=subject, permission=level, granted_by=account_id
        )
        await answer(event, f"✅ {subject}: выдан уровень {level.value}.")

    async def _revoke(self, event, rest: list[str]) -> None:
        """``.perm revoke``: снимает один уровень или все права; права владельца снять нельзя."""
        subject, level = await self._subject_and_level(event, rest, need_level=False)
        account_id = await self.app.access.account_id()
        if subject == account_id:
            raise ValueError("права владельца снять нельзя")
        store = self.app.storage.permissions
        if level is None:
            removed = store.revoke_all(account_id=account_id, subject_id=subject)
            text = f"✅ {subject}: все права сняты." if removed else f"❌ У {subject} нет выданных прав."
        else:
            done = store.revoke(account_id=account_id, subject_id=subject, permission=level)
            text = (
                f"✅ {subject}: уровень {level.value} снят."
                if done
                else f"❌ У {subject} нет уровня {level.value}."
            )
        await answer(event, text)

    # ----------------------------------------------------------------- parsing

    async def _subject_and_level(self, event, rest: list[str], *, need_level: bool):
        """Разбирает ``[<id>] [<уровень>]``: без id берётся автор сообщения, на которое ответили."""
        # Уровень ищем в конце списка: id необязателен (при reply), уровень всегда последний.
        level: PermissionLevel | None = None
        words = list(rest)
        if words and self._parse_level(words[-1]) is not None:
            level = self._parse_level(words.pop())
        if len(words) > 1:
            raise ValueError("слишком много аргументов")
        if need_level and level is None:
            raise ValueError("укажите уровень: trusted или admin")
        if level is not None and level not in GRANTABLE:
            raise ValueError("доступны уровни trusted и admin")
        subject = await self._subject(event, words[0] if words else None, allow_reply=True)
        return subject, level

    @staticmethod
    def _parse_level(text: str) -> PermissionLevel | None:
        """Возвращает уровень по тексту или ``None``, если такого уровня нет."""
        try:
            return PermissionLevel(text.strip().lower())
        except ValueError:
            return None

    async def _subject(self, event, ref: str | None, *, allow_reply: bool) -> int:
        """Возвращает ID пользователя из аргумента или автора сообщения, на которое ответили.

        Бросает ``ValueError``, если ID не удалось определить. Имена (@username) не поддерживаются.
        """
        if ref is not None:
            ref = ref.strip()
            if ref.lstrip("-").isdigit():
                value = int(ref)
                if value <= 0:
                    raise ValueError("ID пользователя должен быть положительным числом")
                return value
            raise ValueError(f"не понял «{ref}»: нужен числовой ID пользователя")
        if allow_reply:
            reply = await event.get_reply_message()
            sender = getattr(reply, "sender_id", None) if reply is not None else None
            if sender is not None:
                return int(sender)
        raise ValueError("укажите ID пользователя или ответьте на его сообщение")
