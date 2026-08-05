# core/account_context.py
"""
AccountContext — изолированный runtime-контекст одного Telegram-аккаунта.

Этап 2: добавлен AccountStatus, connected_at, изоляция через event.client.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path

logger = logging.getLogger("account_context")


class AccountStatus(Enum):
    OFFLINE       = auto()  # не подключён
    CONNECTING    = auto()  # идёт подключение
    CONNECTED     = auto()  # подключён и авторизован
    NEEDS_LOGIN   = auto()  # сессия недействительна, нужен вход
    ERROR         = auto()  # ошибка подключения
    DISCONNECTING = auto()  # идёт отключение


@dataclass
class AccountContext:
    # ── Идентификация ────────────────────────────────────────────────
    account_id:   str
    api_id:       int
    api_hash:     str
    session_path: Path

    # ── Runtime ──────────────────────────────────────────────────────
    client:       object | None = field(default=None,               repr=False)
    tasks:        list[asyncio.Task] = field(default_factory=list,  repr=False)
    handlers:     list = field(default_factory=list,                repr=False)
    module_state: dict[str, object] = field(default_factory=dict,   repr=False)

    # ── Статус ───────────────────────────────────────────────────────
    status:       AccountStatus = field(default=AccountStatus.OFFLINE)
    connected_at: datetime | None = None
    error_msg:    str = ""

    # ── Метаданные из Telegram ────────────────────────────────────────
    telegram_id: int | None = None
    first_name:  str        = ""
    last_name:   str        = ""
    username:    str | None = None
    phone:       str | None = None

    # ── Свойства ─────────────────────────────────────────────────────

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        parts = [p for p in (self.first_name, self.last_name) if p]
        name  = " ".join(parts) or "Unknown"
        return f"{name} [{self.telegram_id}]" if self.telegram_id else name

    def is_running(self) -> bool:
        return (
            self.client is not None
            and self.status == AccountStatus.CONNECTED
            and getattr(self.client, "is_connected", lambda: False)()
        )

    # ── Задачи ───────────────────────────────────────────────────────

    def add_task(self, coro) -> asyncio.Task:
        """Запускает корутину как asyncio.Task привязанный к этому аккаунту."""
        task = asyncio.ensure_future(coro)
        self.tasks.append(task)
        def _cleanup(t):
            try: self.tasks.remove(t)
            except ValueError: pass
        task.add_done_callback(_cleanup)
        return task

    async def cancel_tasks(self) -> None:
        """Отменяет все активные задачи этого аккаунта."""
        pending = [t for t in list(self.tasks) if not t.done()]
        if not pending:
            return
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        self.tasks.clear()
        logger.debug(f"[{self.display_name}] задачи отменены")

    # ── Обработчики ──────────────────────────────────────────────────

    def remove_all_handlers(self) -> None:
        """Снимает все event-handlers зарегистрированные на этом аккаунте."""
        if self.client is None:
            return
        remove = getattr(self.client, "remove_event_handler", None)
        if remove is None:
            return
        for h in list(self.handlers):
            try: remove(h)
            except Exception: pass
        self.handlers.clear()
        logger.debug(f"[{self.display_name}] обработчики сняты")

    # ── Состояние модулей ─────────────────────────────────────────────

    def get_module_state(self, name: str) -> dict:
        return self.module_state.setdefault(name, {})

    def set_module_state(self, name: str, state: dict) -> None:
        self.module_state[name] = state

    def __repr__(self) -> str:
        return f"AccountContext({self.display_name!r}, {self.status.name})"
