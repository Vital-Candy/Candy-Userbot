"""Регрессионные тесты на исправленные баги (Alpha 0.6.1)."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from core.background import BackgroundManager
from core.console import ConsoleManager
from core.dispatcher import Dispatcher
from core.modules import ModuleManager
from core.plugins import PluginManager
from modules.storage.labels import LabelsModule
from modules.system.heartbeat import HeartbeatModule
from storage.service import Storage

try:
    from core.app import UserbotApp
except ImportError:  # Telethon не установлен
    UserbotApp = None


class BackgroundRemoveTests(unittest.IsolatedAsyncioTestCase):
    async def test_remove_after_stop(self):
        manager = BackgroundManager()
        manager.register("job", lambda: None, interval=0.01)
        await manager.start("job")
        await manager.stop("job")
        manager.remove("job")
        self.assertEqual(manager.list(), [])
        manager.register("job", lambda: None, interval=0.01)  # имя снова свободно

    async def test_remove_never_started(self):
        manager = BackgroundManager()
        manager.register("job", lambda: None, interval=0.01)
        manager.remove("job")
        self.assertEqual(manager.list(), [])

    async def test_remove_running_task_is_refused(self):
        manager = BackgroundManager()
        manager.register("job", lambda: None, interval=0.01)
        await manager.start("job")
        with self.assertRaises(RuntimeError):
            manager.remove("job")
        await manager.stop_all()

    async def test_remove_unknown_is_noop(self):
        BackgroundManager().remove("nope")

    async def test_heartbeat_module_stops_cleanly(self):
        app = SimpleNamespace(background=BackgroundManager())
        manager = ModuleManager(app)
        manager.register(HeartbeatModule(app))
        await manager.start_all()
        self.assertTrue(manager.states()[0].started)
        await manager.stop_all()
        self.assertFalse(manager.states()[0].started)
        self.assertEqual(app.background.list(), [])


class ConsoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_command_from_console_does_not_deadlock(self):
        app = SimpleNamespace(plugins=None, modules=None)
        console = ConsoleManager(app)

        async def stop():
            await console.stop()  # так делает UserbotApp.stop()

        app.stop = stop
        task = asyncio.create_task(console.execute("stop"))
        console._task = task
        await asyncio.wait_for(task, timeout=1)
        self.assertTrue(console._stopping)

    async def test_console_disabled_without_tty(self):
        console = ConsoleManager(SimpleNamespace())
        with patch("sys.stdin", SimpleNamespace(isatty=lambda: False)):
            await console.start()
        self.assertIsNone(console._task)
        self.assertIsNone(console._thread)


PLUGIN_TEMPLATE = """\
from __future__ import annotations
from dataclasses import dataclass
from core.plugin import Plugin

@dataclass
class Settings:
    greeting: str = "{greeting}"

class Demo(Plugin):
    name = "demo"
    async def setup(self):
        self.app.registered.add("demo")
        self.app.greeting = Settings().greeting
        {fail}
    async def teardown(self):
        self.app.registered.discard("demo")

def create_plugin(app):
    return Demo(app)
"""


def plugin_source(greeting="hello", fail=False):
    return PLUGIN_TEMPLATE.format(
        greeting=greeting, fail='raise RuntimeError("boom")' if fail else "pass"
    )


class PluginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = SimpleNamespace(registered=set(), greeting=None)
        self.manager = PluginManager(self.app, self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, source):
        (self.root / "demo.py").write_text(source, encoding="utf-8")

    async def test_dataclass_plugin_with_future_annotations_loads(self):
        self.write(plugin_source())
        await self.manager.load_all()
        self.assertTrue(self.manager.states()[0].loaded)
        self.assertEqual(self.app.greeting, "hello")

    async def test_failed_setup_runs_teardown_and_allows_reload(self):
        self.write(plugin_source(fail=True))
        await self.manager.load_all()
        state = self.manager.states()[0]
        self.assertFalse(state.loaded)
        self.assertTrue(state.failed)
        self.assertEqual(self.app.registered, set())  # teardown прибрал за setup

        self.write(plugin_source(greeting="fixed-version"))
        self.assertTrue(await self.manager.reload("demo"))
        self.assertEqual(self.app.greeting, "fixed-version")
        self.assertEqual(self.app.registered, {"demo"})

    async def test_load_picks_up_file_added_after_start(self):
        await self.manager.load_all()
        self.assertEqual(self.manager.states(), [])
        self.write(plugin_source())
        self.assertTrue(await self.manager.load("demo"))
        self.assertEqual(self.app.registered, {"demo"})

    async def test_load_unknown_plugin_raises_keyerror(self):
        with self.assertRaises(KeyError):
            await self.manager.load("missing")

    async def test_failing_teardown_does_not_block_reload(self):
        self.write(plugin_source().replace("discard", "remove_nothing"))
        await self.manager.load_all()
        self.assertFalse(await self.manager.unload("demo"))
        self.assertFalse(self.manager.states()[0].loaded)
        self.write(plugin_source(greeting="second"))
        self.assertTrue(await self.manager.reload("demo"))
        self.assertEqual(self.app.greeting, "second")


class FakeLabelEvent:
    def __init__(self, text, *, chat_id=100, reply=True):
        self.raw_text = text
        self.chat_id = chat_id
        self._reply = SimpleNamespace(id=7) if reply else None
        self.edits: list[str] = []

    async def get_reply_message(self):
        return self._reply

    async def edit(self, text):
        self.edits.append(text)


class LabelCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        storage = Storage(Path(self.tmp.name) / "t.sqlite3")
        storage.open()
        self.app = SimpleNamespace(
            dispatcher=Dispatcher(),
            storage=storage,
            identity=SimpleNamespace(account_id=AsyncMock(return_value=1)),
        )
        self.module = LabelsModule(self.app)
        await self.module.start()

    async def asyncTearDown(self):
        self.app.storage.close()
        self.tmp.cleanup()

    async def run_command(self, text, **kwargs):
        event = FakeLabelEvent(text, **kwargs)
        await self.app.dispatcher.dispatch_command(event)
        return event.edits[-1]

    async def test_label_created(self):
        self.assertIn("установлена", await self.run_command(".label todo"))

    async def test_duplicate_label_gives_user_feedback(self):
        await self.run_command(".label todo")
        reply = await self.run_command(".label TODO")
        self.assertIn("уже", reply)

    async def test_too_long_name_gives_user_feedback(self):
        reply = await self.run_command(".label " + "x" * 65)
        self.assertTrue(reply.startswith("❌"))

    async def test_missing_chat_id(self):
        self.assertIn("чат", await self.run_command(".label todo", chat_id=None))
        self.assertIn("чат", await self.run_command(".labels", chat_id=None))
        self.assertIn("чат", await self.run_command(".unlabel todo", chat_id=None))

    async def test_unlabel_too_long_name(self):
        reply = await self.run_command(".unlabel " + "x" * 65)
        self.assertTrue(reply.startswith("❌"))


class FakeClient:
    def __init__(self, authorized=False, connected=False):
        self.authorized = authorized
        self.connected = connected
        self.connect_called = False
        self.start_called = False
        self.disconnect = AsyncMock(side_effect=self._disconnect)

    async def connect(self):
        self.connect_called = True
        self.connected = True

    async def start(self):
        self.start_called = True

    async def is_user_authorized(self):
        return self.authorized

    def is_connected(self):
        return self.connected

    async def _disconnect(self):
        self.connected = False


@unittest.skipIf(UserbotApp is None, "Telethon не установлен")
class AppLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def make_app(self, tmp):
        base = Path(tmp)
        with patch("core.app.ensure_directories"), patch(
            "core.app.ACCOUNTS_DIR", base / "accounts"
        ), patch("core.app.DATABASE_PATH", base / "db" / "candy.sqlite3"):
            return UserbotApp()

    async def test_invalid_session_does_not_call_interactive_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp)
            app._ensure_account = AsyncMock(return_value=SimpleNamespace(display_name="x"))
            client = FakeClient(authorized=False)
            with patch("core.app.create_client", return_value=client):
                with self.assertRaises(RuntimeError):
                    await app.start()
            self.assertTrue(client.connect_called)
            self.assertFalse(client.start_called)
            client.disconnect.assert_awaited()  # rollback отключил клиента

    async def test_stop_continues_after_step_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp)
            app.console.stop = AsyncMock(side_effect=RuntimeError("console"))
            app.plugins.unload_all = AsyncMock(side_effect=RuntimeError("plugins"))
            app.modules.stop_all = AsyncMock(side_effect=RuntimeError("modules"))
            app.background.stop_all = AsyncMock(side_effect=RuntimeError("background"))
            app.storage = MagicMock()
            client = FakeClient(authorized=True, connected=True)
            app.client = client

            await app.stop()

            client.disconnect.assert_awaited_once()
            app.storage.close.assert_called_once()
            await app.stop()  # повторный вызов безопасен
            client.disconnect.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
