"""Модуль меток сообщений.

Синтаксис: ``.label <имя>`` и ``.unlabel <имя>`` (ответом на сообщение), ``.labels`` (ответом),
``.goto <имя>``. Команды доступны владельцу аккаунта; данные хранит storage/labels.py.
"""
from __future__ import annotations

import sqlite3

from core.module import Module
from core.reply import answer
from utils.links import message_link
from utils.logger import logger
from utils.text import escape_markdown

GOTO_LIMIT = 10  # сколько ссылок показывает .goto
NAME_RULES = (
    "Имя метки: от 1 до 64 символов, без пробелов и символов Markdown, регистр не важен "
    "(Идея и идея одна и та же метка)."
)
RELATED = "Связанные команды: .label, .labels, .unlabel, .goto."

LABEL_DETAILS = f"""\
Ставит метку на сообщение, чтобы потом быстро его найти. Использовать нужно ответом на нужное сообщение.

.label <имя> — поставить метку (ответом на сообщение)

{NAME_RULES}
На одном сообщении может быть несколько разных меток, одну и ту же дважды поставить нельзя.
Метки хранятся в базе userbot и принадлежат активному аккаунту.

{RELATED}
Права: только владелец аккаунта."""

LABELS_DETAILS = f"""\
Показывает все метки сообщения, на которое вы ответили.

.labels — список меток сообщения (ответом на сообщение)

{RELATED}
Права: только владелец аккаунта."""

GOTO_DETAILS = f"""\
Находит сообщения по метке и присылает ссылки на них. Работает в любом чате.

.goto <имя> — ссылки на сообщения с этой меткой (новые первыми, до {GOTO_LIMIT} штук)

Для обычных групп Telegram ссылок на сообщения не даёт, тогда пишется только номер сообщения.

{RELATED}
Права: только владелец аккаунта."""

UNLABEL_DETAILS = f"""\
Снимает метку с сообщения. Использовать нужно ответом на это сообщение.

.unlabel <имя> — удалить метку с сообщения (ответом на сообщение)

{RELATED}
Права: только владелец аккаунта."""

NO_CHAT = "❌ Не удалось определить чат."


class LabelsModule(Module):
    """Команды ``.label``, ``.labels``, ``.goto``, ``.unlabel`` поверх storage.labels."""

    name = "storage.labels"
    description = "Команды управления метками сообщений"

    async def start(self) -> None:
        """Регистрирует четыре команды меток (без ограничения по правам: доступ у владельца)."""
        dispatcher = self.app.dispatcher
        dispatcher.register_command(
            "label",
            self.label_command,
            description="поставить метку на сообщение (ответом)",
            usage=".label <имя>",
            priority=50,
            details=LABEL_DETAILS,
        )
        dispatcher.register_command(
            "labels",
            self.labels_command,
            description="показать метки сообщения (ответом)",
            usage=".labels",
            priority=50,
            details=LABELS_DETAILS,
        )
        dispatcher.register_command(
            "goto",
            self.goto_command,
            description="найти сообщения по метке",
            usage=".goto <имя>",
            priority=50,
            details=GOTO_DETAILS,
        )
        dispatcher.register_command(
            "unlabel",
            self.unlabel_command,
            description="снять метку с сообщения (ответом)",
            usage=".unlabel <имя>",
            priority=50,
            details=UNLABEL_DETAILS,
        )

    async def stop(self) -> None:
        """Снимает регистрацию всех команд меток."""
        for name in ("label", "labels", "goto", "unlabel"):
            self.app.dispatcher.unregister_command(name)

    async def label_command(self, event) -> None:
        """``.label <имя>`` ответом на сообщение: ставит метку; дубликат на том же сообщении отклоняется."""
        reply = await event.get_reply_message()
        if reply is None:
            await answer(event, "❌ .label нужно использовать ответом на сообщение.")
            return

        command = self.app.dispatcher.get_command(event)
        if command is None or len(command.args) != 1:
            await answer(event, "Использование: .label <имя>")
            return

        chat_id = self._chat_id(event)
        if chat_id is None:
            await answer(event, NO_CHAT)
            return

        try:
            account_id = await self.app.identity.account_id()
            label = self.app.storage.labels.create(
                account_id=account_id,
                chat_id=chat_id,
                message_id=int(reply.id),
                name=command.args[0],
                creator_id=account_id,
            )
        except ValueError as exc:
            await answer(event, f"❌ {exc}")
            return
        # Уникальность (сообщение, имя) обеспечивает БД, поэтому дубль приходит как IntegrityError.
        except sqlite3.IntegrityError:
            await answer(event, "❌ Такая метка на этом сообщении уже есть.")
            return
        except sqlite3.Error:
            logger.exception("Ошибка базы данных в .label")
            await answer(event, "❌ Не удалось сохранить метку (ошибка базы данных).")
            return
        await answer(event, f"🏷 Метка #{label.id} `{escape_markdown(label.name)}` установлена.")

    async def labels_command(self, event) -> None:
        """``.labels`` ответом на сообщение: показывает все его метки."""
        reply = await event.get_reply_message()
        if reply is None:
            await answer(event, "❌ Ответь на сообщение, чтобы посмотреть его метки.")
            return
        chat_id = self._chat_id(event)
        if chat_id is None:
            await answer(event, NO_CHAT)
            return
        try:
            account_id = await self.app.identity.account_id()
            labels = self.app.storage.labels.list_for_message(
                account_id=account_id,
                chat_id=chat_id,
                message_id=int(reply.id),
            )
        except sqlite3.Error:
            logger.exception("Ошибка базы данных в .labels")
            await answer(event, "❌ Не удалось прочитать метки (ошибка базы данных).")
            return
        if not labels:
            await answer(event, "🏷 У сообщения нет меток.")
            return
        lines = ["🏷 Метки:"] + [f"#{item.id} — {escape_markdown(item.name)}" for item in labels]
        await answer(event, "\n".join(lines))

    async def goto_command(self, event) -> None:
        """``.goto <имя>``: ссылки на сообщения с меткой (новые первыми, не больше ``GOTO_LIMIT``)."""
        command = self.app.dispatcher.get_command(event)
        if command is None or len(command.args) != 1:
            await answer(event, "Использование: .goto <имя>")
            return
        try:
            account_id = await self.app.identity.account_id()
            found = self.app.storage.labels.list_by_name(
                account_id=account_id, name=command.args[0], newest_first=True
            )
        except ValueError as exc:
            await answer(event, f"❌ {exc}")
            return
        except sqlite3.Error:
            logger.exception("Ошибка базы данных в .goto")
            await answer(event, "❌ Не удалось прочитать метки (ошибка базы данных).")
            return
        name = escape_markdown(command.args[0].strip().lower())
        if not found:
            await answer(event, f"❌ Метки `{name}` нет.")
            return
        shown = found[:GOTO_LIMIT]
        lines = [f"🔗 Метка `{name}`:"]
        for number, label in enumerate(shown, 1):
            when = label.created_at.strftime("%Y-%m-%d %H:%M")
            link = message_link(label.chat_id, label.message_id)
            where = (
                f"[сообщение]({link})"
                if link
                else f"сообщение {label.message_id} в обычной группе (ссылки нет)"
            )
            lines.append(f"{number}. {where}, {when} UTC" if len(shown) > 1 else f"{where}, {when} UTC")
        if len(found) > len(shown):
            lines.append(f"… и ещё {len(found) - len(shown)}.")
        await answer(event, "\n".join(lines))

    async def unlabel_command(self, event) -> None:
        """``.unlabel <имя>`` ответом на сообщение: удаляет метку с этого сообщения."""
        reply = await event.get_reply_message()
        command = self.app.dispatcher.get_command(event)
        if reply is None:
            await answer(event, "❌ .unlabel нужно использовать ответом на сообщение.")
            return
        if command is None or len(command.args) != 1:
            await answer(event, "Использование: .unlabel <имя>")
            return
        chat_id = self._chat_id(event)
        if chat_id is None:
            await answer(event, NO_CHAT)
            return
        try:
            account_id = await self.app.identity.account_id()
            removed = self.app.storage.labels.delete(
                account_id=account_id,
                chat_id=chat_id,
                message_id=int(reply.id),
                name=command.args[0],
            )
        except ValueError as exc:
            await answer(event, f"❌ {exc}")
            return
        except sqlite3.Error:
            logger.exception("Ошибка базы данных в .unlabel")
            await answer(event, "❌ Не удалось удалить метку (ошибка базы данных).")
            return
        await answer(event, "✅ Метка удалена." if removed else "❌ Такая метка не найдена.")

    @staticmethod
    def _chat_id(event) -> int | None:
        """ID чата события или ``None``, если Telethon его не определил."""
        chat_id = getattr(event, "chat_id", None)
        return int(chat_id) if chat_id is not None else None
