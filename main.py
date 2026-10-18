"""Точка входа Candy Userbot: разбор аргументов, сигналы, запуск приложения и коды выхода.

Связывает ``core.app.UserbotApp`` с процессом: ставит обработчики остановки и перезапускает процесс.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import subprocess
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from config.settings import LOG_LEVEL, settings
from core.errors import UserError, handle_fatal_error
from utils.logger import logger, set_level, setup_file_logging

# Коды выхода процесса: их читает супервизор (systemd, цикл перезапуска в Termux).
EXIT_OK = 0  # штатная остановка
EXIT_ERROR = 1  # сбой, который имеет смысл повторить
EXIT_CONFIG = 2  # ошибка настройки или входа: перезапуск не поможет, нужен человек
EXIT_FORCED = 130  # повторный сигнал: принудительный выход (128 + SIGINT)


def _force_exit(code: int) -> None:
    """Немедленно завершает процесс, минуя штатную остановку (зависшее завершение)."""
    # os._exit не вызывает atexit и не ждёт потоки, поэтому логи сбрасываем вручную.
    logging.shutdown()
    os._exit(code)


class StopSignals:
    """Переводит SIGINT / SIGTERM / SIGHUP в запрос на остановку.

    Первый сигнал запускает штатную остановку, второй завершает процесс сразу
    (на случай, если остановка зависла). Если сигналов через event loop нет
    (Windows), работает запасной путь: ``asyncio.run`` отменяет главную задачу.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        event: asyncio.Event,
        force_exit=_force_exit,
    ) -> None:
        self._loop = loop
        self._event = event
        self._force_exit = force_exit
        self._installed: list[signal.Signals] = []
        self._count = 0

    def install(self) -> None:
        """Подписывается на доступные сигналы; недоступные на платформе пропускает."""
        for name in ("SIGINT", "SIGTERM", "SIGHUP"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            # nohup выставляет SIG_IGN на SIGHUP: уважаем это и не перехватываем.
            if name == "SIGHUP" and signal.getsignal(sig) == signal.SIG_IGN:
                continue
            try:
                self._loop.add_signal_handler(sig, self._on_signal, name)
            except (NotImplementedError, RuntimeError, ValueError):
                continue  # Windows или не главный поток
            self._installed.append(sig)

    def uninstall(self) -> None:
        """Снимает обработчики, поставленные в ``install``."""
        for sig in self._installed:
            try:
                self._loop.remove_signal_handler(sig)
            except (NotImplementedError, RuntimeError, ValueError):
                pass
        self._installed.clear()

    def _on_signal(self, name: str) -> None:
        """Первый сигнал просит штатную остановку, последующие убивают процесс."""
        self._count += 1
        if self._count == 1:
            logger.info("Получен %s, останавливаюсь...", name)
            self._event.set()
        else:
            logger.warning("Повторный %s: принудительный выход.", name)
            self._force_exit(EXIT_FORCED)


async def _until_stop(task: asyncio.Future, stop_event: asyncio.Event) -> bool:
    """Ждёт задачу или запрос остановки.

    True: задача завершилась сама. False: раньше пришёл запрос остановки,
    задача отменена.
    """
    waiter = asyncio.ensure_future(stop_event.wait())
    try:
        await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # Не оставляем висеть вспомогательную задачу ожидания события.
        waiter.cancel()
    if task.done():
        return True
    task.cancel()
    try:
        await task  # дожидаемся отмены, чтобы не терять исключения «Task exception never retrieved»
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.debug("Ошибка прерванной задачи", exc_info=True)
    return False


def _report(exc: Exception) -> int:
    """Показывает ошибку пользователю и возвращает код выхода.

    UserError и закрытый ввод: EXIT_CONFIG (супервизор не должен гонять перезапуски
    по кругу). Остальное: EXIT_ERROR, такой запуск стоит повторить.
    """
    if isinstance(exc, UserError):
        logger.error("%s", exc)
        return EXIT_CONFIG
    if isinstance(exc, EOFError):
        logger.error("Ввод закрыт: вход в аккаунт нужно выполнять в терминале.")
        return EXIT_CONFIG
    handle_fatal_error(exc)
    return EXIT_ERROR


async def run_app(app: Any, stop_event: asyncio.Event) -> int:
    """Запускает приложение и возвращает код выхода процесса.

    0: штатная остановка (сигнал, ``.stop``, консоль).
    1: сбой запуска, фатальная ошибка или потеря связи с Telegram (можно перезапустить).
    2: ошибка настройки или входа (нужно вмешательство человека).
    """
    code = EXIT_OK
    start_task = run_task = None
    try:
        start_task = asyncio.ensure_future(app.start())
        if not await _until_stop(start_task, stop_event):
            logger.info("Остановка во время запуска.")
            return EXIT_OK
        start_task.result()  # пробрасывает исключение запуска, если оно было

        run_task = asyncio.ensure_future(app.run())
        if not await _until_stop(run_task, stop_event):
            return EXIT_OK
        run_task.result()

        if not app.is_stopping:
            # run() вернулся сам, никто не просил остановку: связь потеряна насовсем.
            logger.error("Соединение с Telegram потеряно. Завершаю работу с ошибкой.")
            code = EXIT_ERROR
    except asyncio.CancelledError:
        # Ctrl+C там, где нет обработчиков сигналов (Windows).
        logger.info("Остановка по запросу пользователя.")
    except Exception as exc:
        code = _report(exc)
    finally:
        # app.stop() вызываем всегда, в том числе после сбоя, чтобы закрыть клиентов и базу.
        for task in (start_task, run_task):
            if task is not None and not task.done():
                task.cancel()
        await app.stop()
    return code


async def run_cli(action: Callable[[], Awaitable[None]], stop_event: asyncio.Event) -> int:
    """Выполняет разовую команду (--add-account, --restore) с теми же сигналами и кодами выхода."""
    task = asyncio.ensure_future(action())
    try:
        if not await _until_stop(task, stop_event):
            logger.info("Прервано.")
            return EXIT_OK
        task.result()
        return EXIT_OK
    except asyncio.CancelledError:
        logger.info("Прервано.")
        return EXIT_OK
    except Exception as exc:
        return _report(exc)
    finally:
        if not task.done():
            task.cancel()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Разбирает аргументы командной строки; режимы ``--add-account``, ``--restore``, ``--check`` взаимоисключающие."""
    parser = argparse.ArgumentParser(prog="main.py", description="Candy Userbot")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--add-account",
        action="store_true",
        help="добавить аккаунт или войти заново (заменить отозванную сессию) и выйти",
    )
    group.add_argument(
        "--restore",
        metavar="ZIP",
        help="восстановить аккаунт из backup (имя файла из data/backups или путь) и выйти",
    )
    group.add_argument(
        "--check",
        action="store_true",
        help="проверить окружение, каталоги, базу и аккаунт без подключения к Telegram, и выйти",
    )
    return parser.parse_args(argv)


# Выставляется в amain, когда приложение просит перезапуск (переключение аккаунта).
_restart_requested = False


async def amain(args: argparse.Namespace | None = None) -> int:
    """Выбирает режим по аргументам (проверка, разовая команда или работа) и возвращает код выхода."""
    global _restart_requested
    # Импорт внутри функции: тяжёлые модули (Telethon) не нужны для ``--help`` и разбора аргументов.
    from core.app import UserbotApp

    try:
        app = UserbotApp()
    except Exception as exc:
        return _report(exc)

    stop_event = asyncio.Event()
    signals = StopSignals(asyncio.get_running_loop(), stop_event)
    signals.install()
    try:
        if args is not None and args.check:
            from core.doctor import run_checks

            return run_checks(app.accounts)
        if args is not None and args.add_account:
            return await run_cli(app.cli_add_account, stop_event)
        if args is not None and args.restore:
            return await run_cli(lambda: app.cli_restore(args.restore), stop_event)
        code = await run_app(app, stop_event)
        # Перезапускаем только после штатной остановки: при ошибке решает супервизор.
        _restart_requested = bool(getattr(app, "restart_requested", False)) and code == EXIT_OK
        return code
    finally:
        signals.uninstall()


def _restart_process() -> None:
    """Запускает ту же программу заново (после переключения аккаунта)."""
    logger.info("Перезапуск процесса...")
    logging.shutdown()
    command = [sys.executable, os.path.abspath(sys.argv[0])]
    if os.name == "nt":  # execv на Windows не заменяет процесс, а порождает новый
        subprocess.Popen(command)
        return
    os.execv(sys.executable, command)


def main(argv: list[str] | None = None) -> int:
    """Синхронная точка входа: настраивает логи, запускает ``amain`` и при необходимости перезапускает процесс."""
    args = parse_args(argv)
    set_level(LOG_LEVEL)
    setup_file_logging(settings.log_dir, settings.log_max_bytes, settings.log_backups)
    for message in settings.warnings:
        logger.warning(message)
    try:
        code = asyncio.run(amain(args))
    except KeyboardInterrupt:
        logger.info("Остановка по запросу пользователя.")
        return EXIT_OK
    if _restart_requested:
        # Перезапуск после закрытия event loop, когда все ресурсы уже освобождены.
        _restart_process()
    return code


if __name__ == "__main__":
    sys.exit(main())
