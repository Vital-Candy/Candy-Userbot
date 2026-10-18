"""Абстрактный базовый класс модуля userbot. Реестр и запуск модулей: core/modules.py."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Module(ABC):
    """Базовый контракт подключаемого модуля.

    * ``required``: при сбое запуска останавливает весь userbot (с откатом).
      Необязательный модуль в этом случае только помечается FAILED, а владелец
      получает уведомление.
    * ``requires``: имена модулей, которые должны быть запущены раньше.
    """

    name = "unnamed"
    description = ""
    required = False
    requires: tuple[str, ...] = ()

    def __init__(self, app: Any) -> None:
        self.app = app

    @abstractmethod
    async def start(self) -> None:
        """Запустить модуль."""

    async def stop(self) -> None:
        """Остановить модуль. По умолчанию ничего не делает."""
