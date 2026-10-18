"""Общие исключения ядра и обработка фатальных ошибок."""
from __future__ import annotations

from utils.logger import logger


class UserError(RuntimeError):
    """Ошибка, понятная пользователю: показывается текстом, без трейсбека."""


def handle_fatal_error(error: Exception) -> None:
    """Пишет критическую ошибку в лог вместе с traceback. Процесс сама не завершает."""
    logger.critical("Критическая ошибка: %s", error, exc_info=error)
