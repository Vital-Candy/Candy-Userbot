"""Остановка и откат запуска: набор изолированных шагов с таймаутом на каждый."""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from utils.logger import logger

DEFAULT_STEP_TIMEOUT = 20.0


@dataclass(slots=True)
class StepResult:
    """Итог одного шага остановки: успех, текст ошибки и признак таймаута."""

    label: str
    ok: bool
    error: str | None = None
    timed_out: bool = False


class ShutdownSequence:
    """Выполняет шаги по порядку. Сбой или зависание одного шага не мешает остальным.

    ``timeout`` ограничивает каждый шаг отдельно (0 или None: без лимита). Зависший
    ``client.disconnect()`` в плохой сети иначе держал бы процесс до принудительного выхода.
    """

    def __init__(self, timeout: float | None = DEFAULT_STEP_TIMEOUT) -> None:
        self._timeout = timeout if timeout and timeout > 0 else None
        self._steps: list[tuple[str, Callable[[], Any]]] = []

    def add(self, label: str, action: Callable[[], Any]) -> None:
        """Добавляет шаг в конец очереди. ``action``: обычная функция или корутинная функция."""
        self._steps.append((label, action))

    async def run(self) -> list[StepResult]:
        """Выполняет шаги строго по очереди и возвращает результат каждого.

        Ошибки шагов наружу не выходят (они в ``StepResult``); пробрасывается только отмена.
        """
        results: list[StepResult] = []
        for label, action in self._steps:
            results.append(await self._run_step(label, action))
        return results

    async def _run_step(self, label: str, action: Callable[[], Any]) -> StepResult:
        async def call() -> None:
            """Вызывает шаг и дожидается результата, если он awaitable."""
            result = action()
            if inspect.isawaitable(result):
                await result

        try:
            # По таймауту wait_for отменяет зависший шаг, так что он не остаётся висеть в фоне.
            await asyncio.wait_for(call(), self._timeout)
        except asyncio.TimeoutError:
            logger.error("Остановка: шаг «%s» не завершился за %g с, иду дальше.", label, self._timeout)
            return StepResult(label, False, "таймаут", timed_out=True)
        except asyncio.CancelledError:
            # Отмена самой остановки не должна превращаться в «ошибку шага».
            raise
        except Exception as exc:
            logger.exception("Ошибка при остановке: %s", label)
            return StepResult(label, False, str(exc) or type(exc).__name__)
        return StepResult(label, True)
