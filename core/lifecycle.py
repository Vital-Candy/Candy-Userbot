"""Жизненный цикл приложения: NEW → STARTING → RUNNING → STOPPING → STOPPED (или FAILED)."""
from __future__ import annotations

import time
from collections.abc import Callable

NEW = "new"
STARTING = "starting"
RUNNING = "running"
STOPPING = "stopping"
STOPPED = "stopped"
FAILED = "failed"

STATES = (NEW, STARTING, RUNNING, STOPPING, STOPPED, FAILED)

# Допустимые переходы. STOPPING доступен из любого активного состояния:
# остановку можно запросить в любой момент, в том числе во время запуска.
_TRANSITIONS: dict[str, frozenset[str]] = {
    NEW: frozenset({STARTING, STOPPING, STOPPED}),
    STARTING: frozenset({RUNNING, FAILED, STOPPING}),
    RUNNING: frozenset({STOPPING, FAILED}),
    STOPPING: frozenset({STOPPED}),
    FAILED: frozenset({STOPPING, STOPPED}),
    STOPPED: frozenset(),
}


class LifecycleError(RuntimeError):
    """Недопустимый переход между состояниями."""


class Lifecycle:
    """Хранит текущее состояние и историю переходов. Сам ничего не запускает."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._state = NEW
        self._started_at: float | None = None
        self._history: list[tuple[str, float]] = [(NEW, clock())]

    @property
    def state(self) -> str:
        """Текущее состояние (одна из констант NEW … FAILED)."""
        return self._state

    @property
    def history(self) -> list[str]:
        """Имена состояний в порядке прохождения, включая начальное NEW (копия)."""
        return [name for name, _ in self._history]

    @property
    def is_running(self) -> bool:
        """Находится ли приложение в состоянии RUNNING."""
        return self._state == RUNNING

    @property
    def is_terminal(self) -> bool:
        """Достигнуто ли конечное состояние STOPPED (FAILED конечным не считается)."""
        return self._state == STOPPED

    def can_move(self, new: str) -> bool:
        """Разрешён ли переход из текущего состояния в ``new`` (без самого перехода)."""
        return new in _TRANSITIONS.get(self._state, frozenset())

    def move(self, new: str) -> None:
        """Строгий переход: недопустимый вызывает LifecycleError."""
        if new not in STATES:
            raise LifecycleError(f"неизвестное состояние: {new!r}")
        if new == self._state:
            return
        if not self.can_move(new):
            raise LifecycleError(f"переход {self._state} → {new} недопустим")
        self._apply(new)

    def try_move(self, new: str) -> bool:
        """Мягкий переход для кода остановки: лишний вызов не должен ронять завершение."""
        if new == self._state:
            return False
        if not self.can_move(new):
            return False
        self._apply(new)
        return True

    def _apply(self, new: str) -> None:
        now = self._clock()
        self._state = new
        self._history.append((new, now))
        if new == RUNNING:
            self._started_at = now

    @property
    def uptime(self) -> float | None:
        """Секунды с момента входа в RUNNING (None, пока не запущен)."""
        if self._started_at is None:
            return None
        return max(0.0, self._clock() - self._started_at)
