"""Команда .purge: тихо удалить последние N сообщений.

``.purge <N>`` удаляет ровно N ваших последних сообщений в этом чате, ``.purge <N> all`` удаляет
N последних сообщений всех участников (нужны права на удаление). Сама команда удаляется первой,
в чате ничего не остаётся. Итог не показывается, об ошибках сообщение приходит в «Избранное».

Никогда не удаляет больше N: список идентификаторов обрезается до N перед удалением,
а сообщения новее команды в него не попадают.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from core.errors import UserError
from core.module import Module
from core.reply import answer
from utils.logger import logger

try:
    from telethon.errors import FloodWaitError
except ImportError:  # Telethon не установлен
    FloodWaitError = None

MAX_PURGE = 1000
CHUNK = 100  # Telegram удаляет не больше 100 сообщений за запрос
SCAN_CAP = 2000  # в каналах своих сообщений ищем в такой глубине истории
MAX_FLOOD_WAIT = 60
USAGE = "Использование: .purge <число> [all]"

DETAILS = f"""\
Тихо удаляет последние сообщения. Команда убирает себя первой, в чате не остаётся ни ответа, ни следа.

.purge <N> — удалить ваши N последних сообщений в этом чате (сама команда не считается)
.purge <N> all — удалить N последних сообщений всех участников; нужны права администратора на удаление сообщений (в личном чате удаляются сообщения обеих сторон)

N от 1 до {MAX_PURGE}. Удаляется ровно N сообщений или меньше, если их в чате меньше. Без прав команда с all ничего не удаляет, а в «Избранное» приходит объяснение. Удалённое вернуть нельзя.

Права: только владелец аккаунта."""


@dataclass(slots=True, frozen=True)
class PurgeRequest:
    """Разобранная команда: сколько сообщений и чьи."""

    count: int
    everyone: bool


def parse_purge(args: list[str]) -> PurgeRequest:
    """Разбирает аргументы ``<N> [all]`` (порядок любой); при ошибке бросает ``UserError``."""
    count: int | None = None
    everyone = False
    for token in (item.lower() for item in args):
        if token == "all" and not everyone:
            everyone = True
        elif token.isdigit() and count is None:
            count = int(token)
        else:
            raise UserError(USAGE)
    if count is None:
        raise UserError(USAGE)
    if not 1 <= count <= MAX_PURGE:
        raise UserError(f"Число сообщений от 1 до {MAX_PURGE}.")
    return PurgeRequest(count, everyone)


def can_delete_others(permissions) -> bool:
    """Есть ли у администратора право удалять чужие сообщения (создатель может всё)."""
    if permissions is None:
        return False
    if getattr(permissions, "is_creator", False):
        return True
    return bool(getattr(permissions, "is_admin", False) and getattr(permissions, "delete_messages", False))


class PurgeModule(Module):
    """Команда ``.purge``: тихое удаление последних сообщений."""

    name = "utility.purge"
    description = "Команда .purge: тихо удалить последние сообщения"
    # Необязательный: без него userbot работает, сбой запуска только пришлёт уведомление.

    def __init__(self, app) -> None:
        super().__init__(app)
        self._sleep = asyncio.sleep  # подменяется в тестах

    async def start(self) -> None:
        """Регистрирует команду ``.purge``."""
        self.app.dispatcher.register_command(
            "purge",
            self.purge_command,
            description="тихо удалить N последних сообщений (all: чужие тоже)",
            usage=".purge <N> [all]",
            priority=30,
            details=DETAILS,
        )

    async def stop(self) -> None:
        """Снимает регистрацию команды ``.purge``."""
        self.app.dispatcher.unregister_command("purge")

    async def purge_command(self, event) -> None:
        """``.purge <N> [all]``: удаляет команду, затем нужные сообщения."""
        command = self.app.dispatcher.get_command(event)
        try:
            request = parse_purge(list(command.args) if command else [])
        except UserError as exc:
            await answer(event, f"❌ {exc}")
            return
        chat_id = getattr(event, "chat_id", None)
        command_id = getattr(event, "id", None)
        if chat_id is None or command_id is None:
            await answer(event, "❌ Не удалось определить чат.")
            return
        # Сначала убираем команду: так её никто не увидит.
        try:
            await event.delete()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Не удалось удалить сообщение с командой .purge: %s", exc)
        try:
            if request.everyone:
                await self._check_rights(event, chat_id)
            ids = await self._collect(event, chat_id, command_id, request)
            if ids:
                await self._delete(chat_id, ids)
        except asyncio.CancelledError:
            raise
        except UserError as exc:
            await self.app.notify_owner(f"❌ .purge: {exc}")
        except Exception as exc:
            logger.exception("Ошибка .purge.")
            reason = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            await self.app.notify_owner(f"❌ .purge не удалось: {reason}")

    async def _check_rights(self, event, chat_id) -> None:
        """Для ``all``: в группе и канале нужны права на удаление чужих сообщений."""
        if getattr(event, "is_private", False):
            return
        try:
            permissions = await self.app.client.get_permissions(chat_id, "me")
        except Exception as exc:
            logger.debug("get_permissions: %s", exc)
            raise UserError("не удалось проверить права в этом чате, ничего не удалено.") from None
        if not can_delete_others(permissions):
            raise UserError("нет прав на удаление чужих сообщений в этом чате, ничего не удалено.")

    async def _collect(self, event, chat_id, command_id, request: PurgeRequest) -> list[int]:
        """Идентификаторы сообщений старше команды: не больше ``request.count``, без повторов."""
        client = self.app.client
        ids: list[int] = []
        if request.everyone:
            source = client.iter_messages(chat_id, limit=request.count, max_id=command_id)
            own_only = False
        elif getattr(event, "is_channel", False) and not getattr(event, "is_group", False):
            # В каналах у сообщений нет автора, поэтому свои отбираем по признаку «исходящее».
            source = client.iter_messages(chat_id, limit=SCAN_CAP, max_id=command_id)
            own_only = True
        else:
            source = client.iter_messages(chat_id, limit=request.count, from_user="me", max_id=command_id)
            own_only = False
        async for message in source:
            number = getattr(message, "id", None)
            if not isinstance(number, int) or number >= command_id or number in ids:
                continue
            if own_only and not getattr(message, "out", False):
                continue
            ids.append(number)
            if len(ids) >= request.count:
                break
        return ids[: request.count]  # страховка: больше N не удаляем никогда

    async def _delete(self, chat_id, ids: list[int]) -> None:
        """Удаляет пачками по 100; на короткий FloodWait ждёт и повторяет пачку."""
        for start in range(0, len(ids), CHUNK):
            chunk = ids[start:start + CHUNK]
            for attempt in range(4):
                try:
                    await self.app.client.delete_messages(chat_id, chunk)
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if FloodWaitError is None or not isinstance(exc, FloodWaitError):
                        raise
                    seconds = int(getattr(exc, "seconds", 0) or 0)
                    if seconds > MAX_FLOOD_WAIT or attempt == 3:
                        raise
                    logger.warning(".purge: FloodWait %s с, жду.", seconds)
                    await self._sleep(seconds + 1)
