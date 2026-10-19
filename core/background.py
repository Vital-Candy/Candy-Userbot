"""Фоновые циклические задачи: регистрация, запуск, остановка и учёт сбоев.

Задачи плагинов и модулей регистрируются в ``BackgroundManager``;
сводки по ним строят health.py и summary.py.
"""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

from utils.logger import logger

TaskCallback = Callable[[], Awaitable[None] | None]

RUNNING = "RUNNING"
FAILING = "FAILING"
STOPPED = "STOPPED"

# Сколько подряд сбоев терпим с обычным интервалом, прежде чем начать удлинять паузу.
FAILURE_THRESHOLD = 3
# Потолок паузы между попытками упавшей задачи, секунды.
MAX_BACKOFF = 300.0
ERROR_TEXT_LIMIT = 200


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class BackgroundTask:
    """Описание одной фоновой задачи и счётчики её работы (сырьё для ``.status`` и health)."""
    name: str
    callback: TaskCallback
    interval: float
    task: asyncio.Task[None] | None = None
    stopped: bool = False
    # Состояние: сырьё для .status и health (этап 7).
    runs: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    last_run: datetime | None = None
    last_success: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None

    @property
    def alive(self) -> bool:
        """Есть ли у задачи живой asyncio.Task."""
        return self.task is not None and not self.task.done()

    @property
    def status(self) -> str:
        """RUNNING, FAILING (идут сбои подряд) или STOPPED."""
        if not self.alive:
            return STOPPED
        return FAILING if self.consecutive_failures else RUNNING


class BackgroundManager:
    """Управляет независимыми циклическими фоновыми задачами.

    Сбой одной задачи не влияет на остальные: ошибки гасятся внутри цикла ``_runner``.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = FAILURE_THRESHOLD,
        max_backoff: float = MAX_BACKOFF,
        on_failing: Callable[[BackgroundTask], None] | None = None,
    ) -> None:
        """``on_failing(задача)`` вызывается один раз за серию, когда сбоев подряд набралось
        ``failure_threshold`` (например, чтобы сообщить владельцу). Её ошибки не мешают задаче."""
        self._tasks: dict[str, BackgroundTask] = {}
        self.on_failing = on_failing
        self.failure_threshold = max(1, failure_threshold)
        self.max_backoff = max_backoff

    def register(self, name: str, callback: TaskCallback, *, interval: float) -> BackgroundTask:
        """Добавляет задачу, но не запускает её (см. ``start``).

        Raises:
            ValueError: пустое имя, неположительный интервал или дубликат имени.
        """
        name = name.strip()
        if not name:
            raise ValueError("Имя фоновой задачи не может быть пустым")
        if interval <= 0:
            raise ValueError("Интервал должен быть больше нуля")
        if name in self._tasks:
            raise ValueError(f"Фоновая задача '{name}' уже зарегистрирована")

        item = BackgroundTask(name=name, callback=callback, interval=interval)
        self._tasks[name] = item
        return item

    async def start(self, name: str) -> None:
        """Запускает задачу по имени. Для уже живой задачи ничего не делает.

        Raises:
            KeyError: задача не зарегистрирована.
        """
        item = self._tasks[name]
        # Идемпотентность: двойной start не должен породить вторую копию цикла.
        if item.alive:
            return
        item.stopped = False
        item.consecutive_failures = 0  # новый запуск: прежние сбои не считаем
        item.task = asyncio.create_task(self._runner(item), name=f"candy-bg:{item.name}")

    async def start_all(self) -> None:
        """Запускает все зарегистрированные задачи."""
        for name in tuple(self._tasks):
            await self.start(name)

    async def stop(self, name: str) -> None:
        """Останавливает задачу и дожидается её завершения. Неизвестное имя игнорируется."""
        item = self._tasks.get(name)
        if item is None:
            return
        # Флаг ставим до cancel(): цикл не начнёт новый круг, даже если отмена опоздает.
        item.stopped = True
        if item.task and not item.task.done():
            item.task.cancel()
            try:
                await item.task
            # Отмена задачи здесь ожидаема и не ошибка. Оборотная сторона: так же гасится
            # отмена самого вызывающего stop().
            except asyncio.CancelledError:
                pass
        item.task = None

    async def stop_all(self) -> None:
        """Останавливает все задачи по очереди."""
        for name in tuple(self._tasks):
            await self.stop(name)

    def remove(self, name: str) -> None:
        """Удаляет остановленную задачу из реестра.

        Raises:
            RuntimeError: задача ещё работает.
        """
        item = self._tasks.get(name)
        if item is None:
            return
        if item.alive:
            raise RuntimeError("Сначала остановите фоновую задачу")
        del self._tasks[name]

    def list(self) -> list[BackgroundTask]:
        """Снимок всех задач (копия списка, реестр менять нельзя)."""
        return list(self._tasks.values())

    def get(self, name: str) -> BackgroundTask | None:
        """Задача по имени или None."""
        return self._tasks.get(name)

    def delay_for(self, item: BackgroundTask) -> float:
        """Пауза перед следующим запуском.

        Пока серия сбоев короче порога, это обычный интервал. Дальше пауза
        удваивается с каждым сбоем, но не больше ``max_backoff`` (и не меньше
        самого интервала).
        """
        # Сколько сбоев сверх порога: растёт пауза только после того, как порог исчерпан.
        extra = item.consecutive_failures - self.failure_threshold + 1
        if extra <= 0:
            return item.interval
        # Интервал больше max_backoff не должен урезаться потолком.
        ceiling = max(item.interval, self.max_backoff)
        return min(item.interval * (2 ** min(extra, 30)), ceiling)

    async def _runner(self, item: BackgroundTask) -> None:
        logger.info("Фоновая задача '%s' запущена.", item.name)
        try:
            while not item.stopped:
                await self._run_once(item)
                await asyncio.sleep(self.delay_for(item))
        # Отмену пробрасываем как есть: её штатно потребляет stop(). Лог остановки пишет finally.
        except asyncio.CancelledError:
            raise
        finally:
            logger.info("Фоновая задача '%s' остановлена.", item.name)

    async def _run_once(self, item: BackgroundTask) -> None:
        item.runs += 1
        item.last_run = _now()
        try:
            result = item.callback()
            if inspect.isawaitable(result):
                await result
        # CancelledError наследует BaseException; явный проброс страхует от смены базового класса.
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Ошибка одной задачи не должна остановить остальные.
            self._on_failure(item, exc)
        else:
            self._on_success(item)

    def _on_success(self, item: BackgroundTask) -> None:
        if item.consecutive_failures:
            logger.info(
                "Фоновая задача '%s' восстановилась после %d сбоев подряд.",
                item.name,
                item.consecutive_failures,
            )
        item.consecutive_failures = 0
        item.last_success = _now()

    def _report_failing(self, item: BackgroundTask) -> None:
        """Сообщает наружу, что задача сбоит; любая ошибка обратного вызова только пишется в лог."""
        if self.on_failing is None:
            return
        try:
            self.on_failing(item)
        except Exception:
            logger.exception("Ошибка обратного вызова on_failing для задачи '%s'.", item.name)

    def _on_failure(self, item: BackgroundTask, exc: Exception) -> None:
        item.failures += 1
        item.consecutive_failures += 1
        item.last_error_at = _now()
        text = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        item.last_error = text[:ERROR_TEXT_LIMIT]

        count = item.consecutive_failures
        if count == 1:
            logger.exception("Ошибка фоновой задачи '%s'.", item.name)
            if self.failure_threshold == 1:
                self._report_failing(item)
            return
        # Дальше без traceback и не на каждом сбое: степени двойки и порог.
        if count == self.failure_threshold:
            logger.warning(
                "Фоновая задача '%s' упала %d раз подряд, пауза между попытками растёт: %s",
                item.name,
                count,
                item.last_error,
            )
            self._report_failing(item)
        elif count & (count - 1) == 0:
            logger.warning(
                "Фоновая задача '%s' всё ещё падает (%d подряд): %s",
                item.name,
                count,
                item.last_error,
            )
        else:
            logger.debug("Сбой фоновой задачи '%s' (%d подряд): %s", item.name, count, item.last_error)
