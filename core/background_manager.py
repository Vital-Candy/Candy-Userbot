from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger("background_manager")

Worker = Callable[[], Awaitable[None]]


class BackgroundManager:
    """
    Универсальный менеджер фоновых задач одного аккаунта.

    Он не знает ничего о time_name, time_bio или других модулях.
    Он только:
      - запускает именованные asyncio-задачи;
      - не допускает дубликаты;
      - корректно отменяет задачи;
      - хранит JSON-состояние конкретного аккаунта.
    """

    STATE_VERSION = 1

    def __init__(self, state_path: Path) -> None:
        self.state_path = Path(state_path)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._state: dict[str, Any] = {}
        self._closed = False
        self.load_state()

    # ---------- состояние ----------

    def load_state(self) -> None:
        self._state = {}
        if not self.state_path.exists():
            return

        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Корень state.json должен быть объектом")

            version = raw.get("version", self.STATE_VERSION)
            if version != self.STATE_VERSION:
                raise ValueError(f"Неподдерживаемая версия состояния: {version}")

            tasks = raw.get("tasks", {})
            if not isinstance(tasks, dict):
                raise ValueError("Поле tasks должно быть объектом")

            self._state = tasks
        except Exception as exc:
            logger.error("Не удалось загрузить %s: %s", self.state_path, exc)
            self._state = {}

    def save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.STATE_VERSION,
            "tasks": self._state,
        }
        temporary = self.state_path.with_suffix(
            self.state_path.suffix + ".tmp"
        )
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.state_path)

    def get_state(
        self,
        name: str,
        default: Any = None,
    ) -> Any:
        return self._state.get(name, default)

    def set_state(
        self,
        name: str,
        value: Any,
        *,
        save: bool = True,
    ) -> None:
        if not name or not isinstance(name, str):
            raise ValueError("Имя состояния должно быть непустой строкой")

        self._state[name] = value
        if save:
            self.save_state()

    def update_state(
        self,
        name: str,
        **changes: Any,
    ) -> dict[str, Any]:
        current = self._state.get(name, {})
        if not isinstance(current, dict):
            raise TypeError(
                f"Состояние {name!r} не является объектом"
            )

        updated = dict(current)
        updated.update(changes)
        self._state[name] = updated
        self.save_state()
        return updated

    def delete_state(
        self,
        name: str,
        *,
        save: bool = True,
    ) -> None:
        self._state.pop(name, None)
        if save:
            self.save_state()

    # ---------- задачи ----------

    def is_running(self, name: str) -> bool:
        task = self._tasks.get(name)
        return task is not None and not task.done()

    def running_names(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, task in self._tasks.items()
            if not task.done()
        )

    async def start(
        self,
        name: str,
        worker: Worker,
    ) -> bool:
        """
        Возвращает True, если задача создана.
        Возвращает False, если такая задача уже работает.
        """
        if self._closed:
            raise RuntimeError("BackgroundManager уже закрыт")

        if not name or not isinstance(name, str):
            raise ValueError("Имя задачи должно быть непустой строкой")

        if self.is_running(name):
            return False

        result = worker()
        if not inspect.isawaitable(result):
            raise TypeError(
                "worker должен возвращать awaitable"
            )

        task = asyncio.create_task(
            result,
            name=f"background:{name}",
        )
        self._tasks[name] = task
        task.add_done_callback(
            lambda finished, task_name=name:
            self._on_task_done(task_name, finished)
        )
        return True

    def _on_task_done(
        self,
        name: str,
        task: asyncio.Task[None],
    ) -> None:
        if self._tasks.get(name) is task:
            self._tasks.pop(name, None)

        if task.cancelled():
            return

        try:
            error = task.exception()
        except asyncio.CancelledError:
            return

        if error is not None:
            logger.exception(
                "Фоновая задача %s завершилась с ошибкой",
                name,
                exc_info=(
                    type(error),
                    error,
                    error.__traceback__,
                ),
            )
        else:
            logger.info(
                "Фоновая задача %s завершилась",
                name,
            )

    async def stop(self, name: str) -> bool:
        task = self._tasks.get(name)
        if task is None:
            return False

        if not task.done():
            task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            if self._tasks.get(name) is task:
                self._tasks.pop(name, None)

        return True

    async def stop_all(self) -> None:
        tasks = list(self._tasks.items())

        for _, task in tasks:
            if not task.done():
                task.cancel()

        if tasks:
            await asyncio.gather(
                *(task for _, task in tasks),
                return_exceptions=True,
            )

        self._tasks.clear()

    async def close(self) -> None:
        if self._closed:
            return

        self._closed = True
        await self.stop_all()
        self.save_state()
