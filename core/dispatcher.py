"""Диспетчер событий и команд: реестр обработчиков, приоритеты, таймауты и изоляция ошибок.

События приходят из ``core.events`` (мост к Telethon), команды регистрируются модулями и плагинами.
"""
from __future__ import annotations

import asyncio
import contextvars
import inspect
from collections.abc import Callable as _Callable
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from core.parser import CommandParser, ParsedCommand
from core.reply import answer
from utils.logger import logger

HandlerCallback = Callable[[Any], Awaitable[None] | None]
FilterCallback = Callable[[Any], bool | Awaitable[bool]]


@dataclass(slots=True)
class Handler:
    """Подписка на событие одного типа. Создаётся только через ``Dispatcher.register``."""

    callback: HandlerCallback
    event_type: str
    priority: int = 0
    filters: tuple[FilterCallback, ...] = field(default_factory=tuple)
    name: str = ""
    enabled: bool = True  # False после unregister: уже идущий dispatch пропустит обработчик
    order: int = 0  # порядковый номер регистрации: при равном приоритете первым идёт более ранний


@dataclass(slots=True, frozen=True)
class Command:
    """Зарегистрированная команда. ``name`` хранится без префикса и в нижнем регистре."""

    name: str
    callback: HandlerCallback
    description: str = ""
    usage: str = ""
    priority: int = 0
    filters: tuple[FilterCallback, ...] = ()
    allow_incoming: bool = False
    details: str = ""  # подробная справка для ``.help <команда>`` (необязательна)


# Команда, которую сейчас выполняет текущая задача: (событие, разобранная команда).
# ContextVar безопасен для параллельных событий и не зависит от id(event).
_current_command: contextvars.ContextVar[tuple[Any, ParsedCommand] | None] = (
    contextvars.ContextVar("candy_current_command", default=None)
)


class Dispatcher:
    """Внутренний диспетчер событий Candy Userbot.

    Telethon отвечает только за получение событий. Здесь решается, какой
    обработчик получит событие, в каком порядке и с какой изоляцией ошибок.
    """

    EVENT_TYPES = frozenset({"new_message", "edited", "deleted", "raw", "callback"})

    def __init__(
        self,
        *,
        command_prefix: str = ".",
        handler_timeout: float | None = None,
        command_timeout: float | None = None,
    ) -> None:
        """``*_timeout``: секунды; ``None`` или 0 — без ограничения."""
        self.parser = CommandParser(command_prefix)
        self.handlers: dict[str, list[Handler]] = {name: [] for name in self.EVENT_TYPES}
        self.commands: dict[str, Command] = {}
        self.handler_timeout = handler_timeout or None
        self.command_timeout = command_timeout or None
        self._order = 0
        self._listeners: list[_Callable[[str], None]] = []

    def add_listener(self, listener: _Callable[[str], None]) -> None:
        """Сообщает о каждом изменении набора обработчиков: ``listener(event_type)``."""
        self._listeners.append(listener)

    def remove_listener(self, listener: _Callable[[str], None]) -> None:
        """Отписывает слушателя; неизвестный слушатель игнорируется."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def has_handlers(self, event_type: str) -> bool:
        """Есть ли хотя бы один включённый обработчик события этого типа."""
        return any(handler.enabled for handler in self.handlers.get(event_type, ()))

    def _notify(self, event_type: str) -> None:
        """Оповещает слушателей об изменении набора обработчиков; их ошибки не пробрасываются."""
        # Копия кортежем: слушатель может отписаться прямо во время обхода.
        for listener in tuple(self._listeners):
            try:
                listener(event_type)
            except Exception:
                logger.exception("Ошибка слушателя изменений диспетчера.")

    def register(
        self,
        event_type: str,
        callback: HandlerCallback,
        *,
        priority: int = 0,
        filters: tuple[FilterCallback, ...] = (),
        name: str | None = None,
    ) -> Handler:
        """Регистрирует обработчик события и возвращает его (для ``unregister``).

        Порядок вызова: больший ``priority`` раньше, при равенстве раньше зарегистрированный.
        Неизвестный ``event_type``: ValueError.
        """
        if event_type not in self.EVENT_TYPES:
            raise ValueError(f"Неизвестный тип события: {event_type}")

        self._order += 1
        handler = Handler(
            callback=callback,
            event_type=event_type,
            priority=priority,
            filters=filters,
            name=name or getattr(callback, "__name__", "handler"),
            order=self._order,
        )
        self.handlers[event_type].append(handler)
        self.handlers[event_type].sort(key=lambda item: (-item.priority, item.order))
        self._notify(event_type)
        return handler

    def unregister(self, handler: Handler) -> None:
        """Снимает обработчик. Повторный вызов безопасен."""
        handlers = self.handlers.get(handler.event_type)
        if handlers and handler in handlers:
            handlers.remove(handler)
        # dispatch обходит копию списка, поэтому уже начатый обход нужно остановить флагом.
        handler.enabled = False
        self._notify(handler.event_type)

    def register_command(
        self,
        name: str,
        callback: HandlerCallback,
        *,
        description: str = "",
        usage: str = "",
        priority: int = 0,
        filters: tuple[FilterCallback, ...] = (),
        allow_incoming: bool = False,
        details: str = "",
    ) -> Command:
        """``details``: подробное описание (аргументы, примеры) для ``.help <команда>``.

        ``allow_incoming``: команду могут вызывать и другие пользователи.

        По умолчанию команды выполняются только из собственных сообщений. Открытая
        команда обязана иметь фильтры (например ``require(app, "trusted")``), иначе
        ею смог бы пользоваться кто угодно.
        """
        normalized = name.strip().lower()
        if not normalized or normalized.startswith(self.parser.prefix):
            raise ValueError("Имя команды указано неверно")
        if normalized in self.commands:
            raise ValueError(f"Команда .{normalized} уже зарегистрирована")

        if allow_incoming and not filters:
            raise ValueError(
                f"Команда .{normalized} открыта для других пользователей без фильтров доступа"
            )
        command = Command(
            normalized, callback, description, usage, priority, tuple(filters), allow_incoming,
            details.strip(),
        )
        self.commands[normalized] = command
        return command

    def unregister_command(self, name: str) -> None:
        """Удаляет команду по имени; несуществующая команда игнорируется."""
        self.commands.pop(name.strip().lower(), None)

    async def dispatch(self, event_type: str, event: Any) -> None:
        """Передаёт событие обработчикам по порядку. Ошибка одного не мешает остальным.

        Каждый обработчик ограничен ``handler_timeout``; фильтры входят в этот лимит.
        Исключения и таймауты только пишутся в лог.
        """
        # Копия кортежем: обработчики могут (раз)регистрироваться во время обхода.
        for handler in tuple(self.handlers.get(event_type, ())):
            if not handler.enabled:
                continue
            try:
                async with asyncio.timeout(self.handler_timeout) as limit:
                    if not await self._passes_filters(handler.filters, event):
                        continue
                    result = handler.callback(event)
                    if inspect.isawaitable(result):
                        await result
            except TimeoutError:
                # TimeoutError мог прийти из самого обработчика (например, сетевой), а не от лимита.
                if not limit.expired():
                    logger.exception(
                        "Ошибка обработчика '%s' для события '%s'.", handler.name, event_type
                    )
                    continue
                logger.error(
                    "Обработчик '%s' для события '%s' прерван: нет ответа за %g с.",
                    handler.name,
                    event_type,
                    self.handler_timeout,
                )
            except Exception:
                logger.exception(
                    "Ошибка обработчика '%s' для события '%s'.",
                    handler.name,
                    event_type,
                )

    async def dispatch_command(self, event: Any, *, incoming: bool = False) -> None:
        """Разбирает сообщение и выполняет найденную команду.

        ``incoming=True``: сообщение от другого пользователя, работают только открытые команды.
        Ошибка или превышение ``command_timeout`` не пробрасываются: пользователю уходит ответ
        с пометкой, подробности пишутся в лог.
        """
        text = getattr(event, "raw_text", None)
        command_data = self.parser.parse(text)
        if command_data is None:
            return

        command = self.commands.get(command_data.name)
        # Чужие сообщения молча игнорируем для закрытых команд: не раскрываем их существование.
        if command is None or (incoming and not command.allow_incoming):
            return

        # Команда запоминается в ContextVar, чтобы ``get_command`` работал внутри обработчика.
        token = _current_command.set((event, command_data))
        try:
            async with asyncio.timeout(self.command_timeout) as limit:
                if not await self._passes_filters(command.filters, event):
                    return
                result = command.callback(event)
                if inspect.isawaitable(result):
                    await result
        except TimeoutError:
            if limit.expired():
                logger.error(
                    "Команда '.%s' прервана: не выполнилась за %g с.",
                    command_data.name,
                    self.command_timeout,
                )
                await answer(event, f"⏱ Команда .{command_data.name} не уложилась во время.")
            else:
                logger.exception("Ошибка команды '.%s'.", command_data.name)
                await answer(event, f"❌ Ошибка команды .{command_data.name}. Подробности в логе.")
        except Exception:
            logger.exception("Ошибка команды '.%s'.", command_data.name)
            await answer(event, f"❌ Ошибка команды .{command_data.name}. Подробности в логе.")
        finally:
            _current_command.reset(token)

    @staticmethod
    async def _passes_filters(filters: tuple[FilterCallback, ...], event: Any) -> bool:
        """Проверяет фильтры подряд (sync и async); True, если прошли все."""
        # Фильтры идут по порядку и останавливаются на первом отказе (дешёвые ставьте первыми).
        for check in filters:
            result = check(event)
            if inspect.isawaitable(result):
                result = await result
            if not result:
                return False
        return True

    def get_command(self, event: Any) -> ParsedCommand | None:
        """Разобранная команда для события, которое сейчас обрабатывается."""
        current = _current_command.get()
        if current is not None and current[0] is event:
            return current[1]
        return None

    def command_help(self) -> list[Command]:
        """Все команды для справки: сначала с большим приоритетом, затем по алфавиту."""
        return sorted(self.commands.values(), key=lambda item: (-item.priority, item.name))
