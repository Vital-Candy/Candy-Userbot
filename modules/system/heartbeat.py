"""Системный модуль heartbeat: фоновая задача, отмечающая время последнего тика."""
from __future__ import annotations

from datetime import datetime, timezone

from core.module import Module


class HeartbeatModule(Module):
    """Минимальный пример безопасного фонового системного модуля."""

    name = "system.heartbeat"
    required = True  # системный модуль: сбой запуска останавливает userbot
    description = "Проверка живости фоновой системы"

    def __init__(self, app) -> None:
        super().__init__(app)
        self.last_run: datetime | None = None

    async def start(self) -> None:
        """Регистрирует и запускает фоновую задачу с интервалом 60 секунд."""
        self.app.background.register(
            self.name,
            self._tick,
            interval=60.0,
        )
        await self.app.background.start(self.name)

    async def stop(self) -> None:
        """Останавливает и удаляет фоновую задачу."""
        await self.app.background.stop(self.name)
        self.app.background.remove(self.name)

    async def _tick(self) -> None:
        self.last_run = datetime.now(timezone.utc)
