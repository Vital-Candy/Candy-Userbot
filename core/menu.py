"""Терминальное меню: логотип, активный аккаунт и несколько нужных действий.

Только стандартная библиотека и ANSI-коды. Ввод построчный (номер и Enter), поэтому
работает в любом терминале, включая Termux. Пока меню открыто, логи в консоль не
выводятся (они идут в файл и в память), чтобы не портить экран.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from core.errors import UserError
from core.health import OK, format_uptime
from core.version import CORE_VERSION
from utils.logger import logger, ring
from utils.prompt import ask as default_ask

DEFAULT_LOGO = r"""
  ____                _
 / ___|__ _ _ __   __| |_   _
| |   / _` | '_ \ / _` | | | |
| |__| (_| | | | | (_| | |_| |
 \____\__,_|_| |_|\__,_|\__, |
                        |___/
""".strip("\n")

MAX_LOGO_LINES = 20  # выше логотип не показываем: он вытеснит меню с экрана телефона
FALLBACK_TITLE = "Candy Userbot"  # запасная строка, если ни один логотип не помещается
LOG_BACKLOG = 25  # сколько последних строк лога показать при входе в «Логи»
YES = {"y", "yes", "д", "да"}  # ответы, считающиеся согласием

# ANSI-последовательности: очистка экрана вместе с буфером прокрутки и цвета.
CLEAR = "\033[2J\033[3J\033[H"
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ACCENT = "\033[38;5;213m"  # розовый, под название


def _read_logo_file(path: Path | None) -> list[str]:
    """Строки логотипа из файла без пустых краёв. Пустой список, если файла нет или он пуст."""
    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.replace("\t", "    ").splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    return [line.rstrip() for line in lines]


def load_logo(path: Path | None, width: int) -> list[str]:
    """Логотип для главного экрана.

    Порядок выбора: ``logo.txt`` (если он помещается по ширине и высоте экрана), затем
    встроенный логотип, затем простая строка. Обрезать рисунок нельзя: у картинки, у которой
    отрезан край, вид хуже, чем у запасного логотипа.
    """
    for candidate in (_read_logo_file(path), DEFAULT_LOGO.splitlines()):
        if candidate and len(candidate) <= MAX_LOGO_LINES and max(len(line) for line in candidate) <= width:
            return candidate
    return [FALLBACK_TITLE]


class MenuUI:
    """Экранное меню управления: аккаунты, логи, обновление, остановка.

    Ввод, вывод, цвет и ширина внедряются через параметры, что позволяет тестировать без TTY.
    """

    def __init__(
        self,
        app: Any,
        *,
        ask: Callable[..., Awaitable[str]] = default_ask,
        write: Callable[[str], None] | None = None,
        logo_path: Path | None = None,
        clear: bool = True,
        color: bool | None = None,
        width: int | None = None,
    ) -> None:
        """``color=None``: цвет включается автоматически (TTY, нет ``NO_COLOR``, ``TERM`` не dumb)."""
        self.app = app
        self._ask = ask
        self._write = write or (lambda text: print(text, flush=True))
        self._logo_path = logo_path
        self._clear = clear
        if color is None:
            color = sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"
        self._color = color
        self._width = width

    # ------------------------------------------------------------------ вывод

    @property
    def width(self) -> int:
        """Ширина экрана в символах: заданная явно или размер терминала (по умолчанию 80)."""
        return self._width or shutil.get_terminal_size((80, 24)).columns

    def _paint(self, text: str, *codes: str) -> str:
        """Оборачивает текст в ANSI-коды, если цвет включён."""
        return f"{''.join(codes)}{text}{RESET}" if self._color and codes else text

    def screen(self) -> str:
        """Главный экран целиком (без очистки)."""
        lines = [self._paint(line, ACCENT, BOLD) for line in load_logo(self._logo_path, self.width)]
        lines.append("")
        lines += self._status_lines()
        lines += [
            "",
            "  1  Аккаунты",
            "  2  Логи в реальном времени",
            "  3  Обновление",
            "  4  Остановить бота",
            "",
        ]
        return "\n".join(lines)

    def _status_lines(self) -> list[str]:
        """Строки «Аккаунт / Состояние / Версия» для шапки главного экрана."""
        account = getattr(self.app, "account", None)
        name = account.display_name if account is not None else "нет"
        try:
            report = self.app.health()
            state = "работает" if report.status == OK else ("с проблемами" if report.status == "degraded" else "не работает")
            icon = {"ok": "✅", "degraded": "⚠️"}.get(report.status, "❌")
            uptime = format_uptime(report.uptime) if report.uptime is not None else "-"
        except Exception:
            # Шапка не должна ронять меню: при сбое health() показываем «неизвестно».
            state, icon, uptime = "неизвестно", "❔", "-"
        label = lambda text: self._paint(f"{text:<11}", DIM)  # noqa: E731
        return [
            f"  {label('Аккаунт')}{self._paint(name, BOLD)}",
            f"  {label('Состояние')}{icon} {state}",
            f"  {label('Версия')}{CORE_VERSION}   {label('Аптайм')}{uptime}",
        ]

    def _show(self, text: str = "") -> None:
        """Выводит строку через внедрённую функцию записи."""
        self._write(text)

    def _clear_screen(self) -> None:
        """Очищает экран, если очистка не отключена (в тестах отключается)."""
        if self._clear:
            self._write(CLEAR)

    # ------------------------------------------------------------------ ввод

    async def _input(self, prompt: str) -> str | None:
        """Строка ввода или None, если ввод закрыт."""
        try:
            return (await self._ask(prompt)).strip()
        except EOFError:
            return None

    async def _confirm(self, question: str) -> bool:
        """Вопрос «да/нет»: по умолчанию нет, закрытый ввод тоже означает нет."""
        answer = await self._input(f"{question} [y/N]: ")
        return answer is not None and answer.lower() in YES

    # ------------------------------------------------------------------ цикл

    async def run(self) -> None:
        """Главный цикл меню. Завершается выходом, остановкой бота или закрытием ввода."""
        while True:
            self._clear_screen()
            self._show(self.screen())
            choice = await self._input("Выбор (Enter: обновить экран): ")
            if choice is None:
                logger.info("Меню закрыто: ввод недоступен.")
                return
            try:
                if choice == "1":
                    await self.accounts()
                elif choice == "2":
                    if not await self.logs():
                        return
                elif choice == "3":
                    await self.update()
                elif choice == "4":
                    if await self._confirm("Остановить бота?"):
                        await self.app.stop()
                        return
                elif choice:
                    self._show(f"Нет пункта «{choice}».")
                    await self._input("Enter: назад")
            except asyncio.CancelledError:
                raise  # отмену (остановка приложения) нельзя глотать общим except Exception
            except UserError as exc:
                self._show(f"❌ {exc}")
                await self._input("Enter: назад")
            except Exception:
                logger.exception("Ошибка в меню.")
                self._show("❌ Ошибка, подробности в логах (пункт 2).")
                await self._input("Enter: назад")

    # ---------------------------------------------------------------- аккаунты

    async def accounts(self) -> None:
        """Подменю аккаунтов: переключение, добавление, резервная копия."""
        control = self.app.account_control
        while True:
            self._clear_screen()
            self._show(self._paint("Аккаунты", BOLD))
            self._show(control.describe())
            self._show("\n  1  Переключить\n  2  Добавить / войти заново\n  3  Резервная копия\n  0  Назад\n")
            choice = await self._input("Выбор: ")
            if choice in (None, "", "0"):
                return
            if choice == "1":
                await self._switch()
                if getattr(self.app, "is_stopping", False):
                    return
            elif choice == "2":
                await self._add()
            elif choice == "3":
                # Архивирование блокирующее: уводим в поток, чтобы не вешать event loop.
                path = await asyncio.to_thread(control.backup_create)
                self._show(f"✅ Копия создана: {path.name}")
                await self._input("Enter: назад")
            else:
                self._show(f"Нет пункта «{choice}».")

    async def _switch(self) -> None:
        """Выбор аккаунта по номеру и переключение (с перезапуском процесса)."""
        items = self.app.account_control.accounts.list()
        if len(items) < 2:
            self._show("Переключаться не на что: сохранён один аккаунт.")
            await self._input("Enter: назад")
            return
        active = self.app.account_control.accounts.get_active()
        for number, item in enumerate(items, 1):
            mark = " (активный)" if active is not None and item.account_id == active.account_id else ""
            self._show(f"  {number}  {item.display_name}{mark}")
        raw = await self._input("Номер аккаунта (Enter: отмена): ")
        if not raw:
            return
        if not raw.isdigit() or not 1 <= int(raw) <= len(items):
            self._show("Нет такого номера.")
            await self._input("Enter: назад")
            return
        target = items[int(raw) - 1]
        if not await self._confirm(f"Переключиться на {target.display_name}? Бот перезапустится."):
            return
        try:
            await self.app.switch_account(str(target.account_id))
        except ValueError as exc:
            self._show(f"ℹ️ {exc}")
            await self._input("Enter: назад")

    async def _add(self) -> None:
        """Интерактивный вход в аккаунт; новый аккаунт станет активным после перезапуска."""
        self._show("")
        account = await self.app.onboard_account(confirm_replace=True)
        self._show(f"✅ Аккаунт {account.display_name} сохранён и станет активным после перезапуска.")
        if await self._confirm("Перезапустить сейчас?"):
            await self.app.request_restart()

    # --------------------------------------------------------------------- логи

    async def logs(self) -> bool:
        """Показывает логи, пока не нажат Enter. False: ввод закрыт, меню нужно завершить."""
        self._clear_screen()
        self._show(self._paint("Логи в реальном времени (Enter: назад)", BOLD))
        self._show("-" * min(self.width, 60))
        for line in ring.lines(LOG_BACKLOG):
            self._show(line)

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str] = asyncio.Queue()

        def push(line: str) -> None:
            """Показывает новую строку лога (вызывается из подписки на кольцевой буфер)."""
            # Логи пишутся из любых потоков, поэтому в очередь кладём через call_soon_threadsafe.
            try:
                loop.call_soon_threadsafe(queue.put_nowait, line)
            except RuntimeError:  # loop закрыт
                pass

        unsubscribe = ring.subscribe(push)
        waiter = asyncio.ensure_future(self._input(""))
        getter: asyncio.Future | None = None
        try:
            while True:
                getter = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({waiter, getter}, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    self._show(getter.result())
                    getter = None
                if waiter in done:
                    return waiter.result() is not None
        finally:
            # Отписка и отмена ожидающих задач обязательны: иначе висит поток ввода/подписка.
            unsubscribe()
            for task in (waiter, getter):
                if task is not None and not task.done():
                    task.cancel()

    # ---------------------------------------------------------------- обновление

    async def update(self) -> None:
        """Проверка и установка обновления из GitHub с подтверждением и перезапуском."""
        from core.updater import UpdateError  # noqa: F401  (UserError-наследник, ловится в run)
        from modules.system.update import describe

        self._clear_screen()
        self._show(self._paint("Обновление", BOLD))
        self._show("Проверяю GitHub...")
        info = await self.app.check_update()
        self._show(describe(info))
        if not info.available:
            await self._input("Enter: назад")
            return
        if not await self._confirm("Установить сейчас? Бот перезапустится."):
            return
        self._show("Скачиваю и устанавливаю...")
        result = await self.app.install_update(info)
        self._show(f"✅ Обновлено: {result.old} → {result.new} (файлов: {result.files}).")
        for note in result.notes:
            self._show(f"⚠️ {note}")
        self._show("Перезапускаюсь...")
        await self.app.request_restart()
