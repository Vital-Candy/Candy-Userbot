"""Фасад хранилища: открывает одну БД и раздаёт общие объекты доступа к данным по таблицам."""
from __future__ import annotations

from pathlib import Path

from storage.database import Database
from storage.labels import LabelStore
from storage.permissions import PermissionStore
from storage.plugin_data import PluginDataStore


class Storage:
    """Единая точка доступа к постоянным данным приложения."""

    def __init__(self, path: Path) -> None:
        self.database = Database(path)
        self.labels = LabelStore(self.database)
        self.permissions = PermissionStore(self.database)
        self.plugin_data = PluginDataStore(self.database)

    def open(self) -> None:
        """Открывает базу и применяет недостающие миграции (см. Database.open)."""
        self.database.open()

    def close(self) -> None:
        """Закрывает базу; можно вызывать повторно."""
        self.database.close()
