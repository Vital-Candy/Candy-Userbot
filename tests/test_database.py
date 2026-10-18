"""Этап 5: версия базы, SQL-миграции, транзакции."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path

from core.errors import UserError
from storage.database import (
    MIGRATIONS_DIR,
    Database,
    DatabaseError,
    load_migrations,
    split_statements,
)

POSIX = os.name == "posix"

INIT = "CREATE TABLE one (id INTEGER PRIMARY KEY, note TEXT);\nINSERT INTO one(note) VALUES ('v1');\n"
SECOND = "CREATE TABLE two (id INTEGER PRIMARY KEY);\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.path = self.base / "db" / "test.sqlite3"
        self.opened: list[Database] = []

    def tearDown(self):
        for db in self.opened:
            db.close()
        self.tmp.cleanup()

    def migrations(self, **files: str) -> Path:
        directory = self.base / f"mig{len(list(self.base.glob('mig*')))}"
        directory.mkdir()
        for name, sql in files.items():
            (directory / f"{name}.sql").write_text(sql, encoding="utf-8")
        return directory

    def open(self, directory: Path | None = None) -> Database:
        db = Database(self.path, directory)
        self.opened.append(db)
        db.open()
        return db

    def tables(self, db: Database) -> set[str]:
        rows = db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        return {row["name"] for row in rows}

    def digest(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


class FreshDatabaseTests(Base):
    def test_empty_database_gets_real_schema(self):
        with self.assertLogs("candy", level="INFO"):
            db = self.open()
        self.assertTrue({"labels", "permissions", "metadata"} <= self.tables(db))
        self.assertEqual(db.version, load_migrations(MIGRATIONS_DIR)[-1].version)
        value = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
        self.assertEqual(int(value), db.version)
        self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_reopen_is_idempotent_and_keeps_data(self):
        with self.assertLogs("candy", level="INFO"):
            db = self.open()
        db.execute(
            "INSERT INTO labels(account_id, chat_id, message_id, name, created_at) "
            "VALUES(1, 2, 3, 'x', 'now')"
        )
        db.close()
        db = self.open()  # без миграций: лог не ожидается
        self.assertEqual(db.execute("SELECT COUNT(*) FROM labels").fetchone()[0], 1)
        self.assertEqual(list(self.path.parent.glob("*.bak")), [])

    def test_open_twice_and_close_twice_are_safe(self):
        with self.assertLogs("candy", level="INFO"):
            db = self.open()
        db.open()
        self.assertTrue(db.is_open)
        db.close()
        db.close()
        self.assertFalse(db.is_open)
        with self.assertRaises(RuntimeError):
            db.execute("SELECT 1")

    def test_database_written_by_previous_release_is_accepted(self):
        # Так выглядела база до появления файловых миграций: версия 1 в metadata.
        self.path.parent.mkdir(parents=True)
        raw = sqlite3.connect(self.path)
        raw.executescript((MIGRATIONS_DIR / "001_init.sql").read_text(encoding="utf-8"))
        raw.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        raw.execute("INSERT INTO metadata VALUES('schema_version', '1')")
        raw.execute(
            "INSERT INTO labels(account_id, chat_id, message_id, name, created_at) "
            "VALUES(1, 2, 3, 'old', 'now')"
        )
        raw.commit()
        raw.close()
        db = self.open()
        self.assertEqual(db.execute("SELECT name FROM labels").fetchone()[0], "old")


class NewerDatabaseTests(Base):
    def make_future_db(self, version="99"):
        with self.assertLogs("candy", level="INFO"):
            db = self.open()
        db.execute("UPDATE metadata SET value = ? WHERE key = 'schema_version'", (version,))
        db.close()

    def test_newer_database_is_rejected_with_clear_user_error(self):
        self.make_future_db()
        db = Database(self.path)
        with self.assertRaises(DatabaseError) as ctx:
            db.open()
        self.assertIsInstance(ctx.exception, UserError)
        text = str(ctx.exception)
        self.assertIn("более новой версией", text)
        self.assertIn("99", text)
        self.assertFalse(db.is_open)

    def test_version_check_happens_before_any_migration(self):
        directory = self.migrations(**{"001_init": INIT, "002_more": SECOND})
        with self.assertLogs("candy", level="INFO"):
            db = self.open(directory)
        db.execute("UPDATE metadata SET value = '5' WHERE key = 'schema_version'")
        db.close()
        with self.assertRaises(DatabaseError):
            self.open(directory)
        reopened = sqlite3.connect(self.path)
        try:
            self.assertEqual(
                reopened.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],
                "5",
            )
        finally:
            reopened.close()
        self.assertEqual(list(self.path.parent.glob("*.bak")), [])

    def test_newer_database_file_is_not_modified(self):
        self.make_future_db()
        for suffix in ("-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)
        before = self.digest()
        with self.assertRaises(DatabaseError):
            Database(self.path).open()
        self.assertEqual(self.digest(), before)

    def test_garbage_schema_version(self):
        self.make_future_db("abc")
        with self.assertRaisesRegex(DatabaseError, "неверная версия"):
            Database(self.path).open()

    def test_not_a_sqlite_file(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"this is definitely not a database" * 50)
        db = Database(self.path)
        with self.assertRaises(DatabaseError):
            db.open()
        self.assertFalse(db.is_open)


class MigrationTests(Base):
    def test_migrations_apply_in_order_each_in_own_transaction(self):
        directory = self.migrations(**{"001_init": INIT, "002_more": SECOND})
        with self.assertLogs("candy", level="INFO") as logs:
            db = self.open(directory)
        self.assertEqual(db.version, 2)
        self.assertTrue({"one", "two"} <= self.tables(db))
        self.assertEqual(len([line for line in logs.output if "Миграция" in line]), 2)

    def test_upgrade_existing_database_makes_backup_copy(self):
        first = self.migrations(**{"001_init": INIT})
        with self.assertLogs("candy", level="INFO"):
            db = self.open(first)
        db.close()
        second = self.migrations(**{"001_init": INIT, "002_more": SECOND})
        with self.assertLogs("candy", level="INFO"):
            db = self.open(second)
        self.assertEqual(db.version, 2)
        backup = self.path.with_name(self.path.name + ".v1.bak")
        self.assertTrue(backup.exists())
        copy = sqlite3.connect(backup)
        try:
            names = {r[0] for r in copy.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            copy.close()
        self.assertIn("one", names)
        self.assertNotIn("two", names)  # копия снята ДО миграции
        if POSIX:
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)

    def test_fresh_database_gets_no_backup(self):
        directory = self.migrations(**{"001_init": INIT, "002_more": SECOND})
        with self.assertLogs("candy", level="INFO"):
            self.open(directory)
        self.assertEqual(list(self.path.parent.glob("*.bak")), [])

    def test_failed_migration_is_rolled_back_completely(self):
        bad = "CREATE TABLE half (id INTEGER);\nINSERT INTO no_such_table VALUES (1);\n"
        directory = self.migrations(**{"001_init": INIT, "002_bad": bad})
        db = Database(self.path, directory)
        with self.assertLogs("candy", level="INFO"), self.assertRaises(DatabaseError) as ctx:
            db.open()
        self.assertIn("002_bad.sql", str(ctx.exception))
        self.assertIn("прежней версии", str(ctx.exception))
        self.assertFalse(db.is_open)
        check = sqlite3.connect(self.path)
        try:
            tables = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            version = check.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
        finally:
            check.close()
        self.assertNotIn("half", tables)  # частично применённое откатилось
        self.assertIn("one", tables)  # предыдущая миграция остаётся
        self.assertEqual(version, "1")

    def test_database_recovers_after_the_migration_is_fixed(self):
        bad = self.migrations(**{"001_init": INIT, "002_bad": "SELECT * FROM nothing;"})
        with self.assertLogs("candy", level="INFO"), self.assertRaises(DatabaseError):
            Database(self.path, bad).open()
        good = self.migrations(**{"001_init": INIT, "002_bad": SECOND})
        with self.assertLogs("candy", level="INFO"):
            db = self.open(good)
        self.assertEqual(db.version, 2)
        self.assertIn("two", self.tables(db))

    def test_unfinished_statement_is_reported_before_changing_anything(self):
        directory = self.migrations(**{"001_init": INIT, "002_cut": "CREATE TABLE cut (id INTEGER"})
        with self.assertLogs("candy", level="INFO"), self.assertRaisesRegex(DatabaseError, "незавершённый"):
            Database(self.path, directory).open()

    def test_trigger_with_inner_semicolons(self):
        trigger = (
            "CREATE TABLE t (id INTEGER PRIMARY KEY, n INTEGER);\n"
            "CREATE TABLE log (msg TEXT);\n"
            "CREATE TRIGGER t_ins AFTER INSERT ON t BEGIN\n"
            "  INSERT INTO log VALUES ('a;b');\n"
            "  INSERT INTO log VALUES ('c');\n"
            "END;\n"
        )
        directory = self.migrations(**{"001_init": trigger})
        with self.assertLogs("candy", level="INFO"):
            db = self.open(directory)
        db.execute("INSERT INTO t(n) VALUES (1)")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM log").fetchone()[0], 2)

    def test_real_migrations_directory_is_valid(self):
        migrations = load_migrations(MIGRATIONS_DIR)
        self.assertEqual([m.version for m in migrations], list(range(1, len(migrations) + 1)))
        for migration in migrations:
            self.assertTrue(migration.statements())


class MigrationLoadingTests(Base):
    def test_rejects_bad_layouts(self):
        cases = {
            "bad name": {"init": INIT},
            "gap": {"001_a": INIT, "003_c": SECOND},
            "starts at 2": {"002_b": INIT},
            "duplicate": {"001_a": INIT, "001_b": SECOND},
            "empty": {},
        }
        for label, files in cases.items():
            with self.subTest(label):
                with self.assertRaises(DatabaseError):
                    load_migrations(self.migrations(**files))

    def test_split_statements(self):
        sql = "-- comment\nCREATE TABLE a (x TEXT);\nINSERT INTO a VALUES ('x;y');\n-- tail\n"
        self.assertEqual(
            split_statements(sql),
            ["-- comment\nCREATE TABLE a (x TEXT);", "INSERT INTO a VALUES ('x;y');"],
        )
        self.assertEqual(split_statements("-- only comment\n"), [])
        with self.assertRaises(DatabaseError):
            split_statements("SELECT 1")


class TransactionTests(Base):
    def setUp(self):
        super().setUp()
        directory = self.migrations(**{"001_init": INIT})
        with self.assertLogs("candy", level="INFO"):
            self.db = self.open(directory)

    def count(self):
        return self.db.execute("SELECT COUNT(*) FROM one").fetchone()[0]

    def test_commit(self):
        with self.db.transaction():
            self.db.execute("INSERT INTO one(note) VALUES ('a')")
            self.db.execute("INSERT INTO one(note) VALUES ('b')")
        self.assertEqual(self.count(), 3)
        self.assertFalse(self.db.connection.in_transaction)

    def test_rollback_on_error_and_error_propagates(self):
        with self.assertRaises(ValueError):
            with self.db.transaction():
                self.db.execute("INSERT INTO one(note) VALUES ('a')")
                raise ValueError("boom")
        self.assertEqual(self.count(), 1)
        self.assertFalse(self.db.connection.in_transaction)

    def test_sql_error_inside_rolls_back_whole_group(self):
        with self.assertRaises(sqlite3.Error):
            with self.db.transaction():
                self.db.execute("INSERT INTO one(note) VALUES ('a')")
                self.db.execute("INSERT INTO missing VALUES (1)")
        self.assertEqual(self.count(), 1)

    def test_nested_inner_rollback_keeps_outer_work(self):
        with self.db.transaction():
            self.db.execute("INSERT INTO one(note) VALUES ('outer')")
            with self.assertRaises(RuntimeError):
                with self.db.transaction():
                    self.db.execute("INSERT INTO one(note) VALUES ('inner')")
                    raise RuntimeError("inner failed")
            self.db.execute("INSERT INTO one(note) VALUES ('after')")
        notes = [r[0] for r in self.db.execute("SELECT note FROM one ORDER BY id")]
        self.assertEqual(notes, ["v1", "outer", "after"])

    def test_nested_outer_rollback_discards_committed_inner(self):
        with self.assertRaises(RuntimeError):
            with self.db.transaction():
                with self.db.transaction():
                    self.db.execute("INSERT INTO one(note) VALUES ('inner')")
                raise RuntimeError("outer failed")
        self.assertEqual(self.count(), 1)

    def test_usable_again_after_failed_transaction(self):
        for _ in range(3):
            with self.assertRaises(RuntimeError):
                with self.db.transaction():
                    raise RuntimeError("x")
        with self.db.transaction():
            self.db.execute("INSERT INTO one(note) VALUES ('ok')")
        self.assertEqual(self.count(), 2)

    def test_statements_outside_transaction_are_committed_at_once(self):
        self.db.execute("INSERT INTO one(note) VALUES ('solo')")
        other = sqlite3.connect(self.path)
        try:
            self.assertEqual(other.execute("SELECT COUNT(*) FROM one").fetchone()[0], 2)
        finally:
            other.close()

    def test_close_inside_transaction_discards_changes(self):
        with self.assertRaises(RuntimeError):
            with self.db.transaction():
                self.db.execute("INSERT INTO one(note) VALUES ('lost')")
                self.db.close()
                raise RuntimeError("closed while busy")
        self.db.open()
        self.assertEqual(self.count(), 1)

    def test_transaction_requires_open_database(self):
        self.db.close()
        with self.assertRaises(RuntimeError):
            with self.db.transaction():
                pass

    def test_commit_is_harmless(self):
        self.db.commit()
        with self.db.transaction():
            self.db.commit()  # не должен ломать или закрывать транзакцию
            self.db.execute("INSERT INTO one(note) VALUES ('x')")
        self.assertEqual(self.count(), 2)


if __name__ == "__main__":
    unittest.main()
