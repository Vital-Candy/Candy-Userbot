"""Ограничение прав на файлы и каталоги с секретами (сессии, профили, резервные копии)."""
from __future__ import annotations

import os
from pathlib import Path


def secure_file(path: Path) -> None:
    """Права 600: файл читает только владелец. Ошибки игнорируются.

    На Windows и на разделах без прав (например, общее хранилище Android)
    chmod ничего не делает или не поддерживается, это не ошибка.
    """
    _chmod(path, 0o600)


def secure_dir(path: Path) -> None:
    """Права 700 для каталога с секретами (сессии, профили, бэкапы)."""
    _chmod(path, 0o700)


def _chmod(path: Path, mode: int) -> None:
    """Меняет права, молча пропуская платформы и файловые системы без поддержки."""
    if os.name == "nt":  # на Windows POSIX-права не применяются
        return
    try:
        os.chmod(path, mode)
    except OSError:
        pass
