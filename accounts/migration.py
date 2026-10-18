"""Миграции формата profile.json.

Каждая функция в MIGRATIONS переводит профиль с версии N на N+1.
Чтобы поменять формат: поднимите CURRENT_VERSION и добавьте функцию для старой версии.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

CURRENT_VERSION = 1


def _v0_to_v1(data: dict[str, Any]) -> dict[str, Any]:
    """Ранние профили: без поля version, числа могли быть строками."""
    result = dict(data)
    for key in ("account_id", "api_id"):
        if key in result:
            result[key] = int(result[key])
    result["api_hash"] = str(result.get("api_hash", "")).strip()
    result["username"] = result.get("username") or ""
    result["first_name"] = str(result.get("first_name", ""))
    result.setdefault("session", "session.session")
    result["version"] = 1
    return result


MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {0: _v0_to_v1}


def migrate_profile(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Приводит профиль к текущей версии. Возвращает (профиль, был_ли_изменён)."""
    if not isinstance(data, dict):
        raise ValueError("профиль должен быть JSON-объектом")
    try:
        version = int(data.get("version", 0))
    except (TypeError, ValueError):
        raise ValueError(f"некорректная версия профиля: {data.get('version')!r}") from None
    if version < 0:
        raise ValueError(f"некорректная версия профиля: {version}")
    if version > CURRENT_VERSION:
        raise ValueError(
            f"профиль версии {version} создан более новой версией userbot "
            f"(поддерживается до {CURRENT_VERSION})"
        )

    changed = False
    while version < CURRENT_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise ValueError(f"нет миграции профиля с версии {version}")
        data = step(data)
        version = int(data["version"])
        changed = True
    return data, changed
