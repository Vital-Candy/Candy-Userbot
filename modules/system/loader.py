"""Сборка набора системных модулей; вызывается при создании приложения (core/app.py)."""
from __future__ import annotations

from modules.system.accounts import AccountsModule
from modules.system.backup import BackupModule
from modules.system.heartbeat import HeartbeatModule
from modules.system.plugins import PluginsModule
from modules.system.status import StatusModule
from modules.system.update import UpdateModule
from modules.permissions.loader import register_permission_modules
from modules.storage.loader import register_storage_modules


def register_system_modules(app) -> None:
    """Регистрирует только базовые системные модули Alpha 0.4."""
    app.modules.register(StatusModule(app))
    app.modules.register(HeartbeatModule(app))
    app.modules.register(AccountsModule(app))
    app.modules.register(BackupModule(app))
    app.modules.register(PluginsModule(app))
    app.modules.register(UpdateModule(app))
    register_storage_modules(app)
    register_permission_modules(app)
