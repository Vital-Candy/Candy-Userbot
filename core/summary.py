"""Текстовые сводки о модулях и фоновых задачах (для .status и консоли)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.background import FAILING, RUNNING

ICONS = {RUNNING: "✅", FAILING: "⚠️"}


def _short(text: str | None, limit: int = 120) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _ago(moment: datetime | None) -> str:
    if moment is None:
        return "ещё не запускалась"
    seconds = max(0, int((datetime.now(timezone.utc) - moment).total_seconds()))
    if seconds < 90:
        return f"{seconds} с назад"
    if seconds < 5400:
        return f"{seconds // 60} мин назад"
    return f"{seconds // 3600} ч назад"


def module_lines(app: Any) -> list[str]:
    """Строка на каждый модуль: работает, упал (с причиной) или остановлен."""
    lines = []
    for state in app.modules.states():
        name = state.module.name
        mark = "обязательный" if state.required else "необязательный"
        if state.started:
            lines.append(f"✅ {name} ({mark})")
        elif state.failed:
            lines.append(f"❌ {name} ({mark}): {_short(state.error)}")
        else:
            lines.append(f"⏸ {name} ({mark}): остановлен")
    return lines


def task_lines(app: Any) -> list[str]:
    """Строка на каждую фоновую задачу: статус, счётчики запусков и последняя ошибка."""
    lines = []
    for item in app.background.list():
        if item.status == FAILING:
            lines.append(
                f"{ICONS[FAILING]} {item.name}: FAILING, сбоев подряд {item.consecutive_failures} "
                f"(всего {item.failures}/{item.runs}). Последняя ошибка: {_short(item.last_error)}"
            )
        elif item.status == RUNNING:
            lines.append(
                f"{ICONS[RUNNING]} {item.name}: RUNNING, запусков {item.runs}, "
                f"последний {_ago(item.last_run)}"
            )
        else:
            lines.append(f"⏸ {item.name}: STOPPED")
    return lines


def failed_summary(app: Any) -> str | None:
    """Текст уведомления владельцу о том, что не запустилось при старте.

    Возвращает None, если все модули и плагины стартовали без сбоев.
    """
    parts = [f"• {name}: {_short(reason)}" for name, reason in app.modules.startup_failures]
    parts += [
        f"• плагин {s.name}: {_short(getattr(s, 'error', None)) or 'см. лог'}"
        for s in app.plugins.states()
        if s.failed
    ]
    if not parts:
        return None
    return "⚠️ Candy Userbot запущен, но не всё стартовало:\n" + "\n".join(parts)


def plugin_lines(manager: Any, *, esc=lambda text: text) -> list[str]:
    """Строки списка плагинов. ``esc`` экранирует чужой текст (имена, ошибки) для Markdown."""
    manager.discover()
    lines = []
    for state in manager.states():
        name = esc(state.name)
        title = name + (f" v{esc(state.version)}" if state.version else "")
        if state.loaded:
            lines.append(f"✅ {title}")
        elif state.failed:
            lines.append(f"❌ {name}: {esc(state.error or 'ошибка загрузки, см. лог')}")
        else:
            note = f" (последняя ошибка: {esc(state.error)})" if state.error else ""
            lines.append(f"⏸ {name}: не загружен{note}")
    return lines


def plugin_info_lines(info: dict, *, esc=lambda text: text) -> list[str]:
    """Подробная карточка плагина из ``PluginManager.info()``; ``esc`` как в ``plugin_lines``."""
    status = "загружен" if info["loaded"] else ("ошибка" if info["failed"] else "не загружен")
    lines = [f"🔌 {esc(info['name'])}: {status}"]
    if info["version"]:
        lines.append(f"Версия: {esc(info['version'])}")
    if info["description"]:
        lines.append(f"Описание: {esc(info['description'])}")
    if info["requires"]:
        lines.append("Зависит от: " + ", ".join(esc(item) for item in info["requires"]))
    if info["loaded"]:
        lines.append(
            f"Зарегистрировано: команд {info['commands']}, обработчиков {info['handlers']}, "
            f"задач {info['tasks']}"
        )
    if info["error"]:
        lines.append(f"Ошибка: {esc(info['error'])}")
    return lines
