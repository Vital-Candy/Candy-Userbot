"""Мост от событий Telethon к внутреннему Dispatcher (core/dispatcher.py)."""
from __future__ import annotations

from telethon import TelegramClient, events

from core.dispatcher import Dispatcher
from utils.logger import logger


class EventBridge:
    """Адаптер между Telethon и внутренним Dispatcher."""

    def __init__(self, client: TelegramClient, dispatcher: Dispatcher) -> None:
        self.client = client
        self.dispatcher = dispatcher
        self._registered = False
        # Новые сообщения нужны всегда: через них приходят команды владельца.
        self._always = ((self._new_message, events.NewMessage()),)
        # Остальные типы подключаются лениво: только пока в диспетчере есть их обработчики.
        # Так Telethon не собирает события, которые никто не слушает (особенно raw: он
        # получает каждое обновление Telegram).
        self._lazy: dict[str, tuple] = {
            "edited": (self._edited, events.MessageEdited()),
            "deleted": (self._deleted, events.MessageDeleted()),
            "callback": (self._callback, events.CallbackQuery()),
            "raw": (self._raw, events.Raw()),
        }
        self._active: set[str] = set()  # какие ленивые подписки сейчас включены

    def register(self) -> None:
        """Подписывается на события Telethon. Повторный вызов ничего не делает."""
        if self._registered:
            return
        for callback, builder in self._always:
            self.client.add_event_handler(callback, builder)
        self._registered = True
        self.dispatcher.add_listener(self._on_handlers_changed)
        for event_type in self._lazy:
            self._sync(event_type)
        logger.debug("EventBridge зарегистрирован.")

    def unregister(self) -> None:
        """Снимает все подписки. Без предшествующего ``register`` ничего не делает."""
        if not self._registered:
            return
        self.dispatcher.remove_listener(self._on_handlers_changed)
        for callback, builder in self._always:
            self.client.remove_event_handler(callback, builder)
        for event_type in self._lazy:
            self._set(event_type, False)
        self._registered = False

    def _on_handlers_changed(self, event_type: str) -> None:
        """Реагирует на изменение набора обработчиков диспетчера."""
        if event_type in self._lazy:
            self._sync(event_type)

    def _sync(self, event_type: str) -> None:
        """Приводит подписку Telethon в соответствие с наличием обработчиков."""
        self._set(event_type, self.dispatcher.has_handlers(event_type))

    def _set(self, event_type: str, wanted: bool) -> None:
        """Включает или выключает одну ленивую подписку (без лишних вызовов клиента)."""
        if wanted == (event_type in self._active):
            return
        callback, builder = self._lazy[event_type]
        if wanted:
            self.client.add_event_handler(callback, builder)
            self._active.add(event_type)
        else:
            self.client.remove_event_handler(callback, builder)
            self._active.discard(event_type)
        logger.debug("События '%s' %s.", event_type, "включены" if wanted else "выключены")

    async def _new_message(self, event: events.NewMessage.Event) -> None:
        # Сначала обычные обработчики, потом команды: команда видит уже отработавшие хуки.
        await self.dispatcher.dispatch("new_message", event)
        if getattr(event, "out", False):
            await self.dispatcher.dispatch_command(event)
        else:
            # Чужие сообщения: выполнятся только команды с allow_incoming и своими фильтрами.
            await self.dispatcher.dispatch_command(event, incoming=True)

    async def _edited(self, event: events.MessageEdited.Event) -> None:
        await self.dispatcher.dispatch("edited", event)

    async def _deleted(self, event: events.MessageDeleted.Event) -> None:
        await self.dispatcher.dispatch("deleted", event)

    async def _callback(self, event: events.CallbackQuery.Event) -> None:
        await self.dispatcher.dispatch("callback", event)

    async def _raw(self, event: object) -> None:
        await self.dispatcher.dispatch("raw", event)
