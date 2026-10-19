"""Регистрация модуля .spam; вызывается из modules/system/loader.py."""
from __future__ import annotations

from modules.spam.module import SpamModule


def register_spam_modules(app) -> None:
    """Регистрирует модуль команды ``.spam`` в реестре модулей приложения."""
    app.modules.register(SpamModule(app))
