"""Тесты часов в имени: стили, сервис (время, имя, восстановление) и команда ``.time``."""
from __future__ import annotations

import asyncio
import sys
import types
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.background import BackgroundManager
from core.dispatcher import Dispatcher
from modules.clock import styles
from modules.clock.module import ClockModule
from modules.clock.service import (
    NAME_LIMIT,
    TASK_NAME,
    ClockError,
    ClockService,
    TelethonBackend,
)

# 2026-10-19 12:34:10 UTC.
START = datetime(2026, 10, 19, 12, 34, 10, tzinfo=timezone.utc).timestamp()


class FloodWaitError(Exception):
    """Похож на ошибку Telethon: имя класса и поле ``seconds``."""

    def __init__(self, seconds: int) -> None:
        super().__init__(f"wait {seconds}")
        self.seconds = seconds


class FieldNotModifiedError(Exception):
    """Telegram: имя не изменилось (не должно считаться ошибкой)."""


class FakeTime:
    """Управляемые часы: ``sleep`` просто двигает время."""

    def __init__(self, start: float = START) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += max(0.0, seconds)
        await asyncio.sleep(0)


class FakeBackend:
    """Имя и фамилия в памяти; запоминает все изменения вместе со временем."""

    def __init__(self, clock: FakeTime, first: str = "Candy", last: str = "") -> None:
        self.clock = clock
        self.first, self.last = first, last
        self.sets: list[tuple[float, str, str]] = []
        self.fail: BaseException | None = None
        self.fail_get: BaseException | None = None

    async def get_names(self) -> tuple[str, str]:
        if self.fail_get:
            raise self.fail_get
        return self.first, self.last

    async def set_field(self, field: str, value: str) -> None:
        if self.fail:
            raise self.fail
        self.sets.append((self.clock.now(), field, value))
        setattr(self, "first" if field == "first_name" else "last", value)


class FakeStore:
    """Замена PluginDataStore: словарь по (аккаунт, плагин, ключ)."""

    def __init__(self) -> None:
        self.data: dict[tuple, object] = {}

    def get(self, *, account_id, plugin, key, default=None):
        value = self.data.get((account_id, plugin, key), default)
        return None if value is None else dict(value)

    def set(self, *, account_id, plugin, key, value):
        self.data[(account_id, plugin, key)] = dict(value)


class FakeBackground:
    """Фоновый менеджер без реального запуска: тесты вызывают ``_tick`` сами."""

    def __init__(self) -> None:
        self.tasks: dict[str, object] = {}
        self.started: list[str] = []

    def get(self, name):
        return self.tasks.get(name)

    def register(self, name, callback, *, interval):
        self.tasks[name] = (callback, interval)

    async def start(self, name):
        self.started.append(name)

    async def stop(self, name):
        pass

    def remove(self, name):
        self.tasks.pop(name, None)


def make_service(first="Candy", last="", store=None, notify=None, tz="+0"):
    clock = FakeTime()
    backend = FakeBackend(clock, first, last)
    store = store if store is not None else FakeStore()
    background = FakeBackground()
    service = ClockService(
        backend, store, 7, background, notify=notify, now=clock.now, sleep=clock.sleep
    )
    service.state["tz"] = tz
    return service, backend, clock, store, background


# ---------------------------------------------------------------------- стили


class StyleTests(unittest.TestCase):
    def test_there_are_many_styles_with_unique_numbers(self):
        self.assertGreaterEqual(styles.STYLE_COUNT, 20)
        self.assertEqual([s.number for s in styles.STYLES], list(range(1, styles.STYLE_COUNT + 1)))
        self.assertEqual(len({s.title for s in styles.STYLES}), styles.STYLE_COUNT)

    def test_examples(self):
        self.assertEqual(styles.render_time(1, 12, 34), "12:34")
        self.assertEqual(styles.render_time(5, 0, 5), "[00:05]")
        self.assertEqual(styles.render_time(11, 0, 5), "12:05 AM")
        self.assertEqual(styles.render_time(11, 13, 7), "1:07 PM")
        self.assertEqual(styles.render_time(13, 12, 34), "𝟏𝟐:𝟑𝟒")
        self.assertEqual(styles.render_time(17, 9, 8), "⓪⑨:⓪⑧")
        self.assertEqual(styles.render_time(19, 12, 34), "¹²:³⁴")

    def test_every_style_shows_hour_and_minute_for_every_minute(self):
        for style in styles.STYLES:
            seen = {style.render(h, m) for h in range(24) for m in range(60)}
            if style.number != 11:  # в 12-часовом формате 0:xx и 12:xx совпадают, отличается только AM/PM
                self.assertGreaterEqual(len(seen), 1440 // 2, style.title)
            self.assertTrue(all(text.strip() == text and text for text in seen))

    def test_emoji_clock_matches_nearest_half_hour(self):
        self.assertTrue(styles.render_time(2, 0, 0).startswith("🕛"))
        self.assertTrue(styles.render_time(2, 3, 10).startswith("🕒"))
        self.assertTrue(styles.render_time(2, 3, 20).startswith("🕞"))  # 3:30
        self.assertTrue(styles.render_time(2, 23, 50).startswith("🕛"))

    def test_lengths_fit_the_name_limit_for_reasonable_names(self):
        for style in styles.STYLES:
            self.assertLessEqual(styles.max_length(style.number), 12)

    def test_get_style_rejects_bad_numbers(self):
        for bad in (0, styles.STYLE_COUNT + 1, -1):
            with self.assertRaises(ValueError):
                styles.get_style(bad)

    def test_strip_clock_and_is_ours(self):
        self.assertEqual(styles.strip_clock("Candy 12:34"), "Candy")
        self.assertEqual(styles.strip_clock("Candy | 12:34 |"), "Candy")
        self.assertEqual(styles.strip_clock("Candy"), "Candy")
        self.assertEqual(styles.strip_clock("Candy Cat"), "Candy Cat")
        self.assertEqual(styles.strip_clock("12:34"), "12:34")  # одни часы без имени не трогаем
        self.assertTrue(styles.is_ours("Candy", "Candy"))
        self.assertTrue(styles.is_ours("Candy ⏰ 08:15", "Candy"))
        self.assertFalse(styles.is_ours("Candy Cat", "Candy"))
        self.assertFalse(styles.is_ours("Neo 12:34", "Candy"))

    def test_timezone_parsing(self):
        self.assertEqual(styles.parse_timezone("+5")[0], "+05:00")
        self.assertEqual(styles.parse_timezone("UTC-3:30")[0], "-03:30")
        self.assertEqual(styles.parse_timezone("auto"), ("auto", None))
        self.assertEqual(styles.parse_timezone("")[0], "auto")
        self.assertEqual(styles.parse_timezone("Asia/Samarkand")[0], "Asia/Samarkand")
        for bad in ("+15", "+5:99", "Mars/Olympus", "../etc", "abc"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                styles.parse_timezone(bad)

    def test_timezone_labels(self):
        self.assertEqual(styles.describe_timezone(*styles.parse_timezone("+5:30"), START), "UTC+5:30")
        self.assertEqual(styles.describe_timezone(*styles.parse_timezone("-3"), START), "UTC-3")
        self.assertIn("устройства", styles.describe_timezone("auto", None, START))


# ---------------------------------------------------------------------- сервис


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_enable_appends_clock_after_name_with_space(self):
        service, backend, _, store, background = make_service()
        await service.enable(1)
        self.assertEqual(backend.first, "Candy 12:34")
        self.assertEqual(backend.sets[0][1], "first_name")
        saved = store.get(account_id=7, plugin="clock", key="state")
        self.assertEqual((saved["enabled"], saved["base"], saved["applied"], saved["style"]), (True, "Candy", True, 1))
        self.assertTrue(service.active)
        self.assertEqual(background.started, [TASK_NAME])

    async def test_base_is_saved_before_the_name_is_changed(self):
        service, backend, _, store, _ = make_service()
        seen = {}

        original = backend.set_field

        async def spy(field, value):
            seen.update(store.get(account_id=7, plugin="clock", key="state"))
            await original(field, value)

        backend.set_field = spy
        await service.enable(1)
        self.assertEqual((seen["base"], seen["applied"]), ("Candy", True))

    async def test_minute_change_is_sent_just_before_the_boundary(self):
        service, backend, clock, _, _ = make_service()
        await service.enable(1)
        await service._tick()
        when, _, name = backend.sets[-1]
        self.assertEqual(name, "Candy 12:35")
        boundary = START - 10 + 60  # 12:35:00
        self.assertLess(boundary - when, 0.5)  # раньше границы не больше чем на поправку на задержку
        self.assertGreaterEqual(when, boundary - 0.5)
        self.assertLessEqual(when, boundary)

    async def test_every_minute_is_applied_exactly_once(self):
        service, backend, _, _, _ = make_service()
        await service.enable(1)
        for _ in range(4):
            await service._tick()
        self.assertEqual([name for _, _, name in backend.sets], [f"Candy 12:{m}" for m in (34, 35, 36, 37, 38)])

    async def test_missed_boundary_is_caught_up_immediately(self):
        service, backend, clock, _, _ = make_service()
        await service.enable(1)
        clock.t += 130  # потеряли связь на две минуты
        await service._tick()
        self.assertEqual(backend.first, "Candy 12:36")
        self.assertLess(clock.t - (START + 130), 1.0)  # применили сразу, не ждали границу

    async def test_changing_style_while_running_only_changes_style(self):
        service, backend, _, _, background = make_service()
        await service.enable(1)
        await service.enable(5)
        self.assertEqual(backend.first, "Candy [12:34]")
        self.assertEqual(background.started, [TASK_NAME])  # вторая задача не запускалась
        await service._tick()
        self.assertEqual(backend.first, "Candy [12:35]")

    async def test_disable_restores_name(self):
        service, backend, _, store, _ = make_service()
        await service.enable(3)
        await service.disable()
        self.assertEqual(backend.first, "Candy")
        saved = store.get(account_id=7, plugin="clock", key="state")
        self.assertEqual((saved["enabled"], saved["applied"]), (False, False))
        self.assertFalse(service.active)

    async def test_stop_restores_name_but_keeps_clock_enabled_for_next_start(self):
        service, backend, clock, store, _ = make_service()
        await service.enable(2)
        await service.stop()
        self.assertEqual(backend.first, "Candy")
        saved = store.get(account_id=7, plugin="clock", key="state")
        self.assertEqual((saved["enabled"], saved["applied"], saved["style"]), (True, False, 2))
        # Новый запуск userbot: часы включаются сами и в том же стиле.
        again = ClockService(backend, store, 7, FakeBackground(), now=clock.now, sleep=clock.sleep)
        again.state["tz"] = "+0"
        await again.start()
        self.assertTrue(again.active)
        self.assertTrue(backend.first.startswith("Candy ") and backend.first != "Candy")

    async def test_crash_recovery_keeps_original_name(self):
        service, backend, clock, store, _ = make_service()
        await service.enable(1)
        backend.first = "Candy 12:33"  # процесс убили: в имени остались часы
        again = ClockService(backend, store, 7, FakeBackground(), now=clock.now, sleep=clock.sleep)
        again.state["tz"] = "+0"
        await again.start()
        self.assertEqual(again.state["base"], "Candy")
        self.assertEqual(backend.first, "Candy 12:34")
        await again.disable()
        self.assertEqual(backend.first, "Candy")

    async def test_leftover_clock_is_cleaned_even_if_state_was_lost(self):
        service, backend, _, _, _ = make_service(first="Candy 12:33")
        await service.enable(1)
        self.assertEqual(service.state["base"], "Candy")
        self.assertEqual(backend.first, "Candy 12:34")

    async def test_disabled_state_with_applied_clock_is_cleaned_on_start(self):
        store = FakeStore()
        store.set(account_id=7, plugin="clock", key="state",
                  value={"enabled": False, "applied": True, "base": "Candy", "field": "first_name", "style": 1})
        service, backend, _, _, _ = make_service(first="Candy 12:33", store=store)
        await service.start()
        self.assertEqual(backend.first, "Candy")
        self.assertFalse(service.state["applied"])

    async def test_last_name_gets_the_clock_and_first_name_is_untouched(self):
        service, backend, _, _, _ = make_service(first="Candy", last="Smith")
        await service.enable(1)
        self.assertEqual((backend.first, backend.last), ("Candy", "Smith 12:34"))
        await service.disable()
        self.assertEqual((backend.first, backend.last), ("Candy", "Smith"))

    async def test_too_long_name_is_refused_and_not_truncated(self):
        long_name = "Н" * (NAME_LIMIT - 3)
        service, backend, _, store, _ = make_service(first=long_name)
        with self.assertRaises(ClockError) as ctx:
            await service.enable(1)
        self.assertIn("слишком длинное", str(ctx.exception))
        self.assertEqual(backend.sets, [])
        self.assertEqual(backend.first, long_name)
        self.assertFalse(service.state["enabled"])
        self.assertFalse(service.active)

    async def test_longer_style_needs_shorter_name(self):
        name = "Н" * (NAME_LIMIT - 1 - styles.max_length(1))  # впритык для стиля 1
        service, backend, _, _, _ = make_service(first=name)
        await service.enable(1)
        self.assertLessEqual(styles.utf16_len(backend.first), NAME_LIMIT)
        await service.disable()
        with self.assertRaises(ClockError):
            await service.enable(21)  # этот стиль длиннее

    async def test_manual_rename_is_adopted_as_new_base(self):
        service, backend, _, _, _ = make_service()
        await service.enable(1)
        backend.first = "Neo"  # пользователь сменил имя руками
        await service._tick()
        self.assertEqual(service.state["base"], "Neo")
        self.assertEqual(backend.first, "Neo 12:35")
        await service.disable()
        self.assertEqual(backend.first, "Neo")

    async def test_manual_rename_with_old_clock_text_is_cleaned(self):
        service, backend, _, _, _ = make_service()
        await service.enable(1)
        backend.first = "Neo | 08:00 |"
        await service._tick()
        self.assertEqual(service.state["base"], "Neo")

    async def test_removing_last_name_moves_clock_to_first_name(self):
        service, backend, _, _, _ = make_service(first="Candy", last="Smith")
        await service.enable(1)
        backend.last = ""
        await service._tick()
        self.assertEqual(service.state["field"], "first_name")
        self.assertEqual(backend.first, "Candy 12:35")

    async def test_stop_does_not_overwrite_a_manual_rename(self):
        service, backend, _, _, _ = make_service()
        await service.enable(1)
        backend.first = "Neo"
        await service.stop()
        self.assertEqual(backend.first, "Neo")
        self.assertFalse(service.state["applied"])

    async def test_flood_wait_is_waited_out_without_error(self):
        service, backend, clock, _, _ = make_service()
        await service.enable(1)
        backend.fail = FloodWaitError(30)
        before = clock.t
        await service._tick()  # не бросает
        self.assertGreaterEqual(clock.t - before, 60 + 30 - 10)  # дошли до границы и ещё подождали

    async def test_other_errors_propagate_so_background_counts_failures(self):
        service, backend, _, _, _ = make_service()
        await service.enable(1)
        backend.fail = ConnectionError("нет сети")
        with self.assertRaises(ConnectionError):
            await service._tick()

    async def test_not_modified_is_not_an_error(self):
        service, backend, _, _, _ = make_service()
        await service.enable(1)
        backend.fail = FieldNotModifiedError()
        await service._tick()  # не бросает

    async def test_failed_enable_leaves_no_traces(self):
        service, backend, _, store, background = make_service()
        backend.fail = ConnectionError("нет сети")
        with self.assertRaises(ClockError):
            await service.enable(1)
        saved = store.get(account_id=7, plugin="clock", key="state")
        self.assertEqual((saved["enabled"], saved["applied"]), (False, False))
        self.assertFalse(service.active)
        self.assertEqual(background.started, [])

    async def test_failed_restore_keeps_applied_flag_for_next_start(self):
        service, backend, _, store, _ = make_service()
        await service.enable(1)
        backend.fail_get = ConnectionError("нет сети")
        with self.assertRaises(ClockError) as ctx:
            await service.disable()
        self.assertIn("при следующем запуске", str(ctx.exception))
        self.assertTrue(store.get(account_id=7, plugin="clock", key="state")["applied"])
        backend.fail_get = None
        again = ClockService(backend, store, 7, FakeBackground(), now=service._now, sleep=service._sleep)
        await again.start()
        self.assertEqual(backend.first, "Candy")

    async def test_name_becoming_too_long_switches_clock_off_and_notifies(self):
        notify = AsyncMock()
        service, backend, _, store, _ = make_service(notify=notify)
        await service.enable(1)
        backend.first = "Н" * NAME_LIMIT  # теперь часы не поместятся
        await service._tick()
        for _ in range(5):
            await asyncio.sleep(0)
        await asyncio.gather(*list(service._side_tasks))
        self.assertFalse(service.state["enabled"])
        self.assertFalse(service.active)
        self.assertEqual(backend.first, "Н" * NAME_LIMIT)  # имя не обрезано и не испорчено
        self.assertIn("выключены", notify.await_args.args[0])

    async def test_start_failure_does_not_raise_and_notifies(self):
        notify = AsyncMock()
        store = FakeStore()
        store.set(account_id=7, plugin="clock", key="state", value={"enabled": True, "style": 1})
        service, backend, _, _, _ = make_service(store=store, notify=notify)
        backend.fail_get = ConnectionError("нет сети")
        await service.start()
        self.assertFalse(service.active)
        self.assertIn("не запустились", notify.await_args.args[0])

    async def test_timezone_changes_shown_time_and_validates(self):
        service, backend, _, _, _ = make_service()
        await service.enable(1)
        self.assertEqual(await service.set_timezone("+5"), "UTC+5")
        self.assertEqual(backend.first, "Candy 17:34")
        self.assertEqual(await service.set_timezone("-3:30"), "UTC-3:30")
        self.assertEqual(backend.first, "Candy 09:04")
        with self.assertRaises(ClockError):
            await service.set_timezone("nowhere")
        self.assertEqual(service.state["tz"], "-03:30")

    async def test_invalid_style_number(self):
        service, _, _, _, _ = make_service()
        for bad in (0, styles.STYLE_COUNT + 1):
            with self.assertRaises(ClockError):
                await service.enable(bad)

    async def test_corrupted_saved_state_falls_back_to_defaults(self):
        store = FakeStore()
        store.set(account_id=7, plugin="clock", key="state", value={"style": 999, "junk": 1})
        service, _, _, _, _ = make_service(store=store)
        self.assertEqual(service.style, 1)
        self.assertNotIn("junk", service.state)

    async def test_real_background_manager_runs_and_stops_the_task(self):
        clock = FakeTime()
        backend = FakeBackend(clock)
        background = BackgroundManager()
        service = ClockService(backend, FakeStore(), 7, background, now=clock.now, sleep=clock.sleep)
        service.state["tz"] = "+0"
        await service.enable(1)
        self.assertEqual(background.get(TASK_NAME).status, "RUNNING")
        for _ in range(5):
            await asyncio.sleep(0)
        await service.disable()
        self.assertIsNone(background.get(TASK_NAME))
        self.assertEqual(backend.first, "Candy")


class TelethonBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_names_reads_fresh_values(self):
        client = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(first_name="A", last_name=None)))
        self.assertEqual(await TelethonBackend(client).get_names(), ("A", ""))
        client.get_me.return_value = None
        with self.assertRaises(ClockError):
            await TelethonBackend(client).get_names()

    async def test_set_field_sends_only_one_field(self):
        sent = []

        class UpdateProfileRequest:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        module = types.ModuleType("telethon.tl.functions.account")
        module.UpdateProfileRequest = UpdateProfileRequest

        async def call(request):
            sent.append(request.kwargs)

        with patch.dict(sys.modules, {"telethon.tl.functions.account": module}):
            await TelethonBackend(call).set_field("last_name", "X 12:34")
        self.assertEqual(sent, [{"last_name": "X 12:34"}])


# ---------------------------------------------------------------------- команда


class ModuleFixture:
    """Модуль часов на настоящем Dispatcher с заглушками Telegram."""

    def __init__(self, first="Candy", last=""):
        self.clock = FakeTime()
        self.backend = FakeBackend(self.clock, first, last)
        self.store = FakeStore()
        self.notify = AsyncMock()
        self.app = SimpleNamespace(
            dispatcher=Dispatcher(),
            identity=SimpleNamespace(account_id=AsyncMock(return_value=7)),
            client=object(),
            storage=SimpleNamespace(plugin_data=self.store),
            background=FakeBackground(),
            notify_owner=self.notify,
        )
        self.module = ClockModule(self.app)
        self.replies: list[str] = []

    async def start(self):
        with patch("modules.clock.module.TelethonBackend", lambda client: self.backend), patch(
            "modules.clock.module.ClockService.__init__", self._patched_init(), create=False
        ):
            await self.module.start()

    def _patched_init(self):
        original = ClockService.__init__
        clock = self.clock

        def init(service, backend, store, account_id, background, *, notify=None, now=None, sleep=None):
            original(service, backend, store, account_id, background, notify=notify, now=clock.now, sleep=clock.sleep)
            service.state["tz"] = "+0"

        return init

    async def say(self, text, *, message_id=100, chat_id=5):
        sent: list[str] = []

        async def edit(reply):
            sent.append(reply)

        event = SimpleNamespace(raw_text=text, edit=edit, out=True, chat_id=chat_id, id=message_id)
        await self.app.dispatcher.dispatch_command(event)
        return sent[-1]

    async def reply(self, text, to, *, chat_id=5, message_id=101):
        sent: list[str] = []

        async def edit(reply):
            sent.append(reply)

        event = SimpleNamespace(
            raw_text=text, edit=edit, out=True, chat_id=chat_id, id=message_id, reply_to_msg_id=to
        )
        await self.app.dispatcher.dispatch("new_message", event)
        return sent[-1] if sent else None

    def new_message_handlers(self) -> int:
        return len(self.app.dispatcher.handlers["new_message"])


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx = ModuleFixture()
        await self.fx.start()

    async def test_command_is_registered_with_help(self):
        command = self.fx.app.dispatcher.commands["time"]
        self.assertIn("часы", command.description)
        for part in (".time on <номер>", ".time off", ".time tz", "64"):
            self.assertIn(part, command.details)
        self.assertNotRegex(command.details, r"[*`]|__")

    async def test_menu_lists_all_styles_with_live_examples(self):
        text = await self.fx.say(".time")
        for style in styles.STYLES:
            self.assertIn(f"{style.number}. {style.render(12, 34)}", text)
        self.assertIn("Сейчас выключены", text)
        self.assertNotIn("0. Выключить", text)
        self.assertIn("UTC+0", text)
        self.assertLess(len(text), 1500)

    async def test_reply_with_number_turns_clock_on(self):
        await self.fx.say(".time", message_id=100)
        self.assertEqual(self.fx.new_message_handlers(), 1)
        answer = await self.fx.reply("5", to=100)
        self.assertIn("Часы включены: стиль 5", answer)
        self.assertEqual(self.fx.backend.first, "Candy [12:34]")
        self.assertEqual(self.fx.new_message_handlers(), 0)  # меню закрыто

    async def test_reply_to_another_message_or_chat_is_ignored(self):
        await self.fx.say(".time", message_id=100)
        self.assertIsNone(await self.fx.reply("5", to=999))
        self.assertIsNone(await self.fx.reply("5", to=100, chat_id=77))
        self.assertEqual(self.fx.backend.sets, [])
        self.assertEqual(self.fx.new_message_handlers(), 1)  # меню всё ещё ждёт

    async def test_reply_with_non_number_keeps_menu_open(self):
        await self.fx.say(".time", message_id=100)
        self.assertIsNone(await self.fx.reply("привет", to=100))
        self.assertIsNone(await self.fx.reply("99", to=100))
        self.assertIsNone(await self.fx.reply("0", to=100))  # часы выключены: «0» не команда
        self.assertEqual(self.fx.new_message_handlers(), 1)
        self.assertIn("Часы включены", await self.fx.reply("3", to=100))

    async def test_menu_when_enabled_offers_off_and_zero_disables(self):
        await self.fx.say(".time on 2")
        text = await self.fx.say(".time", message_id=200)
        self.assertIn("Сейчас включены, стиль 2", text)
        self.assertIn("0. Выключить часы", text)
        answer = await self.fx.reply("0", to=200)
        self.assertIn("выключены", answer)
        self.assertEqual(self.fx.backend.first, "Candy")

    async def test_menu_when_enabled_allows_changing_style(self):
        await self.fx.say(".time on 2")
        await self.fx.say(".time", message_id=200)
        self.assertIn("Стиль часов изменён: стиль 7", await self.fx.reply("7", to=200))
        self.assertEqual(self.fx.backend.first, "Candy 「12:34」")

    async def test_second_menu_replaces_the_first(self):
        await self.fx.say(".time", message_id=100)
        await self.fx.say(".time", message_id=200)
        self.assertEqual(self.fx.new_message_handlers(), 1)
        self.assertIsNone(await self.fx.reply("5", to=100))
        self.assertIn("Часы включены", await self.fx.reply("5", to=200))

    async def test_on_with_number_and_changing_style(self):
        self.assertIn("Часы включены: стиль 5", await self.fx.say(".time on 5"))
        self.assertEqual(self.fx.backend.first, "Candy [12:34]")
        self.assertIn("Стиль часов изменён: стиль 6", await self.fx.say(".time on 6"))
        self.assertEqual(self.fx.backend.first, "Candy (12:34)")
        self.assertEqual(self.fx.app.background.started, [TASK_NAME])

    async def test_on_with_bad_number(self):
        for text in (".time on 0", ".time on 99", ".time on abc", ".time on -1"):
            with self.subTest(text=text):
                self.assertIn("❌", await self.fx.say(text))
        self.assertEqual(self.fx.backend.sets, [])

    async def test_on_without_number(self):
        text = await self.fx.say(".time on")  # стиль ещё не выбирали: показывает меню
        self.assertIn("🕒 Часы в имени", text)
        await self.fx.say(".time on 4")
        await self.fx.say(".time off")
        self.assertIn("стиль 4", await self.fx.say(".time on"))  # прежний стиль

    async def test_off(self):
        self.assertIn("и так выключены", await self.fx.say(".time off"))
        await self.fx.say(".time on 1")
        self.assertIn("Часы выключены", await self.fx.say(".time off"))
        self.assertEqual(self.fx.backend.first, "Candy")
        self.assertIn("и так выключены", await self.fx.say(".time off"))

    async def test_timezone_command(self):
        self.assertIn("UTC+0", await self.fx.say(".time tz"))
        self.assertIn("UTC+5", await self.fx.say(".time tz +5"))
        self.assertIn("Сейчас там 17:34", await self.fx.say(".time tz"))
        self.assertIn("❌", await self.fx.say(".time tz Mars/Olympus"))

    async def test_usage_for_garbage(self):
        for text in (".time foo", ".time off now", ".time on 1 2", ".time tz a b"):
            with self.subTest(text=text):
                self.assertIn("Использование: .time", await self.fx.say(text))

    async def test_name_errors_are_shown_to_the_user(self):
        self.fx.backend.first = "Н" * 62
        text = await self.fx.say(".time on 1")
        self.assertIn("слишком длинное", text)
        self.assertEqual(self.fx.backend.first, "Н" * 62)

    async def test_stop_removes_command_menu_and_clock(self):
        await self.fx.say(".time on 1")
        await self.fx.say(".time", message_id=300)
        await self.fx.module.stop()
        self.assertNotIn("time", self.fx.app.dispatcher.commands)
        self.assertEqual(self.fx.new_message_handlers(), 0)
        self.assertEqual(self.fx.backend.first, "Candy")

    async def test_resumes_after_restart(self):
        await self.fx.say(".time on 9")
        await self.fx.module.stop()
        second = ModuleFixture()
        second.store, second.backend = self.fx.store, self.fx.backend
        second.app.storage = SimpleNamespace(plugin_data=self.fx.store)
        await second.start()
        self.assertEqual(second.backend.first, "Candy ✦ 12:34 ✦")
        await second.module.stop()


if __name__ == "__main__":
    unittest.main()
