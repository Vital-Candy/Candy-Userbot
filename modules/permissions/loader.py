"""Регистрация модулей подсистемы прав доступа; вызывается из modules/system/loader.py."""
from __future__ import annotations

from modules.permissions.module import PermissionsModule


def register_permission_modules(app) -> None:
    """Регистрирует модуль прав доступа (команда ``.perm``) в реестре модулей приложения."""
    app.modules.register(PermissionsModule(app))
