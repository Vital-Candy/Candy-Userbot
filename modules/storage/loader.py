"""Регистрация модулей, использующих хранилище; вызывается из modules/system/loader.py."""
from __future__ import annotations
from modules.storage.labels import LabelsModule

def register_storage_modules(app) -> None:
    """Регистрирует модули поверх хранилища (сейчас только метки сообщений)."""
    app.modules.register(LabelsModule(app))
