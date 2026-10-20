"""Регистрация модулей-утилит (.user, .ping, .tag, .dd); вызывается из modules/system/loader.py."""
from __future__ import annotations

from modules.utility.dd import DDModule
from modules.utility.ping import PingModule
from modules.utility.tag import TagModule
from modules.utility.user import UserModule


def register_utility_modules(app) -> None:
    """Регистрирует модули команд ``.user``, ``.ping``, ``.tag`` и ``.dd``."""
    for module in (UserModule, PingModule, TagModule, DDModule):
        app.modules.register(module(app))
