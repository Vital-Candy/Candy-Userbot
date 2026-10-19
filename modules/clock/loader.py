"""Регистрация модуля часов; вызывается из modules/system/loader.py."""
from __future__ import annotations

from modules.clock.module import ClockModule


def register_clock_modules(app) -> None:
    """Регистрирует модуль часов в имени (команда ``.time``) в реестре модулей приложения."""
    app.modules.register(ClockModule(app))
