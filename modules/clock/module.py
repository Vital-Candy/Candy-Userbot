"""Модуль команды .time: часы в имени аккаунта.

Синтаксис: ``.time`` (меню), ``.time on [номер]``, ``.time off``, ``.time tz [пояс]``.
Из меню стиль выбирают ответом на сообщение с меню (цифрой). Команду вызывает владелец
аккаунта; всю работу с именем делает ``modules.clock.service``.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from core.errors import UserError
from core.filters import outgoing
from core.module import Module
from core.reply import answer
from modules.clock.service import ClockError, ClockService, TelethonBackend
from modules.clock.styles import STYLE_COUNT, STYLES
from utils.logger import logger

USAGE = "Использование: .time | .time on [номер] | .time off | .time tz [пояс]"
MENU_TTL = 300.0  # сколько секунд меню принимает ответ-цифру

DETAILS = f"""\
Показывает время в имени аккаунта: после имени через пробел, например «Имя 12:34». Меняется ровно в начале каждой минуты. Основное имя не портится: если вы сами смените его, часы подстроятся, а при выключении и остановке userbot имя возвращается как было. Если у аккаунта есть фамилия, часы ставятся после неё.

.time — меню: стили часов с примерами. Выберите стиль, ответив на это сообщение номером (если часы уже включены, ответ 0 выключает их). Меню принимает ответ {int(MENU_TTL // 60)} минут.
.time on <номер> — включить часы в этом стиле (от 1 до {STYLE_COUNT}); если уже включены, просто меняет стиль
.time on — включить с прежним стилем (если стиль ещё не выбирали, покажет меню)
.time off — выключить часы и вернуть имя
.time tz — показать часовой пояс
.time tz <пояс> — задать пояс: смещение (+5, -3:30), имя (Asia/Samarkand) или auto (по часам устройства)

Если имя вместе с часами не помещается в лимит Telegram (64 символа), часы не включаются и имя не обрезается.
После остановки userbot часы убираются из имени, а при следующем запуске включаются сами. Если процесс убит принудительно, имя вернётся при следующем запуске.

Права: только владелец аккаунта."""


@dataclass(slots=True)
class PendingMenu:
    """Сообщение с меню, на которое ждём ответ-цифру."""

    chat_id: int
    message_id: int
    expires: float  # по time.monotonic()


class ClockModule(Module):
    """Команда ``.time``: включение, стиль, выключение и часовой пояс часов в имени."""

    name = "clock.time"
    description = "Команда .time: часы в имени аккаунта"
    # Необязательный: без часов userbot работает, сбой запуска только пришлёт уведомление.

    def __init__(self, app) -> None:
        super().__init__(app)
        self.service: ClockService | None = None
        self._menu: PendingMenu | None = None
        self._handler = None  # подписка на ответы, пока открыто меню
        self._timer: asyncio.TimerHandle | None = None

    async def start(self) -> None:
        """Создаёт сервис, регистрирует команду и возобновляет часы, если они были включены."""
        account_id = await self.app.identity.account_id()
        self.service = ClockService(
            TelethonBackend(self.app.client),
            self.app.storage.plugin_data,
            account_id,
            self.app.background,
            notify=self.app.notify_owner,
        )
        self.app.dispatcher.register_command(
            "time",
            self.time_command,
            description="часы в имени (меню стилей)",
            usage=".time [on <номер> | off | tz <пояс>]",
            priority=60,
            details=DETAILS,
        )
        await self.service.start()

    async def stop(self) -> None:
        """Снимает команду, закрывает меню и убирает часы из имени."""
        self.app.dispatcher.unregister_command("time")
        self._close_menu()
        if self.service is not None:
            await self.service.stop()

    # ------------------------------------------------------------- команда

    async def time_command(self, event) -> None:
        """Разбирает ``.time``; ошибки часов отвечает текстом, а не пробрасывает."""
        if self.service is None:
            return
        command = self.app.dispatcher.get_command(event)
        args = list(command.args) if command else []
        action = args[0].lower() if args else ""
        try:
            if not args:
                await self._show_menu(event)
            elif action == "on" and len(args) <= 2:
                await self._on(event, args[1:])
            elif action == "off" and len(args) == 1:
                await answer(event, await self._turn_off())
            elif action == "tz" and len(args) <= 2:
                await self._tz(event, args[1:])
            else:
                await answer(event, USAGE)
        except UserError as exc:
            await answer(event, f"❌ {exc}")

    async def _on(self, event, rest: list[str]) -> None:
        """``.time on [номер]``: включает часы или меняет стиль."""
        service = self.service
        if not rest:
            # Без номера: прежний стиль, а если его ещё не выбирали, показываем меню.
            if not service.style_chosen:
                await self._show_menu(event)
                return
            number = service.style
        elif rest[0].isdigit():
            number = int(rest[0])
        else:
            raise ClockError(f"Номер стиля от 1 до {STYLE_COUNT}.")
        await answer(event, await self._turn_on(number))

    async def _turn_on(self, number: int) -> str:
        """Включает часы (или меняет стиль) и возвращает текст ответа."""
        service = self.service
        changing = service.active
        await service.enable(number)
        head = "Стиль часов изменён" if changing else "Часы включены"
        return f"✅ {head}: стиль {number}, сейчас {service.clock_text()} ({service.timezone_label()}). Выключить: .time off"

    async def _turn_off(self) -> str:
        """Выключает часы и возвращает текст ответа."""
        service = self.service
        if not service.active and not service.state["applied"] and not service.state["enabled"]:
            return "ℹ️ Часы и так выключены."
        await service.disable()
        return "✅ Часы выключены, имя восстановлено."

    async def _tz(self, event, rest: list[str]) -> None:
        """``.time tz [пояс]``: показывает или задаёт часовой пояс."""
        service = self.service
        if rest:
            await service.set_timezone(rest[0])
            head = "✅ Часовой пояс задан"
        else:
            head = "🌍 Часовой пояс"
        await answer(event, f"{head}: {service.timezone_label()}. Сейчас там {service.clock_text(1)}.")

    # ---------------------------------------------------------------- меню

    def menu_text(self) -> str:
        """Текст меню: состояние, стили с живыми примерами и подсказки."""
        service = self.service
        if service.active:
            state = f"Сейчас включены, стиль {service.style}."
            how = "Чтобы изменить стиль, ответьте на это сообщение его номером или отправьте .time on <номер>."
            off = "\n0. Выключить часы"
        else:
            state = "Сейчас выключены."
            how = "Чтобы включить, ответьте на это сообщение номером стиля или отправьте .time on <номер>."
            off = ""
        lines = ["🕒 Часы в имени", state, how, ""]
        for style in STYLES:
            lines.append(f"{style.number}. {service.clock_text(style.number)}")
        text = "\n".join(lines) + off
        return text + f"\n\nЧасовой пояс: {service.timezone_label()} (сменить: .time tz <пояс>)."

    async def _show_menu(self, event) -> None:
        """Показывает меню на месте команды и начинает ждать ответ-цифру."""
        await answer(event, self.menu_text())
        chat_id = getattr(event, "chat_id", None)
        message_id = getattr(event, "id", None)
        if chat_id is None or message_id is None:
            return
        self._close_menu()
        self._menu = PendingMenu(int(chat_id), int(message_id), time.monotonic() + MENU_TTL)
        # Обработчик живёт, только пока открыто меню: так на каждое исходящее сообщение не тратится время.
        self._handler = self.app.dispatcher.register(
            "new_message", self._on_reply, filters=(outgoing,), name="clock.menu_reply"
        )
        self._timer = asyncio.get_running_loop().call_later(MENU_TTL, self._close_menu)

    def _close_menu(self) -> None:
        """Закрывает меню: снимает обработчик и таймер."""
        self._menu = None
        if self._handler is not None:
            self.app.dispatcher.unregister(self._handler)
            self._handler = None
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    async def _on_reply(self, event) -> None:
        """Ответ на меню: цифра выбирает стиль, 0 выключает часы (если они включены)."""
        menu, service = self._menu, self.service
        if menu is None or service is None:
            return
        if getattr(event, "chat_id", None) != menu.chat_id:
            return
        if getattr(event, "reply_to_msg_id", None) != menu.message_id:
            return
        text = (getattr(event, "raw_text", "") or "").strip().lower()
        try:
            if text in {"0", "off", "выкл"} and service.active:
                reply = await self._turn_off()
            elif text.isdigit() and 1 <= int(text) <= STYLE_COUNT:
                reply = await self._turn_on(int(text))
            else:
                return  # не наша цифра: меню остаётся открытым
        except UserError as exc:
            reply = f"❌ {exc}"
        except Exception:
            logger.exception("Ошибка выбора стиля часов.")
            reply = "❌ Не удалось изменить часы. Подробности в логе."
        self._close_menu()
        await answer(event, reply)
