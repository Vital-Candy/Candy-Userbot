"""Этап 2: команды .account и .backup, переключение аккаунта, консольные команды."""
from __future__ import annotations

import asyncio
import io
import contextlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from accounts.backup import BackupManager
from accounts.control import AccountControl
from accounts.manager import AccountManager
from core.console import ConsoleManager
from core.dispatcher import Dispatcher
from modules.system.accounts import AccountsModule
from modules.system.backup import BackupModule
from tests.helpers import make_account

try:
    from core.app import UserbotApp
except ImportError:  # Telethon не установлен
    UserbotApp = None


class Fixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "accounts"
        make_account(self.root, 1, "alice")
        make_account(self.root, 2, "bob")
        self.manager = AccountManager(self.root)
        self.manager.load()
        self.backups = BackupManager(self.manager, self.base / "backups")
        self.control = AccountControl(self.manager, self.backups)
        self.app = SimpleNamespace(
            dispatcher=Dispatcher(),
            account_control=self.control,
            account=self.manager.get(1),
            switch_account=AsyncMock(),
        )

    async def run(self, text: str) -> str:
        edits: list[str] = []

        async def edit(value):
            edits.append(value)

        event = SimpleNamespace(raw_text=text, edit=edit)
        await self.app.dispatcher.dispatch_command(event)
        return edits[-1]

    def close(self):
        self.tmp.cleanup()


class AccountCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx = Fixture()
        self.module = AccountsModule(self.fx.app)
        await self.module.start()

    async def asyncTearDown(self):
        self.fx.close()

    async def test_list_is_default_and_marks_active(self):
        for text in (".account", ".account list"):
            reply = await self.fx.run(text)
            self.assertIn("@alice", reply)
            self.assertIn("@bob", reply)
            self.assertIn("(активный)", reply)

    async def test_use_other_account_announces_and_switches(self):
        reply = await self.fx.run(".account use bob")
        self.assertIn("Переключаюсь на @bob", reply)
        self.fx.app.switch_account.assert_awaited_once_with("bob")

    async def test_use_by_id(self):
        await self.fx.run(".account use 2")
        self.fx.app.switch_account.assert_awaited_once_with("2")

    async def test_use_current_account_does_nothing(self):
        reply = await self.fx.run(".account use @alice")
        self.assertIn("уже активен", reply)
        self.fx.app.switch_account.assert_not_awaited()

    async def test_use_unknown_account(self):
        reply = await self.fx.run(".account use ghost")
        self.assertTrue(reply.startswith("❌"))
        self.assertIn("ghost", reply)
        self.fx.app.switch_account.assert_not_awaited()

    async def test_bad_usage(self):
        for text in (".account use", ".account use a b", ".account remove 1"):
            self.assertIn("Использование", await self.fx.run(text))
        self.fx.app.switch_account.assert_not_awaited()

    async def test_failure_of_switch_is_reported(self):
        self.fx.app.switch_account.side_effect = ValueError("что-то пошло не так")
        reply = await self.fx.run(".account use bob")
        self.assertIn("❌ что-то пошло не так", reply)

    async def test_stop_unregisters_command(self):
        await self.module.stop()
        self.assertNotIn("account", self.fx.app.dispatcher.commands)


class BackupCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx = Fixture()
        self.module = BackupModule(self.fx.app)
        await self.module.start()

    async def asyncTearDown(self):
        self.fx.close()

    async def test_create_list_restore_cycle(self):
        self.assertIn("пока нет", await self.fx.run(".backup list"))

        reply = await self.fx.run(".backup create")
        self.assertIn("Backup создан", reply)
        self.assertIn("в секрете", reply)
        name = self.fx.backups.list()[0].name
        self.assertIn(name, reply)
        self.assertIn(name, await self.fx.run(".backup list"))

        # аккаунта нет — значит, restore его вернёт
        shutil.rmtree(self.fx.root / "1")
        self.fx.manager.load()
        reply = await self.fx.run(f".backup restore {name}")
        self.assertIn("восстановлен", reply)
        self.assertIn(".account use 1", reply)
        self.assertIsNotNone(self.fx.manager.get(1))

    async def test_create_for_other_account_by_name(self):
        await self.fx.run(".backup create @bob")
        self.assertTrue(self.fx.backups.list()[0].name.startswith("2-"))

    async def test_create_for_unknown_account(self):
        reply = await self.fx.run(".backup create @ghost")
        self.assertTrue(reply.startswith("❌"))
        self.assertEqual(self.fx.backups.list(), [])

    async def test_restore_existing_account_is_refused(self):
        await self.fx.run(".backup create")
        name = self.fx.backups.list()[0].name
        reply = await self.fx.run(f".backup restore {name}")
        self.assertTrue(reply.startswith("❌"))
        self.assertIn("уже существует", reply)

    async def test_restore_missing_file(self):
        self.assertIn("не найден", await self.fx.run(".backup restore nope.zip"))

    async def test_restore_broken_archive(self):
        bad = self.fx.base / "backups"
        bad.mkdir(exist_ok=True)
        (bad / "bad.zip").write_bytes(b"not a zip")
        self.assertTrue((await self.fx.run(".backup restore bad.zip")).startswith("❌"))

    async def test_bad_usage(self):
        for text in (".backup", ".backup create a b", ".backup restore", ".backup list x", ".backup wipe"):
            self.assertIn("Использование", await self.fx.run(text))

    async def test_stop_unregisters_command(self):
        await self.module.stop()
        self.assertNotIn("backup", self.fx.app.dispatcher.commands)


class ConsoleAccountTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx = Fixture()
        self.console = ConsoleManager(self.fx.app)

    async def asyncTearDown(self):
        self.fx.close()

    async def execute(self, line: str) -> str:
        with contextlib.redirect_stdout(io.StringIO()):
            return await self.console.execute(line)

    async def test_account_list_and_use(self):
        self.assertIn("@bob", await self.execute("account list"))
        self.assertIn("@bob", await self.execute("account"))
        self.assertIn("Переключение", await self.execute("account use bob"))
        self.fx.app.switch_account.assert_awaited_once_with("bob")

    async def test_account_use_errors_are_reported_not_raised(self):
        self.fx.app.switch_account.side_effect = LookupError("аккаунт «x» не найден")
        self.assertIn("не найден", await self.execute("account use x"))
        self.assertIn("Использование", await self.execute("account use"))

    async def test_backup_commands(self):
        self.assertIn("Backup-ов нет", await self.execute("backup list"))
        self.assertIn("Backup создан", await self.execute("backup create"))
        self.assertEqual(len(self.fx.backups.list()), 1)
        name = self.fx.backups.list()[0].name
        self.assertIn(name, await self.execute("backup list"))
        self.assertIn("уже существует", await self.execute(f"backup restore {name}"))
        self.assertIn("не найден", await self.execute("backup restore missing.zip"))
        self.assertIn("Использование", await self.execute("backup"))

    async def test_help_mentions_new_commands(self):
        text = await self.execute("help")
        for word in ("account list", "backup create", "backup restore"):
            self.assertIn(word, text)


@unittest.skipIf(UserbotApp is None, "Telethon не установлен")
class AppSwitchTests(unittest.IsolatedAsyncioTestCase):
    def make_app(self, base: Path):
        with patch("core.app.ensure_directories"), patch(
            "core.app.ACCOUNTS_DIR", base / "accounts"
        ), patch("core.app.DATABASE_PATH", base / "db" / "candy.sqlite3"):
            return UserbotApp()

    async def test_switch_sets_active_and_requests_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_account(base / "accounts", 1, "alice")
            make_account(base / "accounts", 2, "bob")
            app = self.make_app(base)
            app.accounts.load()
            app.account = app.accounts.get(1)
            app.stop = AsyncMock()

            account = await app.switch_account("@bob")

            self.assertEqual(account.account_id, 2)
            active = json.loads((base / "accounts" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(active["account_id"], 2)
            self.assertTrue(app.restart_requested)
            app.stop.assert_awaited_once()

    async def test_switch_to_current_or_unknown_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_account(base / "accounts", 1, "alice")
            app = self.make_app(base)
            app.accounts.load()
            app.account = app.accounts.get(1)
            app.stop = AsyncMock()

            with self.assertRaises(ValueError):
                await app.switch_account("alice")
            with self.assertRaises(LookupError):
                await app.switch_account("ghost")

            self.assertFalse(app.restart_requested)
            app.stop.assert_not_awaited()
            self.assertFalse((base / "accounts" / "active.json").exists())

    async def test_failing_task_notifies_owner_only_while_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(Path(tmp))
            app.client = SimpleNamespace()
            app.notify_owner = AsyncMock(return_value=True)
            item = SimpleNamespace(name="sync", consecutive_failures=3, last_error="ValueError: boom")

            app._task_failing(item)  # приложение ещё не работает: молчим
            await asyncio.sleep(0)
            app.notify_owner.assert_not_awaited()

            app.lifecycle.move("starting")
            app.lifecycle.move("running")
            app._task_failing(item)
            await asyncio.sleep(0)
            app.notify_owner.assert_awaited_once()
            text = app.notify_owner.await_args.args[0]
            self.assertIn("sync", text)
            self.assertIn("boom", text)
            await asyncio.sleep(0)  # done-callback срабатывает на следующем шаге цикла
            self.assertEqual(app._notify_tasks, set())  # завершённая задача убирается из набора

    async def test_cli_restore_makes_first_account_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_account(base / "src", 5, "eve")
            source_manager = AccountManager(base / "src")
            source_manager.load()
            archive = BackupManager(source_manager, base / "backups").create(source_manager.get(5))

            app = self.make_app(base)
            app.backups.backups_dir = base / "backups"
            with contextlib.redirect_stdout(io.StringIO()):
                await app.cli_restore(str(archive))
            self.assertEqual(app.accounts.get_active().account_id, 5)

    async def test_cli_add_account_refusal_is_a_user_error(self):
        from core.errors import UserError

        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(Path(tmp))
            app.onboard_account = AsyncMock(side_effect=FileExistsError("аккаунт 1 уже существует"))
            with self.assertRaises(UserError):
                await app.cli_add_account()
            app.onboard_account.assert_awaited_once_with(confirm_replace=True)


if __name__ == "__main__":
    unittest.main()
