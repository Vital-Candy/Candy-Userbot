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
        self._raw_registered = False
        self._builders = (
            (self._new_message, events.NewMessage()),
            (self._edited, events.MessageEdited()),
            (self._deleted, events.MessageDeleted()),
            (self._callback, events.CallbackQuery()),
        )
        # Raw получает каждое обновление Telegram, поэтому подключается лениво:
        # только пока в диспетчере есть raw-обработчики.
        self._raw_builder = events.Raw()

    def register(self) -> None:
        """Подписывается на события Telethon. Повторный вызов ничего не делает."""
        if self._registered:
            return
        for callback, builder in self._builders:
            self.client.add_event_handler(callback, builder)
        self._registered = True
        self.dispatcher.add_listener(self._on_handlers_changed)
        self._sync_raw()
        logger.debug("EventBridge зарегистрирован.")

    def unregister(self) -> None:
        """Снимает все подписки (в том числе raw). Без предшествующего ``register`` ничего не делает."""
        if not self._registered:
            return
        self.dispatcher.remove_listener(self._on_handlers_changed)
        for callback, builder in self._builders:
            self.client.remove_event_handler(callback, builder)
        self._set_raw(False)
        self._registered = False

    def _on_handlers_changed(self, event_type: str) -> None:
        if event_type == "raw":
            self._sync_raw()

    def _sync_raw(self) -> None:
        self._set_raw(self.dispatcher.has_handlers("raw"))

    def _set_raw(self, wanted: bool) -> None:
        if wanted == self._raw_registered:
            return
        if wanted:
            self.client.add_event_handler(self._raw, self._raw_builder)
        else:
            self.client.remove_event_handler(self._raw, self._raw_builder)
        self._raw_registered = wanted
        logger.debug("Raw-события %s.", "включены" if wanted else "выключены")

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
