"""Регистрация модулей-утилит (.user, .ping, .tag); вызывается из modules/system/loader.py."""
from __future__ import annotations

from modules.utility.ping import PingModule
from modules.utility.tag import TagModule
from modules.utility.user import UserModule


def register_utility_modules(app) -> None:
    """Регистрирует модули команд ``.user``, ``.ping`` и ``.tag``."""
    for module in (UserModule, PingModule, TagModule):
        app.modules.register(module(app))
