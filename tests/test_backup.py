"""Этап 2: backup и restore аккаунтов."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from accounts.backup import BackupManager
from accounts.manager import AccountManager
from accounts.migration import CURRENT_VERSION
from tests.helpers import make_account, make_session, session_marker

POSIX = os.name == "posix"


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "accounts"
        self.backups_dir = self.base / "backups"
        self.manager = AccountManager(self.root)
        self.backups = BackupManager(self.manager, self.backups_dir)
        make_account(self.root, 1, "alice")
        self.manager.load()
        self.account = self.manager.get(1)

    def tearDown(self):
        self.tmp.cleanup()

    def make_zip(self, entries: dict[str, bytes | str]) -> Path:
        path = self.base / "custom.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        return path

    def valid_entries(self, **profile_overrides) -> dict[str, bytes]:
        profile = {
            "version": CURRENT_VERSION,
            "account_id": 5,
            "api_id": 1,
            "api_hash": "h",
            "username": "eve",
            "first_name": "Eve",
        }
        profile.update(profile_overrides)
        session = self.base / "tmp-session.session"
        session.unlink(missing_ok=True)
        make_session(session, "eve")
        return {"profile.json": json.dumps(profile).encode(), "session.session": session.read_bytes()}

    # ----------------------------------------------------------------- create

    def test_create_makes_complete_private_archive(self):
        path = self.backups.create(self.account)
        self.assertTrue(path.name.startswith("1-") and path.suffix == ".zip")
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(sorted(archive.namelist()), ["profile.json", "session.session"])
            self.assertIsNone(archive.testzip())
        self.assertEqual(list(self.backups_dir.glob("*.tmp")), [])
        if POSIX:
            self.assertEqual(mode(path), 0o600)
            self.assertEqual(mode(self.backups_dir), 0o700)

    def test_session_in_archive_is_a_consistent_sqlite_snapshot(self):
        path = self.backups.create(self.account)
        out = self.base / "extracted"
        with zipfile.ZipFile(path) as archive:
            archive.extract("session.session", out)
        self.assertEqual(session_marker(out / "session.session"), "acc1")

    def test_snapshot_works_while_session_is_open_and_written(self):
        writer = sqlite3.connect(self.account.session_path)
        try:
            writer.execute("INSERT INTO sessions VALUES (2, 'during')")  # незакоммичено
            path = self.backups.create(self.account)
        finally:
            writer.rollback()
            writer.close()
        out = self.base / "extracted"
        with zipfile.ZipFile(path) as archive:
            archive.extract("session.session", out)
        check = sqlite3.connect(out / "session.session")
        try:
            self.assertEqual(check.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(check.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1)
        finally:
            check.close()

    def test_non_sqlite_session_is_copied_as_is(self):
        self.account.session_path.write_bytes(b"definitely not sqlite")
        with self.assertLogs("candy", level="WARNING"):
            path = self.backups.create(self.account)
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(archive.read("session.session"), b"definitely not sqlite")

    def test_create_requires_both_files(self):
        self.account.session_path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.backups.create(self.account)

    def test_list_is_sorted_and_empty_when_no_directory(self):
        self.assertEqual(self.backups.list(), [])
        first = self.backups.create(self.account)
        (self.backups_dir / "0-old.zip").write_bytes(b"")
        (self.backups_dir / "notes.txt").write_text("x")
        self.assertEqual([p.name for p in self.backups.list()], ["0-old.zip", first.name])

    # ---------------------------------------------------------------- restore

    def test_roundtrip_into_empty_installation(self):
        path = self.backups.create(self.account)
        other_root = self.base / "other-accounts"
        other = BackupManager(AccountManager(other_root), self.backups_dir)
        restored = other.restore(path)
        self.assertEqual((restored.account_id, restored.username, restored.api_id), (1, "alice", 12345))
        self.assertEqual(session_marker(restored.session_path), "acc1")
        if POSIX:
            self.assertEqual(mode(restored.session_path), 0o600)
            self.assertEqual(mode(restored.profile_path), 0o600)
            self.assertEqual(mode(restored.account_dir), 0o700)

    def test_restore_by_name_from_backups_dir(self):
        path = self.backups.create(self.account)
        other = BackupManager(AccountManager(self.base / "other"), self.backups_dir)
        self.assertEqual(other.restore(path.name).account_id, 1)

    def test_restore_over_existing_account_is_refused_and_keeps_it(self):
        path = self.backups.create(self.account)
        before = self.account.session_path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.backups.restore(path)
        self.assertEqual(self.account.session_path.read_bytes(), before)

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            self.backups.restore("nope.zip")

    def test_not_a_zip(self):
        bad = self.base / "bad.zip"
        bad.write_bytes(b"this is not a zip")
        with self.assertRaisesRegex(ValueError, "ZIP"):
            self.backups.restore(bad)

    def test_path_traversal_is_rejected(self):
        entries = self.valid_entries()
        entries["../evil.txt"] = b"pwn"
        with self.assertRaisesRegex(ValueError, "опасный путь"):
            self.backups.restore(self.make_zip(entries))
        self.assertFalse((self.base / "evil.txt").exists())

    def test_absolute_path_is_rejected(self):
        entries = self.valid_entries()
        entries["/tmp/evil.txt"] = b"pwn"
        with self.assertRaises(ValueError):
            self.backups.restore(self.make_zip(entries))

    def test_unknown_files_are_rejected(self):
        entries = self.valid_entries()
        entries["extra.txt"] = b"x"
        with self.assertRaisesRegex(ValueError, "неизвестные"):
            self.backups.restore(self.make_zip(entries))

    def test_incomplete_archive_is_rejected(self):
        entries = self.valid_entries()
        del entries["session.session"]
        with self.assertRaisesRegex(ValueError, "неполный"):
            self.backups.restore(self.make_zip(entries))

    def test_duplicate_entries_are_rejected(self):
        path = self.base / "dup.zip"
        entries = self.valid_entries()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("profile.json", entries["profile.json"])
                archive.writestr("session.session", entries["session.session"])
                archive.writestr("session.session", b"second")
        with self.assertRaisesRegex(ValueError, "повторяющиеся"):
            self.backups.restore(path)

    def test_oversized_session_is_rejected_before_extracting(self):
        self.backups.MAX_SESSION_BYTES = 10
        with self.assertRaisesRegex(ValueError, "слишком большой"):
            self.backups.restore(self.make_zip(self.valid_entries()))
        self.assertFalse((self.root / "5").exists())

    def test_oversized_profile_is_rejected(self):
        self.backups.MAX_PROFILE_BYTES = 10
        with self.assertRaisesRegex(ValueError, "слишком большой"):
            self.backups.restore(self.make_zip(self.valid_entries()))

    def test_copy_limit_holds_even_if_header_lies(self):
        out = io.BytesIO()
        with self.assertRaisesRegex(ValueError, "слишком большой"):
            BackupManager._copy_limited(io.BytesIO(b"x" * 200_000), out, 100_000, "session.session")

    def test_newer_profile_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "новой версией"):
            self.backups.restore(self.make_zip(self.valid_entries(version=CURRENT_VERSION + 1)))

    def test_corrupt_profile_is_rejected(self):
        entries = self.valid_entries()
        entries["profile.json"] = b"{broken"
        with self.assertRaisesRegex(ValueError, "повреждён"):
            self.backups.restore(self.make_zip(entries))

    def test_missing_api_credentials_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "API"):
            self.backups.restore(self.make_zip(self.valid_entries(api_hash="  ")))

    def test_profile_without_ids_is_rejected(self):
        entries = self.valid_entries()
        entries["profile.json"] = json.dumps({"version": CURRENT_VERSION, "api_hash": "h"}).encode()
        with self.assertRaisesRegex(ValueError, "account_id"):
            self.backups.restore(self.make_zip(entries))

    def test_old_profile_format_is_migrated_on_restore(self):
        entries = self.valid_entries()
        entries["profile.json"] = json.dumps(
            {"account_id": "5", "api_id": "1", "api_hash": "h", "username": "eve"}
        ).encode()
        account = self.backups.restore(self.make_zip(entries))
        self.assertEqual(account.account_id, 5)
        saved = json.loads(account.profile_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["version"], CURRENT_VERSION)

    def test_failed_restore_leaves_no_partial_account(self):
        archive = self.make_zip(self.valid_entries())
        with patch("accounts.backup.shutil.copy2", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.backups.restore(archive)
        self.assertFalse((self.root / "5").exists())
        self.manager.load()
        self.assertIsNone(self.manager.get(5))


if __name__ == "__main__":
    unittest.main()
