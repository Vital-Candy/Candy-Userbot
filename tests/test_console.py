"""Этап 6: консоль (TTY, поток чтения, EOF) и команда .plugin в Telegram."""
from __future__ import annotations

import asyncio
import builtins
import contextlib
import io
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.access import AccessService
from core.console import ConsoleManager
from core.modules import ModuleManager
from modules.system.plugins import PluginsModule
from tests.test_plugins import Fixture, source


def tty(value=True):
    return patch("sys.stdin", SimpleNamespace(isatty=lambda: value))


class ConsoleApp:
    def __init__(self, fx: Fixture):
        self.fx = fx
        self.dispatcher = fx.app.dispatcher
        self.background = fx.app.background
        self.storage = fx.app.storage
        self.identity = fx.app.identity
        self.modules = ModuleManager(self)
        self.plugins = fx.manager
        self.stop = AsyncMock()
        self.account_control = SimpleNamespace(describe=lambda: "👤 acc")
        self.events_log = fx.app.events_log
        self.ticks = fx.app.ticks


class TtyTests(unittest.IsolatedAsyncioTestCase):
    async def test_has_tty_variants(self):
        with tty(True):
            self.assertTrue(ConsoleManager._has_tty())
        with tty(False):
            self.assertFalse(ConsoleManager._has_tty())
        with patch("sys.stdin", None):
            self.assertFalse(ConsoleManager._has_tty())

        def closed():
            raise ValueError("I/O operation on closed file")

        with patch("sys.stdin", SimpleNamespace(isatty=closed)):
            self.assertFalse(ConsoleManager._has_tty())
        with patch("sys.stdin", SimpleNamespace()):  # объект без isatty
            self.assertFalse(ConsoleManager._has_tty())

    async def test_no_tty_means_no_console_and_no_thread(self):
        console = ConsoleManager(SimpleNamespace())
        with tty(False), self.assertLogs("candy", level="INFO") as logs:
            await console.start()
        self.assertIsNone(console._task)
        self.assertIsNone(console._thread)
        self.assertIn("не является терминалом", logs.output[0])
        await console.stop()  # безопасно, даже если не запускалась


class ReaderThreadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx = Fixture()
        self.app = ConsoleApp(self.fx)

    async def asyncTearDown(self):
        self.fx.close()

    async def test_lines_are_executed_until_eof(self):
        lines = iter(["help", "", "bogus command", "status"])

        def fake_input(_prompt=""):
            try:
                return next(lines)
            except StopIteration:
                raise EOFError

        console = ConsoleManager(self.app, ui="console")
        out = io.StringIO()
        with tty(), patch.object(builtins, "input", fake_input), contextlib.redirect_stdout(out):
            with self.assertLogs("candy", level="INFO"):
                await console.start()
            await asyncio.wait_for(console._task, 3)  # EOF завершает консоль сам
        text = out.getvalue()
        self.assertIn("plugin info", text)  # help
        self.assertIn("Неизвестная команда: bogus", text)
        self.assertIn("modules=", text)  # status
        await console.stop()

    async def test_stop_does_not_wait_for_input(self):
        release = threading.Event()

        def blocking_input(_prompt=""):
            release.wait(5)
            raise EOFError

        console = ConsoleManager(self.app, ui="console")
        with tty(), patch.object(builtins, "input", blocking_input):
            with self.assertLogs("candy", level="INFO"):
                await console.start()
            await asyncio.sleep(0.05)
            await asyncio.wait_for(console.stop(), 1)  # не ждёт Enter
        self.assertIsNone(console._task)
        release.set()

    async def test_input_exception_ends_reader_without_traceback_in_thread(self):
        def broken_input(_prompt=""):
            raise OSError("terminal lost")

        console = ConsoleManager(self.app, ui="console")
        with tty(), patch.object(builtins, "input", broken_input):
            with self.assertLogs("candy", level="INFO") as logs:
                await console.start()
                await asyncio.wait_for(console._task, 3)
        self.assertTrue(any("Ошибка чтения консоли" in line for line in logs.output))

    async def test_failing_command_does_not_kill_the_loop(self):
        console = ConsoleManager(self.app, ui="console")
        calls = []

        async def execute(line):
            calls.append(line)
            if line == "boom":
                raise RuntimeError("command failed")

        console.execute = execute
        queue: asyncio.Queue = asyncio.Queue()
        for item in ("boom", "next", None):
            queue.put_nowait(item)
        with self.assertLogs("candy", level="ERROR"):
            await asyncio.wait_for(console._run(queue), 2)
        self.assertEqual(calls, ["boom", "next"])

    async def test_start_twice_and_restart(self):
        def eof(_prompt=""):
            raise EOFError

        console = ConsoleManager(self.app, ui="console")
        with tty(), patch.object(builtins, "input", eof), self.assertLogs("candy", level="INFO"):
            await console.start()
            first = console._task
            await console.start()
            self.assertIs(console._task, first)
            await asyncio.wait_for(first, 3)
        await console.stop()


class ConsoleCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx = Fixture()
        self.app = ConsoleApp(self.fx)
        self.console = ConsoleManager(self.app, ui="console")

    async def asyncTearDown(self):
        await self.fx.app.background.stop_all()
        self.fx.close()

    async def run_line(self, line):
        with contextlib.redirect_stdout(io.StringIO()):
            return await self.console.execute(line)

    async def test_blank_and_unknown(self):
        self.assertIsNone(await self.run_line(""))
        self.assertIsNone(await self.run_line("   ".strip()))
        self.assertIn("Неизвестная команда: foo", await self.run_line("foo"))
        self.assertIn("plugin load", await self.run_line("HELP"))  # регистр не важен
        self.assertIn("plugin load", await self.run_line("?"))

    async def test_plugin_usage_and_unknown(self):
        self.assertIn("Использование", await self.run_line("plugin"))
        self.assertIn("Использование", await self.run_line("plugin load"))
        self.assertIn("Использование", await self.run_line("plugin wat x"))
        self.assertIn("не найден", await self.run_line("plugin load ghost"))
        self.assertIn("не найден", await self.run_line("plugin info ghost"))

    async def test_plugin_lifecycle_and_info(self):
        self.fx.write("demo", source(description="демо"))
        self.assertIn("OK", await self.run_line("plugin load demo"))
        info = await self.run_line("plugin info demo")
        self.assertIn("загружен", info)
        self.assertIn("команд 1, обработчиков 1, задач 1", info)
        self.assertIn("✅ demo", await self.run_line("plugins"))
        self.assertIn("OK", await self.run_line("plugin reload demo"))
        self.assertIn("OK", await self.run_line("plugin unload demo"))
        self.assertIn("⏸ demo", await self.run_line("plugins"))

    async def test_plugin_error_is_shown_to_the_user(self):
        self.fx.write("bad", source("bad", setup_tail='raise RuntimeError("видно в консоли")'))
        with self.assertLogs("candy", level="ERROR"):
            result = await self.run_line("plugin load bad")
        self.assertIn("FAILED", result)
        self.assertIn("видно в консоли", result)
        self.assertIn("❌ bad: RuntimeError: видно в консоли", await self.run_line("plugins"))

    async def test_plugins_empty(self):
        self.assertIn("нет", await self.run_line("plugins"))

    async def test_stop_command(self):
        self.assertIn("stopped", await self.run_line("stop"))
        self.app.stop.assert_awaited_once()

    async def test_account_and_backup_usage(self):
        self.assertIn("Использование", await self.run_line("account wat"))
        self.assertIn("Использование", await self.run_line("backup"))


class TelegramPluginCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx = Fixture()
        self.app = self.fx.app
        self.app.plugins = self.fx.manager
        self.app.access = AccessService(self.fx.storage.permissions, self.app.identity)
        self.module = PluginsModule(self.app)
        await self.module.start()

    async def asyncTearDown(self):
        await self.fx.manager.unload_all()
        await self.app.background.stop_all()
        self.fx.close()

    async def run_cmd(self, text, *, sender=1, out=True):
        sent = []

        async def edit(value):
            sent.append(value)

        async def reply(value):
            sent.append(value)

        event = SimpleNamespace(raw_text=text, sender_id=sender, out=out, edit=edit, reply=reply)
        await self.app.dispatcher.dispatch_command(event)
        return sent[-1] if sent else None

    async def test_is_required_system_module(self):
        self.assertTrue(PluginsModule.required)

    async def test_list_empty_and_states(self):
        self.assertIn("пуста", await self.run_cmd(".plugin"))
        self.fx.write("good", source("good"))
        self.fx.write("bad", source("bad", setup_tail='raise RuntimeError("boom")'))
        self.fx.write("idle", source("idle"))
        await self.fx.manager.load("good")
        with self.assertLogs("candy", level="ERROR"):
            await self.fx.manager.load("bad")
        listing = await self.run_cmd(".plugin list")
        self.assertIn("✅ good v1.0", listing)
        self.assertIn("❌ bad: RuntimeError: boom", listing)
        self.assertIn("⏸ idle: не загружен", listing)

    async def test_load_unload_reload_info(self):
        self.fx.write("demo", source())
        self.assertIn("загружен (v1.0)", await self.run_cmd(".plugin load demo"))
        self.assertIn("demo", self.app.dispatcher.commands)
        info = await self.run_cmd(".plugin info demo")
        self.assertIn("команд 1, обработчиков 1, задач 1", info)
        self.assertIn("перезагружен", await self.run_cmd(".plugin reload demo"))
        self.assertIn("выгружен", await self.run_cmd(".plugin unload demo"))
        self.assertNotIn("demo", self.app.dispatcher.commands)
        self.assertIn("и так не загружен", await self.run_cmd(".plugin unload demo"))

    async def test_reload_picks_up_new_version_without_restart(self):
        self.fx.write("demo", source(version="1.0"))
        await self.run_cmd(".plugin load demo")
        self.fx.write("demo", source(version="2.5"))
        self.assertIn("v2.5", await self.run_cmd(".plugin reload demo"))

    async def test_load_failure_shows_reason(self):
        self.fx.write("bad", source("bad", setup_tail='raise RuntimeError("не получилось")'))
        with self.assertLogs("candy", level="ERROR"):
            reply = await self.run_cmd(".plugin load bad")
        self.assertTrue(reply.startswith("❌"))
        self.assertIn("не получилось", reply)

    async def test_teardown_failure_is_a_warning(self):
        self.fx.write("demo", source(teardown='raise RuntimeError("t boom")'))
        await self.run_cmd(".plugin load demo")
        with self.assertLogs("candy", level="ERROR"):
            reply = await self.run_cmd(".plugin unload demo")
        self.assertIn("⚠️", reply)
        self.assertIn("t boom", reply)
        self.assertNotIn("demo", self.app.dispatcher.commands)

    async def test_unknown_plugin_and_bad_names(self):
        self.assertIn("не найден", await self.run_cmd(".plugin load ghost"))
        self.assertIn("не найден", await self.run_cmd(".plugin unload ghost"))
        self.assertIn("не найден", await self.run_cmd(".plugin info ghost"))
        for bad in ("../evil", "a/b", "x.py", "имя", "a" * 65):
            self.assertIn("Имя плагина", await self.run_cmd(f".plugin load {bad}"), bad)

    async def test_usage(self):
        for text in (".plugin wat", ".plugin load", ".plugin load a b", ".plugin list x"):
            self.assertIn("Использование", await self.run_cmd(text), text)

    async def test_markdown_in_error_text_is_neutralised(self):
        self.fx.write("bad", source("bad", setup_tail='raise RuntimeError("**жирный** [x](y)")'))
        with self.assertLogs("candy", level="ERROR"):
            reply = await self.run_cmd(".plugin load bad")
        self.assertNotIn("**", reply)
        self.assertNotIn("](", reply)
        listing = await self.run_cmd(".plugin list")
        self.assertNotIn("**", listing)

    async def test_only_admin_can_use_it(self):
        self.fx.storage.permissions.grant(account_id=1, subject_id=7, permission="trusted", granted_by=1)
        self.fx.write("demo", source())
        self.assertIsNone(await self.run_cmd(".plugin load demo", sender=7, out=False))
        self.assertNotIn("demo", self.app.dispatcher.commands)
        self.assertIsNone(await self.run_cmd(".plugin load demo", sender=999, out=False))

    async def test_stop_unregisters(self):
        await self.module.stop()
        self.assertNotIn("plugin", self.app.dispatcher.commands)


if __name__ == "__main__":
    unittest.main()
