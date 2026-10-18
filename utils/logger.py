"""Логгер ``candy``: консоль, кольцевой буфер в памяти (для меню) и ротируемый файл.

Настраивается из ``main`` через ``set_level`` и ``setup_file_logging``; режим меню прячет консоль.
"""
from __future__ import annotations

import collections
import logging
import logging.handlers
import os
import sys
from collections.abc import Callable
from pathlib import Path

LOG_FILE_NAME = "candy.log"  # имя файла лога внутри каталога логов

logger = logging.getLogger("candy")
logger.setLevel(logging.INFO)

# Проверка защищает от дублирования консольного обработчика при повторном импорте модуля.
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger.addHandler(handler)

logger.propagate = False  # не отдаём записи корневому логгеру: иначе строки задвоятся


class RingBufferHandler(logging.Handler):
    """Хранит последние строки лога в памяти и сообщает о новых подписчикам.

    Нужен меню «логи в реальном времени»: показывать логи можно, даже когда вывод в
    консоль выключен, а запись в файл отключена.
    """

    def __init__(self, capacity: int = 500) -> None:
        """``capacity``: сколько последних строк хранить (старые вытесняются)."""
        super().__init__()
        self._lines: collections.deque[str] = collections.deque(maxlen=capacity)
        self._listeners: list[Callable[[str], None]] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Форматирует запись, кладёт в буфер и уведомляет подписчиков. Ошибки не пробрасывает."""
        # Логирование не должно ронять программу, поэтому сбои форматирования и слушателей глушим.
        try:
            line = self.format(record)
        except Exception:
            return
        self._lines.append(line)
        # Обход по копии: подписчик может отписаться прямо из своего вызова.
        for listener in list(self._listeners):
            try:
                listener(line)
            except Exception:
                pass

    def lines(self, count: int | None = None) -> list[str]:
        """Последние ``count`` строк (все, если ``count`` не задан)."""
        items = list(self._lines)
        return items if count is None else items[-count:]

    def subscribe(self, listener: Callable[[str], None]) -> Callable[[], None]:
        """Возвращает функцию отписки."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            """Снимает подписку (повторный вызов безвредён)."""
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe


ring = RingBufferHandler()
ring.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
logger.addHandler(ring)

# Консольные обработчики, снятые на время работы меню (вернёт ``unmute_console``).
_muted: list[logging.Handler] = []


def mute_console() -> None:
    """Прячет вывод логов в консоль (файл и память продолжают работать)."""
    for handler in list(logger.handlers):
        # Точное сравнение типа: RotatingFileHandler наследует StreamHandler, а файл прятать нельзя.
        if type(handler) is logging.StreamHandler and handler not in _muted:
            logger.removeHandler(handler)
            _muted.append(handler)


def unmute_console() -> None:
    """Возвращает консольный вывод логов, скрытый ``mute_console``."""
    while _muted:
        handler = _muted.pop()
        if handler not in logger.handlers:
            logger.addHandler(handler)

_FILE_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"


def set_level(name: str) -> None:
    """Меняет уровень логов по имени (``"DEBUG"``, ``"INFO"``...)."""
    logger.setLevel(getattr(logging, name.upper(), logging.INFO))


def _file_handlers() -> list[logging.Handler]:
    """Файловые обработчики, созданные ``setup_file_logging`` (по пометке ``_candy_file``)."""
    return [h for h in logger.handlers if getattr(h, "_candy_file", False)]


def setup_file_logging(directory: Path | None, max_bytes: int = 1_000_000, backups: int = 3) -> Path | None:
    """Включает запись логов в ``<directory>/candy.log`` с ротацией.

    Возвращает путь к файлу или None (выключено или каталог недоступен: userbot
    из-за логов падать не должен). Повторный вызов заменяет прежний файловый обработчик.
    """
    disable_file_logging()
    if directory is None:
        return None
    path = Path(directory) / LOG_FILE_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )
    except OSError as exc:
        logger.warning("Файловые логи отключены: %s", exc)
        return None
    handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    # Пометка нужна, чтобы найти и снять именно наш обработчик при повторной настройке.
    handler._candy_file = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    try:
        os.chmod(path, 0o600)  # в логах бывают имена и тексты ошибок
    except OSError:
        pass
    return path


def disable_file_logging() -> None:
    """Снимает файловый обработчик и закрывает файл."""
    for handler in _file_handlers():
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
