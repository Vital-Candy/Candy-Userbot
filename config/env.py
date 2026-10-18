"""Чтение файла ``.env`` в переменные окружения (без внешних зависимостей).

Используется ``config.settings`` при импорте: к моменту разбора настроек окружение уже заполнено.
"""
from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path


def parse_env(text: str) -> dict[str, str]:
    """Разбирает содержимое .env: ``KEY=value``, комментарии ``#``, кавычки, ``export``."""
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        # Строки без «=» и с недопустимым началом имени молча пропускаем: .env правит человек.
        if not sep or not key or not (key[0].isalpha() or key[0] == "_"):
            continue
        value = value.strip()
        if value[:1] in {'"', "'"} and value.endswith(value[0]) and len(value) >= 2:
            value = value[1:-1]
        else:
            # Комментарий в конце строки допустим только у значения без кавычек.
            hash_at = value.find(" #")
            if hash_at != -1:
                value = value[:hash_at].rstrip()
        result[key] = value
    return result


def load_env_file(
    path: Path, environ: MutableMapping[str, str] | None = None
) -> dict[str, str]:
    """Читает .env и добавляет значения в окружение.

    Файл необязателен. Уже заданные переменные окружения не перезаписываются.
    Возвращает только те переменные, которые были добавлены.
    """
    target = os.environ if environ is None else environ
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, PermissionError, UnicodeDecodeError):
        # Битый или недоступный .env не должен мешать запуску: работаем с тем, что в окружении.
        return {}
    added: dict[str, str] = {}
    for key, value in parse_env(text).items():
        if key not in target:  # реальное окружение главнее .env
            target[key] = value
            added[key] = value
    return added
