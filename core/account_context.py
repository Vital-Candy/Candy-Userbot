# core/account_context.py
"""
AccountContext — изолированный контекст одного Telegram-аккаунта.

Каждый аккаунт имеет собственные:
  - TelegramClient и сессию
  - asyncio-задачи (не пересекаются с другими аккаунтами)
  - обработчики событий
  - состояние модулей (module_state)

Этап 1: структура данных подготовлена.
        В main.py пока используется один аккаунт.
        Одновременная работа нескольких — Этап 2+.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("account_context")


@dataclass
class AccountContext:
    # ── Идентификация ────────────────────────────────────────────────
    account_id: str
    """
    Человекочитаемый ID:
      - "@username"   если username есть
      - "Имя [12345]" если username отсутствует
    Не придумывается пользователем — берётся из Telegram.
    """

    api_id:       int
    api_hash:     str
    session_path: Path
    """Абсолютный путь к файлу сессии Telethon (.session)."""

    # ── Runtime (не заполнены до старта) ─────────────────────────────
    client: object | None = field(default=None, repr=False)
    """TelegramClient. None пока аккаунт не запущен."""

    tasks: list[asyncio.Task] = field(default_factory=list, repr=False)
    """asyncio-задачи этого аккаунта (time_name loop и т.п.)."""

    handlers: list = field(default_factory=list, repr=False)
    """Зарегистрированные event-handlers этого аккаунта."""

    module_state: dict[str, object] = field(default_factory=dict, repr=False)
    """
    Произвольное состояние модулей, привязанное к этому аккаунту.
    Пример: {"time_name": {"running": True, "original_name": "Ivan"}}
    """

    # ── Метаданные из Telegram ────────────────────────────────────────
    telegram_id: int | None = None
    first_name:  str        = ""
    last_name:   str        = ""
    username:    str | None = None
    phone:       str | None = None

    # ── Свойства ─────────────────────────────────────────────────────

    @property
    def display_name(self) -> str:
        """
        Отображаемое имя по правилам:
          - "@username"        если username есть
          - "Имя Фамилия [ID]" если нет
        """
        if self.username:
            return f"@{self.username}"
        parts = [p for p in (self.first_name, self.last_name) if p]
        name  = " ".join(parts) or "Unknown"
        return f"{name} [{self.telegram_id}]" if self.telegram_id else name

    def is_running(self) -> bool:
        """True если клиент подключён."""
        return (
            self.client is not None
            and getattr(self.client, "is_connected", lambda: False)()
        )

    # ── Управление задачами ───────────────────────────────────────────

    def add_task(self, coro) -> asyncio.Task:
        """
        Запускает корутину как asyncio.Task, привязанный к этому аккаунту.
        Завершённые задачи убираются автоматически.

        Использование в модуле:
            ctx.add_task(my_loop(ctx.client))
        """
        task = asyncio.ensure_future(coro)
        self.tasks.append(task)

        def _cleanup(t: asyncio.Task) -> None:
            try:
                self.tasks.remove(t)
            except ValueError:
                pass

        task.add_done_callback(_cleanup)
        return task

    async def cancel_tasks(self) -> None:
        """
        Отменяет все активные asyncio-задачи этого аккаунта.
        Ждёт завершения каждой (не более 2 сек).
        """
        pending = [t for t in list(self.tasks) if not t.done()]
        if not pending:
            return

        for task in pending:
            task.cancel()

        results = await asyncio.gather(*pending, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError):
                logger.warning(f"Задача завершилась с ошибкой: {r}")

        self.tasks.clear()
        logger.debug(f"[{self.display_name}] Все задачи отменены")

    # ── Управление обработчиками ──────────────────────────────────────

    def remove_all_handlers(self) -> None:
        """Снимает все зарегистрированные event-handlers."""
        if self.client is None:
            return
        remove = getattr(self.client, "remove_event_handler", None)
        if remove is None:
            return
        for handler in list(self.handlers):
            try:
                remove(handler)
            except Exception as e:
                logger.debug(f"remove_event_handler: {e}")
        self.handlers.clear()
        logger.debug(f"[{self.display_name}] Все обработчики сняты")

    # ── Состояние модулей ─────────────────────────────────────────────

    def get_module_state(self, module_name: str) -> dict:
        """Возвращает состояние модуля (пустой dict если нет)."""
        return self.module_state.setdefault(module_name, {})

    def set_module_state(self, module_name: str, state: dict) -> None:
        """Сохраняет состояние модуля."""
        self.module_state[module_name] = state

    def __repr__(self) -> str:
        status = "connected" if self.is_running() else "offline"
        return f"AccountContext({self.display_name!r}, {status})"
