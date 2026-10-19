"""Сервис часов в имени: хранит состояние, обновляет имя ровно в начале минуты и возвращает его.

Главные гарантии:

* исходное имя («основа») сохраняется в базе ДО первого изменения, поэтому его можно вернуть
  даже после аварийного завершения процесса;
* имя никогда не обрезается: если часы не помещаются в лимит Telegram, они не включаются;
* если вы сами сменили имя, новая основа принимается без перезаписи;
* при остановке userbot часы убираются, а при следующем запуске включаются снова.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from core.errors import UserError
from modules.clock.styles import (
    AUTO,
    STYLE_COUNT,
    describe_timezone,
    is_ours,
    max_length,
    moment,
    parse_timezone,
    render_time,
    strip_clock,
    utf16_len,
)
from utils.logger import logger

PLUGIN = "clock"  # пространство в plugin_data, где лежит состояние
STATE_KEY = "state"
TASK_NAME = "clock.tick"  # имя фоновой задачи (видна в .status all)
NAME_LIMIT = 64  # лимит Telegram на имя и фамилию
CHECK_LEAD = 3.0  # за сколько секунд до смены минуты проверяем, не менял ли вы имя вручную
INITIAL_LEAD = 0.1  # начальная поправка на сетевую задержку, секунды
MAX_LEAD = 0.5  # потолок поправки на задержку
RESTORE_TIMEOUT = 10.0  # сколько ждём Telegram при возврате имени
MAX_FLOOD_WAIT = 3600.0  # дольше этого FloodWait не ждём

DEFAULT_STATE: dict[str, Any] = {
    "enabled": False,  # часы включены (после перезапуска запустятся сами)
    "style": 1,  # номер стиля
    "chosen": False,  # стиль выбирали явно (иначе `.time on` без номера покажет меню)
    "tz": AUTO,  # часовой пояс: auto, смещение или имя
    "field": "first_name",  # какое поле имени дополняем: first_name или last_name
    "base": "",  # исходное значение этого поля без часов
    "applied": False,  # часы сейчас могут быть в имени (нужно вернуть при остановке)
}


class ClockError(UserError):
    """Ошибка часов с текстом для пользователя."""


class NameBackend(Protocol):
    """Как сервис читает и меняет имя; в тестах заменяется заглушкой."""

    async def get_names(self) -> tuple[str, str]:
        """Текущие (имя, фамилия) аккаунта."""

    async def set_field(self, field: str, value: str) -> None:
        """Меняет одно поле профиля (``first_name`` или ``last_name``), второе не трогает."""


class TelethonBackend:
    """Реализация ``NameBackend`` поверх Telethon-клиента."""

    def __init__(self, client: Any) -> None:
        self.client = client

    async def get_names(self) -> tuple[str, str]:
        """Читает имя и фамилию из Telegram (каждый раз свежий запрос, не кэш)."""
        me = await self.client.get_me()
        if me is None:
            raise ClockError("Telegram не вернул данные аккаунта")
        return me.first_name or "", me.last_name or ""

    async def set_field(self, field: str, value: str) -> None:
        """Отправляет ``account.updateProfile`` только с одним полем."""
        from telethon.tl.functions.account import UpdateProfileRequest

        await self.client(UpdateProfileRequest(**{field: value}))


def _flood_seconds(exc: BaseException) -> float | None:
    """Секунды ожидания, если это FloodWait от Telegram; иначе ``None``."""
    seconds = getattr(exc, "seconds", None)
    if "FloodWait" in type(exc).__name__ and isinstance(seconds, (int, float)):
        return float(seconds)
    return None


def _not_modified(exc: BaseException) -> bool:
    """True, если Telegram сообщил, что имя уже такое же (это не ошибка)."""
    return type(exc).__name__.endswith("NotModifiedError")


class ClockService:
    """Включает, выключает и обновляет часы в имени одного аккаунта."""

    def __init__(
        self,
        backend: NameBackend,
        store: Any,
        account_id: int,
        background: Any,
        *,
        notify: Callable[[str], Awaitable[Any]] | None = None,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        """``store``: PluginDataStore; ``background``: BackgroundManager; ``now``/``sleep``: для тестов."""
        self.backend = backend
        self.store = store
        self.account_id = account_id
        self.background = background
        self._notify = notify
        self._now = now
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._running = False  # фоновая задача обновления запущена
        self._broken = False  # часы остановлены из-за слишком длинного имени
        self._last_name: str | None = None  # последнее имя, записанное нами
        self._last_target = 0  # номер минуты (epoch // 60), которую показали последней
        self._lead = INITIAL_LEAD  # на сколько секунд раньше границы минуты отправляем запрос
        self._side_tasks: set[asyncio.Task[None]] = set()
        saved = store.get(account_id=account_id, plugin=PLUGIN, key=STATE_KEY, default=None) or {}
        self.state: dict[str, Any] = {**DEFAULT_STATE, **{k: v for k, v in saved.items() if k in DEFAULT_STATE}}
        if not 1 <= int(self.state["style"]) <= STYLE_COUNT:
            self.state["style"] = 1

    # ------------------------------------------------------------ состояние

    @property
    def active(self) -> bool:
        """Часы сейчас работают (идёт обновление имени)."""
        return self._running

    @property
    def style_chosen(self) -> bool:
        """Выбирал ли пользователь стиль хотя бы раз."""
        return bool(self.state["chosen"])

    @property
    def style(self) -> int:
        """Номер выбранного стиля."""
        return int(self.state["style"])

    def _save(self) -> None:
        """Записывает состояние в базу."""
        self.store.set(account_id=self.account_id, plugin=PLUGIN, key=STATE_KEY, value=self.state)

    def _tz(self):
        """Часовой пояс из состояния; повреждённая запись заменяется на ``auto``."""
        try:
            return parse_timezone(str(self.state["tz"]))[1]
        except ValueError:
            return None

    def timezone_label(self) -> str:
        """Подпись текущего часового пояса, например ``UTC+5``."""
        return describe_timezone(str(self.state["tz"]), self._tz(), self._now())

    def clock_text(self, style: int | None = None, epoch: float | None = None) -> str:
        """Запись часов в выбранном (или заданном) стиле на момент ``epoch`` (по умолчанию сейчас)."""
        when = moment(self._now() if epoch is None else epoch, self._tz())
        return render_time(style or self.style, when.hour, when.minute)

    # ---------------------------------------------------------------- запуск

    async def start(self) -> None:
        """Вызывается при запуске модуля: возобновляет включённые часы или дочищает имя после сбоя."""
        async with self._lock:
            try:
                if self.state["enabled"]:
                    await self._enable(self.style)
                elif self.state["applied"]:
                    await self._restore()
            except Exception as exc:
                # Запуск userbot из-за часов падать не должен: сообщаем и работаем дальше.
                logger.warning("Часы не запустились: %s", exc)
                await self._tell(f"⚠️ Часы в имени не запустились: {exc}")

    async def stop(self) -> None:
        """Вызывается при остановке модуля: убирает часы из имени, но оставляет их включёнными в настройках."""
        async with self._lock:
            await self._stop_task()
            try:
                await self._restore()
            except ClockError as exc:
                logger.warning("%s", exc)
        for task in tuple(self._side_tasks):
            task.cancel()

    async def enable(self, style: int) -> None:
        """Включает часы в стиле ``style``; если они уже идут, только меняет стиль."""
        async with self._lock:
            await self._enable(style)

    async def disable(self) -> None:
        """Выключает часы и возвращает имя. ``ClockError``, если вернуть имя сейчас не вышло."""
        async with self._lock:
            await self._stop_task()
            self.state["enabled"] = False
            self._save()
            await self._restore()

    async def set_timezone(self, spec: str) -> str:
        """Меняет часовой пояс (``ValueError`` из разбора превращается в ``ClockError``). Возвращает подпись."""
        try:
            normalized, _ = parse_timezone(spec)
        except ValueError as exc:
            raise ClockError(str(exc)) from None
        async with self._lock:
            self.state["tz"] = normalized
            self._save()
            if self._running:
                await self._apply(int(self._now() // 60))
        return self.timezone_label()

    # ------------------------------------------------------------ внутренние

    async def _enable(self, style: int) -> None:
        """Тело ``enable``; вызывается под блокировкой."""
        if not 1 <= style <= STYLE_COUNT:
            raise ClockError(f"Номер стиля от 1 до {STYLE_COUNT}.")
        if self._running:
            self.state.update(style=style, chosen=True)
            self._save()
            await self._apply(int(self._now() // 60))
            return

        first, last = await self.backend.get_names()
        field, base = self._adopt(first, last)
        if utf16_len(base) + 1 + max_length(style) > NAME_LIMIT:
            room = NAME_LIMIT - 1 - max_length(style)
            raise ClockError(
                f"Имя «{base}» слишком длинное для этого стиля: в Telegram не больше {NAME_LIMIT} символов. "
                f"Сократите имя до {room} символов или выберите стиль покороче."
            )
        # Сначала запоминаем исходное имя, и только потом меняем его: так оно не потеряется при сбое.
        self.state.update(enabled=True, style=style, chosen=True, field=field, base=base, applied=True)
        self._save()
        self._broken = False
        self._last_name = None
        try:
            await self._apply(int(self._now() // 60))
        except Exception as exc:
            self.state.update(enabled=False, applied=False)
            self._save()
            raise ClockError(f"Не удалось изменить имя: {self._describe(exc)}") from exc
        await self._start_task()

    def _adopt(self, first: str, last: str) -> tuple[str, str]:
        """Выбирает поле и исходное имя. Если прошлый запуск оборвался, берёт сохранённое, иначе
        очищает текущее от наших часов. Часы идут после фамилии, а без фамилии после имени."""
        field = self.state["field"]
        saved = self.state["base"]
        current = last if field == "last_name" else first
        if self.state["applied"] and saved and is_ours(current, saved):
            return field, saved
        stripped_last = strip_clock(last)
        if stripped_last:
            return "last_name", stripped_last
        return "first_name", strip_clock(first)

    @staticmethod
    def _describe(exc: BaseException) -> str:
        """Короткий текст ошибки для пользователя."""
        wait = _flood_seconds(exc)
        if wait is not None:
            return f"Telegram просит подождать {int(wait)} с (слишком частые изменения имени)"
        return str(exc) or type(exc).__name__

    async def _apply(self, target: int) -> None:
        """Записывает в имя «основа + часы» для минуты ``target`` (номер минуты с начала эпохи)."""
        field, base = self.state["field"], self.state["base"]
        clock = self.clock_text(epoch=target * 60)
        name = f"{base} {clock}"
        if utf16_len(name) > NAME_LIMIT:
            raise ClockError(f"Имя «{base}» с часами длиннее {NAME_LIMIT} символов.")
        if name == self._last_name:
            return
        started = self._now()
        try:
            await self.backend.set_field(field, name)
        except Exception as exc:
            if not _not_modified(exc):
                raise
        # Поправка на задержку сети: запрос уходит чуть раньше границы минуты, чтобы имя сменилось вовремя.
        half = min(MAX_LEAD, max(0.0, (self._now() - started) / 2))
        self._lead = 0.5 * self._lead + 0.5 * half
        self._last_name = name
        self._last_target = max(self._last_target, target)

    async def _sync_external(self) -> None:
        """Проверяет, не меняли ли вы имя вручную. Если да, принимает новое имя как основу."""
        first, last = await self.backend.get_names()
        field, base = self.state["field"], self.state["base"]
        current = last if field == "last_name" else first
        if current == self._last_name or is_ours(current, base):
            return
        if field == "last_name" and not current:
            # Фамилию удалили: часы переезжают в имя.
            field, new_base = "first_name", strip_clock(first)
        else:
            new_base = strip_clock(current) or current
        logger.info("Имя изменено вручную, новая основа для часов: %r.", new_base)
        self.state.update(field=field, base=new_base)
        self._save()
        self._last_name = None

    async def _restore(self) -> None:
        """Возвращает исходное имя (если часы были применены). ``ClockError``, если Telegram недоступен."""
        if not self.state["applied"]:
            return
        field, base = self.state["field"], self.state["base"]
        try:
            first, last = await asyncio.wait_for(self.backend.get_names(), RESTORE_TIMEOUT)
            current = last if field == "last_name" else first
            if current != base and is_ours(current, base):
                await asyncio.wait_for(self.backend.set_field(field, base), RESTORE_TIMEOUT)
            elif current != base:
                logger.info("Имя изменено вручную, часы не трогаю.")
        except Exception as exc:
            raise ClockError(
                f"Не удалось вернуть имя ({self._describe(exc)}). Это будет сделано при следующем запуске."
            ) from exc
        self.state["applied"] = False
        self._save()
        self._last_name = None

    async def _start_task(self) -> None:
        """Регистрирует и запускает фоновую задачу обновления."""
        if self.background.get(TASK_NAME) is None:
            # Пауза между оборотами 1 с: после сбоя повтор не бьёт по Telegram с частотой цикла.
            self.background.register(TASK_NAME, self._tick, interval=1.0)
        await self.background.start(TASK_NAME)
        self._running = True

    async def _stop_task(self) -> None:
        """Останавливает и убирает фоновую задачу обновления."""
        self._running = False
        if self.background.get(TASK_NAME) is not None:
            await self.background.stop(TASK_NAME)
            self.background.remove(TASK_NAME)

    async def _tick(self) -> None:
        """Один оборот: дожидается начала следующей минуты и меняет имя на новое время.

        Сначала (за ``CHECK_LEAD`` секунд до границы) проверяем ручные правки имени, потом ждём
        границу минус сетевая задержка и отправляем запрос. Так смена происходит почти в тот же миг.
        """
        if self._broken:
            await self._sleep(1.0)
            return
        now = self._now()
        current = int(now // 60)
        # Если текущую минуту ещё не показали (границу пропустили из-за сбоя), показываем её сразу.
        # Иначе ждём следующую; запрос уходит чуть раньше границы, поэтому «+1» считаем от последней
        # показанной минуты, а не от часов: так одна минута не применяется дважды.
        target = current if current > self._last_target else self._last_target + 1
        boundary = target * 60.0
        check_at = boundary - CHECK_LEAD
        if now < check_at:
            await self._sleep(check_at - now)
            async with self._lock:
                await self._sync_external()
            now = self._now()
        fire_at = boundary - self._lead
        if now < fire_at:
            await self._sleep(fire_at - now)
        try:
            async with self._lock:
                if self._running:
                    await self._apply(target)
        except ClockError as exc:
            self._broken = True
            logger.warning("Часы остановлены: %s", exc)
            self._spawn(self._give_up(str(exc)))
        except Exception as exc:
            wait = _flood_seconds(exc)
            if wait is None:
                raise
            logger.warning("FloodWait %g с при смене имени, жду.", wait)
            await self._sleep(min(wait, MAX_FLOOD_WAIT) + 1.0)

    def _spawn(self, coroutine: Awaitable[None]) -> None:
        """Запускает побочную задачу и хранит ссылку, чтобы её не собрал сборщик мусора."""
        task = asyncio.ensure_future(coroutine)
        self._side_tasks.add(task)
        task.add_done_callback(self._side_tasks.discard)

    async def _give_up(self, reason: str) -> None:
        """Выключает часы после неустранимой ошибки (например, имя стало слишком длинным) и сообщает владельцу."""
        try:
            await self.disable()
        except ClockError as exc:
            logger.warning("%s", exc)
        await self._tell(f"⚠️ Часы в имени выключены: {reason}")

    async def _tell(self, text: str) -> None:
        """Отправляет уведомление владельцу, если задан канал уведомлений; ошибки только в лог."""
        if self._notify is None:
            return
        try:
            await self._notify(text)
        except Exception:
            logger.exception("Не удалось отправить уведомление о часах.")
