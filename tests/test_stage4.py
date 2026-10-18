"""Этап 4: фоновые задачи (состояние, пауза) и модули (required, зависимости, уведомление)."""
from __future__ import annotations

import asyncio
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from core.background import FAILING, RUNNING, STOPPED, BackgroundManager
from core.console import ConsoleManager
from core.module import Module
from core.modules import ModuleManager, ModuleStartError
from core.summary import failed_summary
from core.errors import UserError
from modules.system.accounts import AccountsModule
from modules.system.backup import BackupModule
from modules.system.heartbeat import HeartbeatModule
from modules.system.status import StatusModule
from modules.storage.labels import LabelsModule

try:
    from core.app import UserbotApp
except ImportError:  # Telethon не установлен
    UserbotApp = None


# ------------------------------------------------------------- фоновые задачи


class BackgroundStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_follows_lifecycle(self):
        manager = BackgroundManager()
        item = manager.register("t", lambda: None, interval=0.01)
        self.assertEqual(item.status, STOPPED)
        await manager.start("t")
        self.assertEqual(item.status, RUNNING)
        await asyncio.sleep(0.05)
        self.assertGreaterEqual(item.runs, 2)
        self.assertIsNotNone(item.last_run)
        self.assertIsNotNone(item.last_success)
        self.assertIsNone(item.last_error)
        await manager.stop("t")
        self.assertEqual(item.status, STOPPED)

    async def test_failing_task_reports_error_and_counters(self):
        async def broken():
            raise ValueError("всегда падаю")

        manager = BackgroundManager()
        item = manager.register("a", broken, interval=0.01)
        with self.assertLogs("candy", level="DEBUG"):
            await manager.start("a")
            await asyncio.sleep(0.06)
            self.assertEqual(item.status, FAILING)
            await manager.stop("a")
        self.assertGreaterEqual(item.failures, 2)
        self.assertEqual(item.failures, item.consecutive_failures)
        self.assertEqual(item.last_error, "ValueError: всегда падаю")
        self.assertIsNotNone(item.last_error_at)
        self.assertIsNone(item.last_success)

    async def test_recovery_resets_consecutive_but_keeps_totals(self):
        calls = 0

        def flaky():
            nonlocal calls
            calls += 1
            if calls <= 2:
                raise RuntimeError("пока рано")

        manager = BackgroundManager()
        item = manager.register("f", flaky, interval=0.01)
        with self.assertLogs("candy", level="INFO") as logs:
            await manager.start("f")
            await asyncio.sleep(0.08)
            await manager.stop("f")
        self.assertEqual(item.failures, 2)
        self.assertEqual(item.consecutive_failures, 0)
        self.assertEqual(item.last_error, "RuntimeError: пока рано")  # история сохраняется
        self.assertTrue(any("восстановилась" in line for line in logs.output))

    async def test_restart_clears_failure_streak(self):
        manager = BackgroundManager()
        item = manager.register("a", lambda: 1 / 0, interval=0.01)
        with self.assertLogs("candy", level="DEBUG"):
            await manager.start("a")
            await asyncio.sleep(0.03)
            await manager.stop("a")
        self.assertGreater(item.consecutive_failures, 0)
        item.callback = lambda: None
        await manager.start("a")
        self.assertEqual(item.consecutive_failures, 0)
        await manager.stop("a")

    async def test_error_without_message_and_long_error_are_trimmed(self):
        async def silent():
            raise KeyError

        async def wordy():
            raise RuntimeError("x" * 1000)

        manager = BackgroundManager()
        a = manager.register("a", silent, interval=5)
        b = manager.register("b", wordy, interval=5)
        with self.assertLogs("candy", level="ERROR"):
            await manager.start_all()
            await asyncio.sleep(0.03)
            await manager.stop_all()
        self.assertEqual(a.last_error, "KeyError")
        self.assertLessEqual(len(b.last_error), 200)

    async def test_isolation_between_tasks(self):
        ok = []
        manager = BackgroundManager()
        manager.register("a", lambda: 1 / 0, interval=0.01)
        manager.register("b", lambda: ok.append("b"), interval=0.01)
        manager.register("c", lambda: ok.append("c"), interval=0.01)
        with self.assertLogs("candy", level="DEBUG"):
            await manager.start_all()
            await asyncio.sleep(0.05)
            statuses = {i.name: i.status for i in manager.list()}
            await manager.stop_all()
        self.assertEqual(statuses, {"a": FAILING, "b": RUNNING, "c": RUNNING})
        self.assertIn("b", ok)
        self.assertIn("c", ok)

    async def test_backoff_grows_after_threshold_and_is_capped(self):
        manager = BackgroundManager(failure_threshold=3, max_backoff=100)
        item = manager.register("a", lambda: None, interval=10)
        delays = []
        for streak in range(0, 9):
            item.consecutive_failures = streak
            delays.append(manager.delay_for(item))
        self.assertEqual(delays, [10, 10, 10, 20, 40, 80, 100, 100, 100])

    async def test_backoff_never_below_interval(self):
        manager = BackgroundManager(max_backoff=1)
        item = manager.register("a", lambda: None, interval=30)
        item.consecutive_failures = 50
        self.assertEqual(manager.delay_for(item), 30)

    async def test_backoff_huge_streak_does_not_overflow(self):
        manager = BackgroundManager()
        item = manager.register("a", lambda: None, interval=1)
        item.consecutive_failures = 10**6
        self.assertEqual(manager.delay_for(item), manager.max_backoff)

    async def test_failing_task_slows_down(self):
        calls = 0

        def broken():
            nonlocal calls
            calls += 1
            raise RuntimeError("x")

        manager = BackgroundManager(failure_threshold=1, max_backoff=10)
        manager.register("a", broken, interval=0.02)
        with self.assertLogs("candy", level="DEBUG"):
            await manager.start("a")
            await asyncio.sleep(0.3)
            await manager.stop("a")
        # без паузы было бы ~15 запусков; с удвоением 0.04, 0.08, 0.16: около 4
        self.assertLessEqual(calls, 6)
        self.assertGreaterEqual(calls, 2)

    async def test_log_is_not_spammed_by_long_failure_series(self):
        manager = BackgroundManager(failure_threshold=100)  # пауза не растёт: считаем только шум
        item = manager.register("a", lambda: 1 / 0, interval=5)
        with self.assertLogs("candy", level="DEBUG") as logs:
            for _ in range(40):
                await manager._run_once(item)
        loud = [r for r in logs.records if r.levelname in ("ERROR", "WARNING")]
        # traceback один раз, предупреждения на степенях двойки: 2, 4, 8, 16, 32
        self.assertEqual(len([r for r in loud if r.exc_info]), 1)
        self.assertEqual(len(loud), 6)

    async def test_get_and_cancellation_is_not_a_failure(self):
        started = asyncio.Event()

        async def waiting():
            started.set()
            await asyncio.Event().wait()

        manager = BackgroundManager()
        item = manager.register("w", waiting, interval=1)
        self.assertIs(manager.get("w"), item)
        self.assertIsNone(manager.get("zzz"))
        await manager.start("w")
        await started.wait()
        await manager.stop("w")
        self.assertEqual(item.failures, 0)

    async def test_remove_requires_stopped_task(self):
        manager = BackgroundManager()
        manager.register("t", lambda: None, interval=1)
        await manager.start("t")
        with self.assertRaises(RuntimeError):
            manager.remove("t")
        await manager.stop("t")
        manager.remove("t")
        self.assertEqual(manager.list(), [])


# ------------------------------------------------------------------- модули


def make_module(name, *, required=False, requires=(), start=None, stop=None, log=None):
    class Fake(Module):
        async def start(self):
            if log is not None:
                log.append(f"start {name}")
            if start is not None:
                raise start

        async def stop(self):
            if log is not None:
                log.append(f"stop {name}")
            if stop is not None:
                raise stop

    Fake.name = name
    Fake.required = required
    Fake.requires = tuple(requires)
    return Fake(SimpleNamespace())


class ModuleManagerTests(unittest.IsolatedAsyncioTestCase):
    def manager(self, *modules):
        manager = ModuleManager(SimpleNamespace())
        for module in modules:
            manager.register(module)
        return manager

    async def test_defaults_are_optional_without_dependencies(self):
        self.assertFalse(Module.required)
        self.assertEqual(Module.requires, ())

    async def test_optional_failure_only_notifies_and_others_run(self):
        log = []
        manager = self.manager(
            make_module("a", log=log),
            make_module("bad", start=RuntimeError("не вышло"), log=log),
            make_module("c", log=log),
        )
        with self.assertLogs("candy", level="ERROR"):
            await manager.start_all()
        self.assertEqual(log, ["start a", "start bad", "start c"])
        states = {s.module.name: s for s in manager.states()}
        self.assertTrue(states["a"].started and states["c"].started)
        self.assertTrue(states["bad"].failed)
        self.assertEqual(states["bad"].status, "failed")
        self.assertEqual(states["bad"].error, "RuntimeError: не вышло")
        self.assertEqual(manager.startup_failures, [("bad", "RuntimeError: не вышло")])
        self.assertEqual([s.module.name for s in manager.failures()], ["bad"])

    async def test_required_failure_stops_startup(self):
        log = []
        manager = self.manager(
            make_module("a", log=log),
            make_module("core", required=True, start=RuntimeError("критично"), log=log),
            make_module("never", log=log),
        )
        with self.assertLogs("candy", level="ERROR"), self.assertRaises(ModuleStartError) as ctx:
            await manager.start_all()
        self.assertIn("core", str(ctx.exception))
        self.assertIn("критично", str(ctx.exception))
        self.assertTrue(issubclass(ModuleStartError, UserError))
        self.assertEqual(log, ["start a", "start core"])  # never не запускался

    async def test_stop_all_after_failed_startup_stops_only_started(self):
        log = []
        manager = self.manager(
            make_module("a", log=log),
            make_module("core", required=True, start=RuntimeError("x"), log=log),
        )
        with self.assertLogs("candy", level="ERROR"), self.assertRaises(ModuleStartError):
            await manager.start_all()
        await manager.stop_all()
        self.assertEqual(log, ["start a", "start core", "stop a"])

    async def test_dependencies_are_started_first_and_stopped_last(self):
        log = []
        manager = self.manager(
            make_module("app", requires=("db", "cache"), log=log),
            make_module("cache", requires=("db",), log=log),
            make_module("db", log=log),
        )
        await manager.start_all()
        self.assertEqual(log, ["start db", "start cache", "start app"])
        log.clear()
        await manager.stop_all()
        self.assertEqual(log, ["stop app", "stop cache", "stop db"])

    async def test_registration_order_is_kept_when_there_are_no_dependencies(self):
        manager = self.manager(make_module("z"), make_module("a"), make_module("m"))
        order, problems = manager.start_order()
        self.assertEqual((order, problems), (["z", "a", "m"], {}))

    async def test_dependent_of_failed_module_is_skipped(self):
        log = []
        manager = self.manager(
            make_module("db", start=RuntimeError("down"), log=log),
            make_module("app", requires=("db",), log=log),
            make_module("free", log=log),
        )
        with self.assertLogs("candy", level="ERROR"):
            await manager.start_all()
        self.assertEqual(log, ["start db", "start free"])
        states = {s.module.name: s for s in manager.states()}
        self.assertIn("'db'", states["app"].error)
        self.assertEqual({n for n, _ in manager.startup_failures}, {"db", "app"})

    async def test_required_module_with_failed_dependency_stops_startup(self):
        manager = self.manager(
            make_module("db", start=RuntimeError("down")),
            make_module("core", required=True, requires=("db",)),
        )
        with self.assertLogs("candy", level="ERROR"), self.assertRaisesRegex(ModuleStartError, "core"):
            await manager.start_all()

    async def test_unknown_dependency(self):
        manager = self.manager(
            make_module("a", requires=("ghost",)), make_module("b")
        )
        with self.assertLogs("candy", level="ERROR"):
            await manager.start_all()
        a = next(s for s in manager.states() if s.module.name == "a")
        self.assertTrue(a.failed)
        self.assertIn("ghost", a.error)
        self.assertTrue(next(s for s in manager.states() if s.module.name == "b").started)

    async def test_required_with_unknown_dependency_is_fatal(self):
        manager = self.manager(make_module("a", required=True, requires=("ghost",)))
        with self.assertLogs("candy", level="ERROR"), self.assertRaisesRegex(ModuleStartError, "ghost"):
            await manager.start_all()

    async def test_cycle_is_detected_without_hanging(self):
        log = []
        manager = self.manager(
            make_module("a", requires=("b",), log=log),
            make_module("b", requires=("c",), log=log),
            make_module("c", requires=("a",), log=log),
            make_module("ok", log=log),
        )
        order, problems = manager.start_order()
        self.assertEqual(set(problems), {"a", "b", "c"})
        self.assertIn("циклическая", problems["a"])
        with self.assertLogs("candy", level="ERROR"):
            await manager.start_all()
        self.assertEqual(log, ["start ok"])

    async def test_register_validation(self):
        manager = self.manager(make_module("a"))
        with self.assertRaises(ValueError):
            manager.register(make_module("a"))
        with self.assertRaises(ValueError):
            manager.register(make_module("self", requires=("self",)))
        bad = make_module("str")
        bad.requires = "db"
        with self.assertRaises(ValueError):
            manager.register(bad)
        with self.assertRaises(ValueError):
            manager.register(make_module("  "))

    async def test_stop_cascades_to_dependents(self):
        log = []
        manager = self.manager(
            make_module("db", log=log),
            make_module("app", requires=("db",), log=log),
        )
        await manager.start_all()
        log.clear()
        self.assertTrue(await manager.stop("db"))
        self.assertEqual(log, ["stop app", "stop db"])
        states = {s.module.name: s.started for s in manager.states()}
        self.assertEqual(states, {"db": False, "app": False})

    async def test_manual_start_checks_dependencies(self):
        manager = self.manager(make_module("db"), make_module("app", requires=("db",)))
        with self.assertLogs("candy", level="ERROR"):
            self.assertFalse(await manager.start("app"))
        self.assertTrue(await manager.start("db"))
        self.assertTrue(await manager.start("app"))
        self.assertTrue(manager.states()[1].started)
        self.assertIsNone(manager.states()[1].error)

    async def test_restart_after_failure_clears_error(self):
        module = make_module("a", start=RuntimeError("1"))
        manager = self.manager(module)
        with self.assertLogs("candy", level="ERROR"):
            await manager.start_all()
        self.assertTrue(manager.states()[0].failed)
        module.__class__.start = AsyncMock()
        self.assertTrue(await manager.start("a"))
        state = manager.states()[0]
        self.assertFalse(state.failed)
        self.assertIsNone(state.error)

    async def test_stop_failure_does_not_stop_the_rest(self):
        log = []
        manager = self.manager(
            make_module("a", log=log),
            make_module("b", stop=RuntimeError("stop boom"), log=log),
            make_module("c", log=log),
        )
        await manager.start_all()
        log.clear()
        with self.assertLogs("candy", level="ERROR"):
            await manager.stop_all()
        self.assertEqual(log, ["stop c", "stop b", "stop a"])

    async def test_start_all_can_be_repeated(self):
        log = []
        manager = self.manager(make_module("a", log=log))
        await manager.start_all()
        await manager.start_all()
        self.assertEqual(log, ["start a"])

    async def test_startup_failures_are_reset_between_runs(self):
        module = make_module("a", start=RuntimeError("x"))
        manager = self.manager(module)
        with self.assertLogs("candy", level="ERROR"):
            await manager.start_all()
            await manager.start_all()
        self.assertEqual(len(manager.startup_failures), 1)


class SystemModuleFlagTests(unittest.TestCase):
    def test_system_modules_are_required_and_labels_optional(self):
        for cls in (StatusModule, HeartbeatModule, AccountsModule, BackupModule):
            self.assertTrue(cls.required, cls.__name__)
        self.assertFalse(LabelsModule.required)


# ---------------------------------------------------------- .status и консоль


class StatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_shows_failing_task_with_error(self):
        modules = ModuleManager(SimpleNamespace())
        modules.register(make_module("ok"))
        modules.register(make_module("bad", start=RuntimeError("модуль упал")))
        background = BackgroundManager()
        background.register("A", lambda: 1 / 0, interval=0.01)
        background.register("B", lambda: None, interval=0.01)
        background.register("C", lambda: None, interval=0.01)
        app = SimpleNamespace(
            modules=modules, background=background, plugins=SimpleNamespace(states=lambda: [])
        )
        from core.health import build_health

        app.health = lambda: build_health(app)
        with self.assertLogs("candy", level="DEBUG"):
            await modules.start_all()
            await background.start_all()
            await asyncio.sleep(0.05)
        try:
            from core.dispatcher import Dispatcher

            app.dispatcher = Dispatcher()
            module = StatusModule(app)
            await module.start()
            edits = []

            async def edit(text):
                edits.append(text)

            await app.dispatcher.dispatch_command(SimpleNamespace(raw_text=".status all", edit=edit))
        finally:
            await background.stop_all()
        text = edits[-1]
        self.assertIn("Модули: 1/2 запущено, ошибок запуска: 1", text)
        self.assertIn("❌ bad", text)
        self.assertIn("модуль упал", text)
        self.assertRegex(text, r"A: FAILING.*ZeroDivisionError")
        self.assertRegex(text, r"B: RUNNING")
        self.assertRegex(text, r"C: RUNNING")
        self.assertIn("Фоновые задачи: 3", text)

    async def test_console_modules_and_tasks(self):
        modules = ModuleManager(SimpleNamespace())
        modules.register(make_module("ok", required=True))
        background = BackgroundManager()
        background.register("t", lambda: None, interval=1)
        app = SimpleNamespace(modules=modules, background=background, plugins=SimpleNamespace(states=lambda: []))
        app.health = lambda: SimpleNamespace(lines=lambda: ["Состояние: ok"])
        console = ConsoleManager(app)
        await modules.start_all()
        with contextlib.redirect_stdout(io.StringIO()):
            short = await console.execute("status")
            self.assertIn("Состояние: ok", short)
            self.assertNotIn("обязательный", short)  # кратко: без списка модулей
            full = await console.execute("status all")
            self.assertIn("✅ ok (обязательный)", full)
            self.assertIn("STOPPED", full)
            self.assertIn("Использование", await console.execute("status bogus"))
            help_text = await console.execute("help")
            self.assertIn("status [all]", help_text)
            self.assertNotIn("health", help_text)
            self.assertIn("Неизвестная команда", await console.execute("health"))

    async def test_console_status_all_without_tasks(self):
        app = SimpleNamespace(
            modules=ModuleManager(SimpleNamespace()),
            background=BackgroundManager(),
            plugins=SimpleNamespace(states=lambda: []),
            health=lambda: SimpleNamespace(lines=lambda: ["Состояние: ok"]),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn("Фоновые задачи:\nнет", await ConsoleManager(app).execute("status all"))


class FailedSummaryTests(unittest.TestCase):
    def test_none_when_everything_started(self):
        app = SimpleNamespace(
            modules=SimpleNamespace(startup_failures=[]), plugins=SimpleNamespace(states=lambda: [])
        )
        self.assertIsNone(failed_summary(app))

    def test_lists_modules_and_plugins(self):
        app = SimpleNamespace(
            modules=SimpleNamespace(startup_failures=[("storage.labels", "OSError: диск")]),
            plugins=SimpleNamespace(states=lambda: [SimpleNamespace(name="demo", failed=True),
                                                    SimpleNamespace(name="fine", failed=False)]),
        )
        text = failed_summary(app)
        self.assertIn("storage.labels: OSError: диск", text)
        self.assertIn("плагин demo", text)
        self.assertNotIn("fine", text)


# --------------------------------------------------------- запуск приложения


class FakeClient:
    def __init__(self, send_error=None):
        self.connected = False
        self.send_message = AsyncMock(side_effect=send_error)
        self.disconnect = AsyncMock(side_effect=self._disconnect)

    async def connect(self):
        self.connected = True

    async def is_user_authorized(self):
        return True

    def is_connected(self):
        return self.connected

    async def _disconnect(self):
        self.connected = False


@unittest.skipIf(UserbotApp is None, "Telethon не установлен")
class AppStartupPolicyTests(unittest.IsolatedAsyncioTestCase):
    def make_app(self, tmp, modules, client):
        base = Path(tmp)
        with patch("core.app.ensure_directories"), patch(
            "core.app.ACCOUNTS_DIR", base / "accounts"
        ), patch("core.app.DATABASE_PATH", base / "db" / "candy.sqlite3"):
            app = UserbotApp()
        app._ensure_account = AsyncMock(return_value=SimpleNamespace(display_name="@me"))
        app.console.start = AsyncMock()
        app.plugins.load_all = AsyncMock()
        app.events = None

        def register(application):
            for module in modules:
                application.modules.register(module)

        self.patches = [
            patch("core.app.create_client", return_value=client),
            patch("core.app.register_system_modules", register),
            patch("core.app.EventBridge", return_value=MagicMock()),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        return app

    async def test_optional_failure_keeps_userbot_running_and_notifies_owner(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(
                tmp,
                [make_module("good", required=True), make_module("bad", start=RuntimeError("упал"))],
                client,
            )
            with self.assertLogs("candy", level="ERROR"):
                await app.start()
            self.assertTrue(client.connected)
            client.send_message.assert_awaited_once()
            target, text = client.send_message.await_args.args
            self.assertEqual(target, "me")
            self.assertIn("bad", text)
            self.assertIn("упал", text)
            await app.stop()

    async def test_no_notification_when_everything_started(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp, [make_module("good")], client)
            await app.start()
            client.send_message.assert_not_awaited()
            await app.stop()

    async def test_required_failure_aborts_with_rollback_and_no_notification(self):
        client = FakeClient()
        log = []
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(
                tmp,
                [
                    make_module("first", required=True, log=log),
                    make_module("core", required=True, start=RuntimeError("критично"), log=log),
                    make_module("late", log=log),
                ],
                client,
            )
            with self.assertLogs("candy", level="ERROR"), self.assertRaises(ModuleStartError):
                await app.start()
            self.assertEqual(log, ["start first", "start core", "stop first"])
            client.disconnect.assert_awaited()
            client.send_message.assert_not_awaited()
            app.console.start.assert_not_awaited()

    async def test_notification_failure_never_breaks_startup(self):
        client = FakeClient(send_error=RuntimeError("нет сети"))
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp, [make_module("bad", start=RuntimeError("x"))], client)
            with self.assertLogs("candy", level="WARNING"):
                await app.start()
            self.assertFalse(await app.notify_owner("ещё раз"))
            await app.stop()

    async def test_notify_owner_without_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp, [], FakeClient())
            self.assertFalse(await app.notify_owner("текст"))

    async def test_notify_owner_times_out(self):
        client = FakeClient()

        async def hang(*_a):
            await asyncio.Event().wait()

        client.send_message = hang
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp, [], client)
            app.client = client
            with patch("core.app.NOTIFY_TIMEOUT", 0.05), self.assertLogs("candy", level="WARNING"):
                self.assertFalse(await asyncio.wait_for(app.notify_owner("t"), 2))


if __name__ == "__main__":
    unittest.main()
