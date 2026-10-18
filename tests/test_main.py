"""Этап 1: коды выхода, сигналы, потеря связи."""
from __future__ import annotations

import asyncio
import os
import signal
import sys
import unittest
from unittest.mock import patch

import main
from core.errors import UserError
from main import EXIT_CONFIG, EXIT_ERROR, EXIT_FORCED, EXIT_OK, StopSignals, run_app, run_cli


class FakeApp:
    """Подменяет UserbotApp: поведение start/run задаётся корутинами."""

    def __init__(self, start=None, run=None):
        self._start = start
        self._run = run
        self.stop_calls = 0
        self._stopping = False

    @property
    def is_stopping(self) -> bool:
        return self._stopping

    async def start(self):
        if self._start:
            await self._start(self)

    async def run(self):
        if self._run:
            await self._run(self)

    async def stop(self):
        self.stop_calls += 1
        self._stopping = True


async def forever(_app):
    await asyncio.Event().wait()


class RunAppTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_request_while_running_gives_ok(self):
        stop = asyncio.Event()
        app = FakeApp(run=forever)
        task = asyncio.create_task(run_app(app, stop))
        await asyncio.sleep(0.05)
        stop.set()
        self.assertEqual(await asyncio.wait_for(task, 1), EXIT_OK)
        self.assertEqual(app.stop_calls, 1)

    async def test_startup_error_gives_error_code_and_stops(self):
        async def broken(_app):
            raise RuntimeError("boom")

        app = FakeApp(start=broken)
        self.assertEqual(await run_app(app, asyncio.Event()), EXIT_ERROR)
        self.assertEqual(app.stop_calls, 1)

    async def test_eof_on_first_run_gives_error_code(self):
        async def eof(_app):
            raise EOFError

        app = FakeApp(start=eof)
        self.assertEqual(await run_app(app, asyncio.Event()), EXIT_CONFIG)
        self.assertEqual(app.stop_calls, 1)

    async def test_run_returning_by_itself_is_a_lost_connection(self):
        app = FakeApp()  # run() сразу возвращается, остановку никто не просил
        self.assertEqual(await run_app(app, asyncio.Event()), EXIT_ERROR)
        self.assertEqual(app.stop_calls, 1)

    async def test_run_returning_after_requested_stop_is_ok(self):
        async def run(app):
            app._stopping = True  # так выглядит .stop из Telegram или консоли

        app = FakeApp(run=run)
        self.assertEqual(await run_app(app, asyncio.Event()), EXIT_OK)

    async def test_run_failure_gives_error_code(self):
        async def run(_app):
            raise ConnectionError("network")

        app = FakeApp(run=run)
        self.assertEqual(await run_app(app, asyncio.Event()), EXIT_ERROR)
        self.assertEqual(app.stop_calls, 1)

    async def test_stop_request_during_startup_cancels_it(self):
        stop = asyncio.Event()
        cancelled = asyncio.Event()

        async def slow_start(_app):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        app = FakeApp(start=slow_start)
        task = asyncio.create_task(run_app(app, stop))
        await asyncio.sleep(0.05)
        stop.set()
        self.assertEqual(await asyncio.wait_for(task, 1), EXIT_OK)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(app.stop_calls, 1)

    async def test_cancellation_of_main_task_is_graceful(self):
        # Запасной путь без обработчиков сигналов (Ctrl+C в Windows).
        app = FakeApp(run=forever)
        task = asyncio.create_task(run_app(app, asyncio.Event()))
        await asyncio.sleep(0.05)
        task.cancel()
        self.assertEqual(await asyncio.wait_for(task, 1), EXIT_OK)
        self.assertEqual(app.stop_calls, 1)


@unittest.skipUnless(hasattr(signal, "SIGTERM") and os.name == "posix", "нужны POSIX-сигналы")
class RealSignalTests(unittest.IsolatedAsyncioTestCase):
    async def run_with_signal(self, signum):
        stop = asyncio.Event()
        signals = StopSignals(asyncio.get_running_loop(), stop, force_exit=lambda c: None)
        signals.install()
        try:
            app = FakeApp(run=forever)
            task = asyncio.create_task(run_app(app, stop))
            await asyncio.sleep(0.05)
            os.kill(os.getpid(), signum)
            code = await asyncio.wait_for(task, 2)
        finally:
            signals.uninstall()
        return code, app

    async def test_sigterm_stops_gracefully(self):
        code, app = await self.run_with_signal(signal.SIGTERM)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(app.stop_calls, 1)

    async def test_sigint_stops_gracefully_without_keyboardinterrupt(self):
        code, app = await self.run_with_signal(signal.SIGINT)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(app.stop_calls, 1)

    async def test_handlers_are_removed_after_uninstall(self):
        before = signal.getsignal(signal.SIGTERM)
        signals = StopSignals(asyncio.get_running_loop(), asyncio.Event())
        signals.install()
        self.assertNotEqual(signal.getsignal(signal.SIGTERM), before)
        signals.uninstall()
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)


class StopSignalsTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_signal_forces_exit(self):
        exits: list[int] = []
        event = asyncio.Event()
        signals = StopSignals(asyncio.get_running_loop(), event, force_exit=exits.append)
        signals._on_signal("SIGINT")
        self.assertTrue(event.is_set())
        self.assertEqual(exits, [])
        signals._on_signal("SIGINT")
        self.assertEqual(exits, [EXIT_FORCED])

    async def test_install_tolerates_loop_without_signal_support(self):
        class NoSignalsLoop:
            def add_signal_handler(self, *args):
                raise NotImplementedError

            def remove_signal_handler(self, *args):
                raise NotImplementedError

        signals = StopSignals(NoSignalsLoop(), asyncio.Event())
        signals.install()  # не должно падать
        signals.uninstall()
        self.assertEqual(signals._installed, [])

    @unittest.skipUnless(hasattr(signal, "SIGHUP"), "нет SIGHUP")
    async def test_ignored_sighup_stays_ignored(self):
        previous = signal.getsignal(signal.SIGHUP)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)  # так делает nohup
        try:
            signals = StopSignals(asyncio.get_running_loop(), asyncio.Event())
            signals.install()
            try:
                self.assertEqual(signal.getsignal(signal.SIGHUP), signal.SIG_IGN)
            finally:
                signals.uninstall()
        finally:
            signal.signal(signal.SIGHUP, previous)


class MainEntryTests(unittest.TestCase):
    def test_main_returns_exit_code_from_amain(self):
        async def fake_amain(args=None):
            return 7

        original = main.amain
        main.amain = fake_amain
        try:
            self.assertEqual(main.main([]), 7)
        finally:
            main.amain = original

    def test_keyboard_interrupt_is_ok(self):
        original = main.asyncio.run

        def raising(coro):
            coro.close()
            raise KeyboardInterrupt

        main.asyncio.run = raising
        try:
            self.assertEqual(main.main([]), EXIT_OK)
        finally:
            main.asyncio.run = original


class UserErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_error_gives_config_exit_without_traceback(self):
        async def broken(_app):
            raise UserError("Сессия отозвана. Войдите заново.")

        app = FakeApp(start=broken)
        with self.assertLogs("candy", level="ERROR") as logs:
            code = await run_app(app, asyncio.Event())
        self.assertEqual(code, EXIT_CONFIG)
        self.assertEqual(app.stop_calls, 1)
        self.assertEqual(len(logs.records), 1)
        self.assertIsNone(logs.records[0].exc_info)
        self.assertIn("Сессия отозвана", logs.records[0].getMessage())


class RunCliTests(unittest.IsolatedAsyncioTestCase):
    async def test_success(self):
        async def action():
            return None

        self.assertEqual(await run_cli(action, asyncio.Event()), EXIT_OK)

    async def test_user_error(self):
        async def action():
            raise UserError("Замена отменена")

        with self.assertLogs("candy", level="ERROR") as logs:
            self.assertEqual(await run_cli(action, asyncio.Event()), EXIT_CONFIG)
        self.assertIsNone(logs.records[0].exc_info)

    async def test_eof(self):
        async def action():
            raise EOFError

        with self.assertLogs("candy", level="ERROR"):
            self.assertEqual(await run_cli(action, asyncio.Event()), EXIT_CONFIG)

    async def test_unexpected_error(self):
        async def action():
            raise RuntimeError("boom")

        self.assertEqual(await run_cli(action, asyncio.Event()), EXIT_ERROR)

    async def test_stop_signal_cancels_action(self):
        stop = asyncio.Event()
        cancelled = asyncio.Event()

        async def action():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(run_cli(action, stop))
        await asyncio.sleep(0.05)
        stop.set()
        self.assertEqual(await asyncio.wait_for(task, 1), EXIT_OK)
        self.assertTrue(cancelled.is_set())


class ParseArgsTests(unittest.TestCase):
    def test_defaults(self):
        args = main.parse_args([])
        self.assertFalse(args.add_account)
        self.assertIsNone(args.restore)

    def test_add_account(self):
        self.assertTrue(main.parse_args(["--add-account"]).add_account)

    def test_restore(self):
        self.assertEqual(main.parse_args(["--restore", "a.zip"]).restore, "a.zip")

    def test_options_are_mutually_exclusive(self):
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            main.parse_args(["--add-account", "--restore", "a.zip"])

    def test_restore_needs_value(self):
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            main.parse_args(["--restore"])


class RestartTests(unittest.TestCase):
    def setUp(self):
        self._saved = main._restart_requested

    def tearDown(self):
        main._restart_requested = self._saved

    def test_main_restarts_when_requested(self):
        async def fake_amain(args=None):
            return 0

        main._restart_requested = True
        with patch.object(main, "amain", fake_amain), patch.object(main, "_restart_process") as restart:
            self.assertEqual(main.main([]), 0)
        restart.assert_called_once()

    def test_main_does_not_restart_otherwise(self):
        async def fake_amain(args=None):
            return 0

        main._restart_requested = False
        with patch.object(main, "amain", fake_amain), patch.object(main, "_restart_process") as restart:
            main.main([])
        restart.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "execv")
    def test_restart_process_execs_same_script(self):
        with patch.object(main.os, "execv") as execv, patch.object(main.logging, "shutdown") as shutdown:
            main._restart_process()
        shutdown.assert_called_once()
        executable, command = execv.call_args.args
        self.assertEqual(executable, sys.executable)
        self.assertEqual(command[0], sys.executable)
        self.assertTrue(os.path.isabs(command[1]))


if __name__ == "__main__":
    unittest.main()
