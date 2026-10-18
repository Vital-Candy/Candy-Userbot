"""Локальная консоль управления: строка ``candy>`` или экранное меню (см. ``core.menu``).

Запускается из ``core.app`` последним шагом старта и останавливается первым шагом остановки.
"""
from __future__ import annotations

import asyncio
import sys
import threading
from typing import Any

from config.settings import BASE_DIR, UI_MODE
from core.menu import MenuUI
from core.summary import module_lines, plugin_info_lines, plugin_lines, task_lines
from utils.logger import logger, mute_console, unmute_console


class ConsoleManager:
    """Локальная консоль управления.

    Ввод читается в daemon-потоке, а не через ``asyncio.to_thread``: поток из
    executor нельзя отменить, и при выходе процесс ждал бы нажатия Enter.
    Без TTY (фон, nohup, systemd) консоль не запускается.
    """

    def __init__(self, app: Any, ui: str | None = None) -> None:
        self.app = app
        self._ui = ui or UI_MODE
        self._muted = False
        self._task: asyncio.Task | None = None
        self._thread: threading.Thread | None = None
        self._stopping = False
        # Номер «поколения» потока-читателя: после stop() старый поток видит смену номера и выходит.
        self._generation = 0

    @staticmethod
    def _has_tty() -> bool:
        """Подключён ли stdin к терминалу. Закрытый или подменённый stdin считается «нет»."""
        stdin = sys.stdin
        try:
            return bool(stdin is not None and stdin.isatty())
        except (AttributeError, ValueError):
            return False

    async def start(self) -> None:
        """Запускает консоль или меню. Без TTY ничего не делает. Повторный вызов игнорируется."""
        if self._task is not None:
            return
        if not self._has_tty():
            logger.info("Консоль отключена: stdin не является терминалом.")
            return

        self._stopping = False
        if self._ui == "menu":
            # Меню само читает ввод построчно; логи до его закрытия идут только в файл и память.
            mute_console()
            self._muted = True
            menu = MenuUI(self.app, logo_path=BASE_DIR / "logo.txt")
            self._task = asyncio.create_task(self._run_menu(menu), name="candy-menu")
            return
        self._generation += 1
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._thread = threading.Thread(
            target=self._read_loop,
            args=(loop, queue, self._generation),
            name="candy-console-input",
            daemon=True,
        )
        self._thread.start()
        self._task = asyncio.create_task(self._run(queue), name="candy-console")
        logger.info("Консоль управления активна. Введите 'help'.")

    async def _run_menu(self, menu: MenuUI) -> None:
        """Задача экранного меню; по завершении возвращает логи в консоль."""
        # Меню может закрыться само (выход, закрытый ввод): тогда логи нужно вернуть в консоль.
        try:
            await menu.run()
        finally:
            self._release_console()

    def _release_console(self) -> None:
        """Возвращает вывод логов в консоль, если меню его скрывало."""
        if self._muted:
            self._muted = False
            unmute_console()

    async def stop(self) -> None:
        """Останавливает консоль. Безопасно вызывать повторно и из самой консольной команды."""
        self._stopping = True
        self._release_console()
        self._generation += 1  # старый поток-читатель завершится после своего input()
        task, self._task = self._task, None
        self._thread = None
        # Если stop() вызван командой из самой консоли, ждать свою же задачу нельзя.
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _read_loop(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[str | None],
        generation: int,
    ) -> None:
        """Тело потока ввода: читает строки и передаёт их в event loop через ``queue``.

        ``None`` в очереди означает конец ввода (EOF или ошибка терминала).
        """
        while generation == self._generation:
            try:
                line: str | None = input("candy> ")
            except EOFError:
                line = None
            except Exception:  # noqa: BLE001 - поток не должен падать с трейсбеком
                logger.exception("Ошибка чтения консоли.")
                line = None
            # input() нельзя прервать, поэтому после остановки строку просто выбрасываем.
            if generation != self._generation:
                return
            try:
                loop.call_soon_threadsafe(queue.put_nowait, line)
            except RuntimeError:  # loop уже закрыт
                return
            if line is None:
                return

    async def _run(self, queue: asyncio.Queue[str | None]) -> None:
        """Цикл обработки введённых строк до остановки или конца ввода."""
        while not self._stopping:
            line = await queue.get()
            if line is None:
                return
            try:
                await self.execute(line.strip())
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка консольной команды.")

    async def execute(self, line: str) -> str | None:
        """Выполняет одну консольную команду. Возвращает напечатанный текст (None для пустой строки)."""
        if not line:
            return None
        parts = line.split()
        command, args = parts[0].lower(), parts[1:]
        if command in {"help", "?"}:
            return self._print(
                "help | status [all] | plugins | plugin load <name> | "
                "plugin unload <name> | plugin reload <name> | plugin info <name> | account list | "
                "account use <id|@name> | backup create [id|@name] | backup list | "
                "backup restore <file> | stop"
            )
        if command == "status":
            return self._status(args)
        if command == "plugins":
            return self._plugins()
        if command == "plugin":
            return await self._plugin(args)
        if command == "account":
            return await self._account(args)
        if command == "backup":
            return self._backup(args)
        if command == "stop":
            # stop() идемпотентен и безопасен из консольной задачи: она сама не ждёт свою отмену.
            await self.app.stop()
            return self._print("Userbot stopped.")
        return self._print(f"Неизвестная команда: {command}")

    def _status(self, args: list[str]) -> str:
        """``status``: сводка здоровья; ``status all``: ещё модули и фоновые задачи."""
        if args not in ([], ["all"]):
            return self._print("Использование: status [all]")
        text = "\n".join(self.app.health().lines())
        if args == ["all"]:
            text += "\n\nМодули:\n" + ("\n".join(module_lines(self.app)) or "нет")
            text += "\n\nФоновые задачи:\n" + ("\n".join(task_lines(self.app)) or "нет")
        return self._print(text)

    def _plugins(self) -> str:
        """Список плагинов и их состояние."""
        return self._print("\n".join(plugin_lines(self.app.plugins)) or "Плагинов нет.")

    async def _plugin(self, args: list[str]) -> str:
        """``plugin load|unload|reload|info <name>``."""
        if len(args) != 2 or args[0] not in {"load", "unload", "reload", "info"}:
            return self._print("Использование: plugin <load|unload|reload|info> <name>")
        action, name = args
        try:
            if action == "info":
                return self._print("\n".join(plugin_info_lines(self.app.plugins.info(name))))
            ok = await getattr(self.app.plugins, action)(name)
        except KeyError:
            return self._print(f"Плагин не найден: {name}")
        text = f"plugin {action} {name}: {'OK' if ok else 'FAILED'}"
        if not ok:
            error = self.app.plugins.info(name)["error"]
            if error:
                text += f" ({error})"
        return self._print(text)

    async def _account(self, args: list[str]) -> str:
        """``account list`` и ``account use <id|@name>`` (переключение перезапускает процесс)."""
        if not args or args[0] == "list":
            return self._print(self.app.account_control.describe())
        if args[0] == "use" and len(args) == 2:
            try:
                account = await self.app.switch_account(args[1])
            except (LookupError, ValueError, RuntimeError) as exc:
                return self._print(f"Ошибка: {exc}")
            return self._print(f"Переключение на {account.display_name}...")
        return self._print("Использование: account list | account use <id|@name>")

    def _backup(self, args: list[str]) -> str:
        """``backup create|list|restore``: резервные копии аккаунтов."""
        control = self.app.account_control
        action = args[0] if args else ""
        try:
            if action == "create" and len(args) <= 2:
                path = control.backup_create(args[1] if len(args) == 2 else None)
                return self._print(f"Backup создан: {path}")
            if action == "list" and len(args) == 1:
                files = control.backup_list()
                return self._print("\n".join(f.name for f in files) or "Backup-ов нет.")
            if action == "restore" and len(args) == 2:
                account = control.backup_restore(args[1])
                return self._print(f"Аккаунт {account.display_name} восстановлен.")
        except FileNotFoundError:
            return self._print("Файл backup не найден.")
        except (LookupError, ValueError, FileExistsError, RuntimeError) as exc:
            return self._print(f"Ошибка: {exc}")
        return self._print("Использование: backup create [id|@name] | backup list | backup restore <file>")

    @staticmethod
    def _print(text: str) -> str:
        """Печатает текст и возвращает его же (результат удобно проверять в тестах)."""
        print(text)
        return text
