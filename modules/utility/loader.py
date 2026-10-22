"""Регистрация модулей-утилит (.user, .ping, .tag, .purge); вызывается из modules/system/loader.py."""
from __future__ import annotations

from modules.utility.ping import PingModule
from modules.utility.purge import PurgeModule
from modules.utility.tag import TagModule
from modules.utility.user import UserModule


def register_utility_modules(app) -> None:
    """Регистрирует модули команд ``.user``, ``.ping``, ``.tag`` и ``.purge``."""
    for module in (UserModule, PingModule, TagModule, PurgeModule):
        app.modules.register(module(app))
