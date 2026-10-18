"""Этап 2: менеджер аккаунтов, миграции профиля, права файлов, AccountControl."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from accounts.account import Account
from accounts.backup import BackupManager
from accounts.control import AccountControl
from accounts.manager import AccountManager
from accounts.migration import CURRENT_VERSION, migrate_profile
from tests.helpers import make_account

POSIX = os.name == "posix"


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class MigrationTests(unittest.TestCase):
    def test_current_version_is_untouched(self):
        data = {"version": CURRENT_VERSION, "account_id": 1}
        result, changed = migrate_profile(data)
        self.assertFalse(changed)
        self.assertEqual(result, data)

    def test_profile_without_version_is_migrated(self):
        result, changed = migrate_profile(
            {"account_id": "42", "api_id": "7", "api_hash": " h ", "username": None}
        )
        self.assertTrue(changed)
        self.assertEqual(result["version"], CURRENT_VERSION)
        self.assertEqual((result["account_id"], result["api_id"]), (42, 7))
        self.assertEqual(result["api_hash"], "h")
        self.assertEqual(result["username"], "")
        self.assertEqual(result["session"], "session.session")

    def test_newer_version_is_refused(self):
        with self.assertRaisesRegex(ValueError, "новой версией"):
            migrate_profile({"version": CURRENT_VERSION + 1})

    def test_garbage_version_is_refused(self):
        for bad in ("abc", None, [], -1):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "некорректная"):
                migrate_profile({"version": bad})

    def test_non_object_is_refused(self):
        with self.assertRaises(ValueError):
            migrate_profile([1, 2])  # type: ignore[arg-type]

    def test_missing_migration_step_is_reported(self):
        with patch("accounts.migration.MIGRATIONS", {}):
            with self.assertRaisesRegex(ValueError, "нет миграции"):
                migrate_profile({"version": 0})

    def test_chain_of_steps_is_applied_in_order(self):
        steps = {
            0: lambda d: {**d, "version": 1, "trail": d.get("trail", []) + ["0>1"]},
            1: lambda d: {**d, "version": 2, "trail": d["trail"] + ["1>2"]},
        }
        with patch("accounts.migration.CURRENT_VERSION", 2), patch(
            "accounts.migration.MIGRATIONS", steps
        ):
            result, changed = migrate_profile({"version": 0})
        self.assertTrue(changed)
        self.assertEqual(result["trail"], ["0>1", "1>2"])
        self.assertEqual(result["version"], 2)


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "accounts"
        self.manager = AccountManager(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_reads_valid_accounts_and_active(self):
        make_account(self.root, 1, "alice")
        make_account(self.root, 2, "bob")
        (self.root / "active.json").write_text(json.dumps({"account_id": 2}), encoding="utf-8")
        self.manager.load()
        self.assertEqual({a.account_id for a in self.manager.list()}, {1, 2})
        self.assertEqual(self.manager.get_active().account_id, 2)

    def test_active_falls_back_to_first_account(self):
        make_account(self.root, 5, "eve")
        self.manager.load()
        self.assertEqual(self.manager.get_active().account_id, 5)

    def test_active_pointing_to_missing_account_falls_back(self):
        make_account(self.root, 1)
        (self.root / "active.json").write_text(json.dumps({"account_id": 99}), encoding="utf-8")
        self.manager.load()
        self.assertEqual(self.manager.get_active().account_id, 1)

    def test_broken_active_json_is_ignored(self):
        make_account(self.root, 1)
        (self.root / "active.json").write_text("{not json", encoding="utf-8")
        self.manager.load()
        self.assertEqual(self.manager.get_active().account_id, 1)

    def test_bad_accounts_are_skipped_but_good_ones_load(self):
        make_account(self.root, 1)
        make_account(self.root, 2, session=False)  # нет сессии
        broken = self.root / "3"
        broken.mkdir()
        (broken / "profile.json").write_text("{oops", encoding="utf-8")
        make_account(self.root, 4, profile={"version": CURRENT_VERSION + 5, "account_id": 4})
        make_account(
            self.root, 6, profile={"version": 1, "account_id": 6, "api_id": 0, "api_hash": ""}
        )
        with self.assertLogs("candy", level="ERROR") as logs:
            self.manager.load()
        self.assertEqual([a.account_id for a in self.manager.list()], [1])
        self.assertEqual(len(logs.records), 4)

    def test_old_profile_is_migrated_with_backup_copy(self):
        old = {"account_id": "7", "api_id": "99", "api_hash": "h", "username": "old"}
        directory = make_account(self.root, 7, "old", profile=old)
        self.manager.load()
        account = self.manager.get(7)
        self.assertEqual((account.account_id, account.api_id), (7, 99))
        on_disk = json.loads((directory / "profile.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["version"], CURRENT_VERSION)
        self.assertEqual(on_disk["api_id"], 99)
        saved_old = json.loads((directory / "profile.json.bak").read_text(encoding="utf-8"))
        self.assertEqual(saved_old, old)
        # второй запуск ничего не меняет
        before = (directory / "profile.json").read_text(encoding="utf-8")
        self.manager.load()
        self.assertEqual((directory / "profile.json").read_text(encoding="utf-8"), before)

    def test_add_saves_profile_and_sets_active(self):
        account = Account(10, 1, "h", "zed", "Zed", self.root / "10")
        self.manager.add(account)
        self.assertEqual(self.manager.get_active().account_id, 10)
        data = json.loads((self.root / "10" / "profile.json").read_text(encoding="utf-8"))
        self.assertEqual(data["account_id"], 10)
        self.assertEqual(data["version"], CURRENT_VERSION)
        self.assertEqual(list((self.root / "10").glob("*.tmp")), [])

    def test_add_duplicate_is_refused(self):
        account = Account(10, 1, "h", None, "", self.root / "10")
        self.manager.add(account)
        with self.assertRaises(ValueError):
            self.manager.add(account)

    @unittest.skipUnless(POSIX, "права POSIX")
    def test_secrets_get_private_permissions(self):
        directory = make_account(self.root, 1)
        for path in (directory / "profile.json", directory / "session.session"):
            path.chmod(0o644)
        directory.chmod(0o755)
        self.manager.load()
        self.assertEqual(mode(directory), 0o700)
        self.assertEqual(mode(directory / "profile.json"), 0o600)
        self.assertEqual(mode(directory / "session.session"), 0o600)

    @unittest.skipUnless(POSIX, "права POSIX")
    def test_saved_profile_and_active_file_are_private(self):
        account = Account(11, 1, "h", None, "", self.root / "11")
        self.manager.add(account)
        self.assertEqual(mode(self.root / "11" / "profile.json"), 0o600)
        self.assertEqual(mode(self.root / "active.json"), 0o600)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.manager = AccountManager(base / "accounts")
        self.control = AccountControl(self.manager, BackupManager(self.manager, base / "backups"))
        make_account(base / "accounts", 111, "Alice")
        make_account(base / "accounts", 222, "bob")
        make_account(base / "accounts", 333, None)
        self.manager.load()

    def tearDown(self):
        self.tmp.cleanup()

    def test_resolve_by_id_and_username(self):
        self.assertEqual(self.control.resolve("222").account_id, 222)
        self.assertEqual(self.control.resolve("@bob").account_id, 222)
        self.assertEqual(self.control.resolve("alice").account_id, 111)  # без учёта регистра
        self.assertEqual(self.control.resolve("  @ALICE ").account_id, 111)

    def test_resolve_errors(self):
        with self.assertRaises(ValueError):
            self.control.resolve("  ")
        with self.assertRaises(LookupError):
            self.control.resolve("999")
        with self.assertRaises(LookupError):
            self.control.resolve("@ghost")

    def test_describe_marks_active_account(self):
        self.manager.set_active(self.manager.get(222))
        lines = self.control.describe().splitlines()
        self.assertEqual(len(lines), 3)
        active = [line for line in lines if line.startswith("●")]
        self.assertEqual(len(active), 1)
        self.assertIn("@bob", active[0])
        self.assertIn("(активный)", active[0])
        self.assertTrue(any("333" in line and line.startswith("○") for line in lines))

    def test_describe_without_accounts(self):
        empty = AccountControl(
            AccountManager(Path(self.tmp.name) / "none"),
            BackupManager(self.manager, Path(self.tmp.name) / "b"),
        )
        self.assertEqual(empty.describe(), "Аккаунтов нет.")

    def test_backup_create_without_accounts(self):
        empty = AccountControl(
            AccountManager(Path(self.tmp.name) / "none"),
            BackupManager(self.manager, Path(self.tmp.name) / "b"),
        )
        with self.assertRaises(LookupError):
            empty.backup_create()


if __name__ == "__main__":
    unittest.main()
