"""Асинхронный ввод строки с терминала для интерактивных шагов (вход в аккаунт, подтверждения)."""
from __future__ import annotations

import asyncio
import getpass
import threading


async def ask(prompt: str, *, secret: bool = False) -> str:
    """Читает строку с терминала, не блокируя event loop и не мешая выходу.

    Ввод идёт в daemon-потоке, а не через ``asyncio.to_thread``: поток из executor
    нельзя отменить, и процесс при остановке ждал бы нажатия Enter.
    ``secret=True`` скрывает ввод (``getpass``). При закрытом stdin бросает ``EOFError``.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()

    def deliver(setter, value) -> None:
        """Передаёт результат в future из потока, если задачу не отменили."""
        if not future.done():  # задачу могли отменить, пока поток ждал ввода
            setter(value)

    def worker() -> None:
        """Тело daemon-потока: читает строку и возвращает её (или ошибку) в event loop."""
        # Исключение передаём в future, чтобы EOFError дошёл до вызывающего, а не умер в потоке.
        try:
            value = getpass.getpass(prompt) if secret else input(prompt)
        except Exception as exc:  # EOFError и ошибки терминала
            callback = (deliver, future.set_exception, exc)
        else:
            callback = (deliver, future.set_result, value)
        try:
            loop.call_soon_threadsafe(*callback)
        except RuntimeError:  # loop уже закрыт
            pass

    threading.Thread(target=worker, name="candy-prompt", daemon=True).start()
    return await future
