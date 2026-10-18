"""Дополнительные тесты стабильности: консоль в потоке, stop(), метки, плагины, клиент."""
from __future__ import annotations

import asyncio
import contextlib
import io
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from core.console import ConsoleManager
from core.dispatcher import Dispatcher
from core.plugins import PluginManager
from modules.storage.labels import LabelsModule
from storage.service import Storage

try:
    from core.app import UserbotApp
except ImportError:  # Telethon не установлен
    UserbotApp = None


class ConsoleThreadTests(unittest.IsolatedAsyncioTestCase):
    async def test_line_is_executed_and_stop_does_not_wait_for_enter(self):
        release = threading.Event()
        calls = 0

        def fake_input(_prompt=""):
            nonlocal calls
            calls += 1
            if calls == 1:
                return "status"
            release.wait(5)  # имитируем ожидание Enter
            raise EOFError

        app = SimpleNamespace(
            modules=SimpleNamespace(states=lambda: []),
            plugins=SimpleNamespace(states=lambda: []),
            health=lambda: SimpleNamespace(lines=lambda: ["HEALTH-OK"]),
        )
        console = ConsoleManager(app, ui="console")
        out = io.StringIO()
        try:
            with patch("sys.stdin", SimpleNamespace(isatty=lambda: True)), patch(
                "builtins.input", fake_input
            ), contextlib.redirect_stdout(out):
                await console.start()
                for _ in range(100):
                    if "HEALTH-OK" in out.getvalue():
                        break
                    await asyncio.sleep(0.01)
                started = time.monotonic()
                await asyncio.wait_for(console.stop(), timeout=1)
                self.assertLess(time.monotonic() - started, 1)
            self.assertIn("HEALTH-OK", out.getvalue())
            self.assertIsNone(console._task)
        finally:
            release.set()

    async def test_eof_ends_console_task(self):
        def fake_input(_prompt=""):
            raise EOFError

        console = ConsoleManager(SimpleNamespace())
        with patch("sys.stdin", SimpleNamespace(isatty=lambda: True)), patch(
            "builtins.input", fake_input
        ):
            await console.start()
            await asyncio.wait_for(console._task, timeout=1)
        await console.stop()


class LabelFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        storage = Storage(Path(self.tmp.name) / "t.sqlite3")
        storage.open()
        self.app = SimpleNamespace(
            dispatcher=Dispatcher(),
            storage=storage,
            identity=SimpleNamespace(account_id=AsyncMock(return_value=1)),
        )
        await LabelsModule(self.app).start()

    async def asyncTearDown(self):
        self.app.storage.close()
        self.tmp.cleanup()

    async def run_command(self, text, chat_id=100):
        edits: list[str] = []

        async def edit(value):
            edits.append(value)

        event = SimpleNamespace(
            raw_text=text,
            chat_id=chat_id,
            get_reply_message=AsyncMock(return_value=SimpleNamespace(id=7)),
            edit=edit,
        )
        await self.app.dispatcher.dispatch_command(event)
        return edits[-1]

    async def test_label_list_and_unlabel_roundtrip(self):
        await self.run_command(".label todo")
        self.assertIn("todo", await self.run_command(".labels"))
        self.assertIn("удалена", await self.run_command(".unlabel todo"))
        self.assertIn("нет меток", await self.run_command(".labels"))
        self.assertIn("не найдена", await self.run_command(".unlabel todo"))

    async def test_name_with_spaces_is_not_accepted(self):
        self.assertIn("Использование", await self.run_command(".label two words"))


class PluginSysModulesTests(unittest.IsolatedAsyncioTestCase):
    async def test_module_removed_from_sys_modules_on_unload_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.py").write_text(
                "from core.plugin import Plugin\n"
                "class P(Plugin):\n"
                "    async def setup(self): pass\n"
                "def create_plugin(app): return P(app)\n",
                encoding="utf-8",
            )
            (root / "broken.py").write_text("raise RuntimeError('import boom')\n", encoding="utf-8")
            manager = PluginManager(SimpleNamespace(), root)
            await manager.load_all()

            self.assertIn("candy_plugin_ok", sys.modules)
            self.assertNotIn("candy_plugin_broken", sys.modules)
            states = {s.name: s for s in manager.states()}
            self.assertTrue(states["ok"].loaded)
            self.assertTrue(states["broken"].failed)

            self.assertTrue(await manager.unload("ok"))
            self.assertNotIn("candy_plugin_ok", sys.modules)


class ClientFactoryTests(unittest.TestCase):
    @unittest.skipIf(UserbotApp is None, "Telethon не установлен")
    def test_client_survives_network_drops(self):
        from core.client import create_client

        account = SimpleNamespace(session_path=Path("s.session"), api_id=1, api_hash="h")
        with patch("core.client.TelegramClient") as factory:
            create_client(account)
        kwargs = factory.call_args.kwargs
        self.assertEqual(kwargs["connection_retries"], -1)
        self.assertTrue(kwargs["auto_reconnect"])


@unittest.skipIf(UserbotApp is None, "Telethon не установлен")
class ConcurrentStopTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_stop_calls_run_shutdown_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with patch("core.app.ensure_directories"), patch(
                "core.app.ACCOUNTS_DIR", base / "accounts"
            ), patch("core.app.DATABASE_PATH", base / "db" / "candy.sqlite3"):
                app = UserbotApp()
            gate = asyncio.Event()

            async def slow_unload():
                await gate.wait()

            app.plugins.unload_all = AsyncMock(side_effect=slow_unload)
            app.storage = MagicMock()
            client = MagicMock()
            client.is_connected.return_value = True
            client.disconnect = AsyncMock()
            app.client = client

            first = asyncio.create_task(app.stop())
            second = asyncio.create_task(app.stop())
            await asyncio.sleep(0.05)
            self.assertFalse(first.done() or second.done())  # оба ждут одну остановку
            gate.set()
            await asyncio.wait_for(asyncio.gather(first, second), timeout=1)

            app.plugins.unload_all.assert_awaited_once()
            client.disconnect.assert_awaited_once()
            app.storage.close.assert_called_once()

    async def test_cancelling_caller_does_not_abort_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with patch("core.app.ensure_directories"), patch(
                "core.app.ACCOUNTS_DIR", base / "accounts"
            ), patch("core.app.DATABASE_PATH", base / "db" / "candy.sqlite3"):
                app = UserbotApp()
            gate = asyncio.Event()

            async def slow_unload():
                await gate.wait()

            app.plugins.unload_all = AsyncMock(side_effect=slow_unload)
            app.storage = MagicMock()
            app.client = None

            caller = asyncio.create_task(app.stop())
            await asyncio.sleep(0.05)
            caller.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await caller
            gate.set()
            await asyncio.wait_for(asyncio.shield(app._stop_task), timeout=1)
            app.storage.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
