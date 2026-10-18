"""Безопасный API для плагинов.

Плагин регистрирует команды, обработчики и фоновые задачи только через
``self.api``. Объект запоминает всё, что плагин зарегистрировал, и при выгрузке
(в том числе после упавшего ``teardown()`` или ``setup()``) снимает это сам.
"""
from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from core.dispatcher import Command, Handler
from utils.logger import logger as core_logger

Undo = Callable[[], Awaitable[None] | None]


class PluginStorage:
    """Своё пространство плагина в базе: JSON-значения по строковым ключам."""

    def __init__(self, api: "PluginAPI") -> None:
        self._api = api

    async def _scope(self) -> tuple[Any, int, str]:
        self._api._check_open()
        store = self._api.app.storage.plugin_data
        account_id = await self._api.app.identity.account_id()
        return store, account_id, self._api.plugin_name

    async def get(self, key: str, default: Any = None) -> Any:
        """Значение по ключу или ``default``, если ключа нет."""
        store, account_id, plugin = await self._scope()
        return store.get(account_id=account_id, plugin=plugin, key=key, default=default)

    async def set(self, key: str, value: Any) -> None:
        """Сохраняет JSON-совместимое значение под ключом (перезаписывает старое)."""
        store, account_id, plugin = await self._scope()
        store.set(account_id=account_id, plugin=plugin, key=key, value=value)

    async def delete(self, key: str) -> bool:
        """Удаляет ключ. Возвращает результат хранилища (обычно: был ли такой ключ)."""
        store, account_id, plugin = await self._scope()
        return store.delete(account_id=account_id, plugin=plugin, key=key)

    async def keys(self) -> list[str]:
        """Все ключи этого плагина у текущего аккаунта."""
        store, account_id, plugin = await self._scope()
        return store.keys(account_id=account_id, plugin=plugin)


class PluginAPI:
    """Фасад над ядром для одного плагина: регистрации с автоматической отменой, логгер, storage.

    После ``cleanup()`` объект закрыт: любая новая регистрация бросает RuntimeError.
    """

    def __init__(self, app: Any, plugin_name: str) -> None:
        self.app = app
        self.plugin_name = plugin_name
        self.logger = logging.getLogger(f"candy.plugin.{plugin_name}")
        self.storage = PluginStorage(self)
        self._undo: list[tuple[str, Undo]] = []
        self._counts = {"commands": 0, "handlers": 0, "tasks": 0}
        self._closed = False

    # ---------------------------------------------------------------- state

    @property
    def closed(self) -> bool:
        """Закрыт ли API (плагин выгружен, регистрировать больше нельзя)."""
        return self._closed

    @property
    def registrations(self) -> dict[str, int]:
        """Сколько команд, обработчиков и задач сейчас держит плагин."""
        return dict(self._counts)

    def _check_open(self) -> None:
        # Защита от «зомби»-плагина: после выгрузки его регистрации уже никто не снимет.
        if self._closed:
            raise RuntimeError(f"плагин '{self.plugin_name}' выгружен, регистрировать больше нельзя")

    # ------------------------------------------------------------- register

    def register_command(self, name: str, callback: Callable[..., Any], **options: Any) -> Command:
        """Как ``Dispatcher.register_command``. Команда снимется при выгрузке плагина."""
        self._check_open()
        dispatcher = self.app.dispatcher
        command = dispatcher.register_command(name, callback, **options)
        self._counts["commands"] += 1

        def undo() -> None:
            """Снимает команду из диспетчера и уменьшает счётчик."""
            # Не трогаем команду, если её уже заменили чужой с тем же именем.
            if dispatcher.commands.get(command.name) is command:
                dispatcher.unregister_command(command.name)
            self._counts["commands"] -= 1

        self._undo.append((f"команда .{command.name}", undo))
        return command

    def register_handler(self, event_type: str, callback: Callable[..., Any], **options: Any) -> Handler:
        """Как ``Dispatcher.register``. Обработчик снимется при выгрузке плагина."""
        self._check_open()
        dispatcher = self.app.dispatcher
        options.setdefault("name", f"{self.plugin_name}.{getattr(callback, '__name__', 'handler')}")
        handler = dispatcher.register(event_type, callback, **options)
        self._counts["handlers"] += 1

        def undo() -> None:
            """Снимает обработчик из диспетчера и уменьшает счётчик."""
            dispatcher.unregister(handler)
            self._counts["handlers"] -= 1

        self._undo.append((f"обработчик {handler.name}", undo))
        return handler

    async def add_background_task(
        self, name: str, callback: Callable[..., Any], *, interval: float, start: bool = True
    ) -> str:
        """Регистрирует (и по умолчанию сразу запускает) циклическую фоновую задачу.

        Возвращает полное имя задачи ``plugin.<плагин>.<name>``, под которым она видна в ``.status``.
        """
        self._check_open()
        background = self.app.background
        full_name = f"plugin.{self.plugin_name}.{name.strip()}"
        background.register(full_name, callback, interval=interval)
        self._counts["tasks"] += 1

        async def undo() -> None:
            """Останавливает задачу и убирает её из реестра фоновых задач."""
            # remove() вызываем в finally: задача должна уйти из реестра, даже если stop() упал.
            try:
                await background.stop(full_name)
            finally:
                background.remove(full_name)
                self._counts["tasks"] -= 1

        self._undo.append((f"задача {full_name}", undo))
        if start:
            await background.start(full_name)
        return full_name

    def on_cleanup(self, callback: Undo) -> None:
        """Любое своё действие при выгрузке (закрыть файл, соединение). Вызывается в обратном порядке."""
        self._check_open()
        self._undo.append((f"cleanup {getattr(callback, '__name__', 'callback')}", callback))

    # -------------------------------------------------------------- cleanup

    async def cleanup(self) -> None:
        """Снимает всё в обратном порядке регистрации. Ошибка одного шага не мешает остальным."""
        # Закрываем сразу: пока идёт очистка, новые регистрации не должны проскочить.
        self._closed = True
        while self._undo:
            label, undo = self._undo.pop()
            try:
                result = undo()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                # Ошибку шага только логируем: остальные регистрации всё равно надо снять.
                core_logger.exception(
                    "Плагин '%s': не удалось снять %s.", self.plugin_name, label
                )
