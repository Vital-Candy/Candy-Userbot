"""Модуль команд .status и .health (без аргументов, отдельный фильтр прав не задан).

Вызывает владелец аккаунта; данные берутся из app.health() и core/summary.py.
"""
from __future__ import annotations

from core.module import Module
from core.reply import answer
from core.summary import module_lines, task_lines


class StatusModule(Module):
    """Команды ``.status`` и ``.health``: состояние модулей, задач и краткий отчёт о здоровье."""

    name = "system.status"
    required = True  # системный модуль: сбой запуска останавливает userbot
    description = "Системная команда .status"

    async def start(self) -> None:
        """Регистрирует команды ``.status`` и ``.health``."""
        self.app.dispatcher.register_command(
            "status",
            self.status_command,
            description="состояние userbot",
            usage=".status",
            priority=100,
        )
        self.app.dispatcher.register_command(
            "health",
            self.health_command,
            description="краткий отчёт о здоровье userbot",
            usage=".health",
            priority=100,
        )

    async def stop(self) -> None:
        """Снимает регистрацию команд ``.status`` и ``.health``."""
        self.app.dispatcher.unregister_command("status")
        self.app.dispatcher.unregister_command("health")

    async def health_command(self, event) -> None:
        """``.health``: краткий отчёт о здоровье."""
        await answer(event, "🩺 Candy Userbot\n" + "\n".join(self.app.health().lines()))

    async def status_command(self, event) -> None:
        """``.status``: здоровье, число запущенных модулей и список фоновых задач."""
        states = self.app.modules.states()
        started = sum(state.started for state in states)
        failed = sum(state.failed for state in states)
        tasks = task_lines(self.app)
        text = (
            "🍬 Candy Userbot\n"
            + "\n".join(self.app.health().lines())
            + "\n\n"
            f"Модули: {started}/{len(states)} запущено, ошибок запуска: {failed}\n"
            + "\n".join(module_lines(self.app))
            + f"\n\nФоновые задачи: {len(tasks)}"
        )
        if tasks:
            text += "\n" + "\n".join(tasks)
        await answer(event, text)
