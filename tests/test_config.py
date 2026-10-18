"""Этап 1: настройки, необязательный .env, ввод с терминала."""
from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from config.env import load_env_file, parse_env
from config.settings import load_settings
from utils.prompt import ask


class EnvParserTests(unittest.TestCase):
    def test_parse_basic_forms(self):
        text = (
            "# комментарий\n"
            "\n"
            "A=1\n"
            "export B = two \n"
            'C="with # hash"\n'
            "D='single'\n"
            "E=value # trailing comment\n"
            "bad line\n"
            "1BAD=x\n"
            "F=\n"
        )
        self.assertEqual(
            parse_env(text),
            {"A": "1", "B": "two", "C": "with # hash", "D": "single", "E": "value", "F": ""},
        )

    def test_missing_file_is_fine(self):
        self.assertEqual(load_env_file(Path("/nonexistent/.env"), {}), {})

    def test_directory_instead_of_file_is_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_env_file(Path(tmp), {}), {})

    def test_existing_environment_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("CANDY_LOG_LEVEL=DEBUG\nOTHER=1\n", encoding="utf-8")
            environ = {"CANDY_LOG_LEVEL": "ERROR"}
            added = load_env_file(path, environ)
            self.assertEqual(environ, {"CANDY_LOG_LEVEL": "ERROR", "OTHER": "1"})
            self.assertEqual(added, {"OTHER": "1"})


class SettingsTests(unittest.TestCase):
    def test_defaults(self):
        base = Path("/project")
        s = load_settings({}, base)
        self.assertEqual(s.data_dir, base / "data")
        self.assertEqual(s.accounts_dir, base / "data" / "accounts")
        self.assertEqual(s.database_path, base / "data" / "database" / "candy.sqlite3")
        self.assertEqual(s.log_level, "INFO")
        self.assertEqual(s.warnings, ())

    def test_relative_and_absolute_data_dir(self):
        base = Path("/project")
        self.assertEqual(load_settings({"CANDY_DATA_DIR": "state"}, base).data_dir, base / "state")
        self.assertEqual(
            load_settings({"CANDY_DATA_DIR": "/var/candy"}, base).data_dir, Path("/var/candy")
        )

    def test_blank_data_dir_falls_back_to_default(self):
        self.assertEqual(
            load_settings({"CANDY_DATA_DIR": "  "}, Path("/p")).data_dir, Path("/p/data")
        )

    def test_log_level_is_case_insensitive(self):
        self.assertEqual(load_settings({"CANDY_LOG_LEVEL": "debug"}).log_level, "DEBUG")

    def test_invalid_log_level_falls_back_with_warning(self):
        s = load_settings({"CANDY_LOG_LEVEL": "LOUD"})
        self.assertEqual(s.log_level, "INFO")
        self.assertEqual(len(s.warnings), 1)
        self.assertIn("LOUD", s.warnings[0])

    def test_api_credentials_are_not_settings(self):
        s = load_settings({"API_ID": "1", "API_HASH": "x"})
        self.assertFalse(hasattr(s, "api_id"))
        self.assertFalse(hasattr(s, "api_hash"))


class AskTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_typed_value(self):
        with patch("builtins.input", return_value="hello"):
            self.assertEqual(await ask("> "), "hello")

    async def test_secret_uses_getpass(self):
        with patch("getpass.getpass", return_value="s3cret") as gp, patch(
            "builtins.input", side_effect=AssertionError("input() не должен вызываться")
        ):
            self.assertEqual(await ask("pw: ", secret=True), "s3cret")
        gp.assert_called_once_with("pw: ")

    async def test_eof_is_raised(self):
        with patch("builtins.input", side_effect=EOFError):
            with self.assertRaises(EOFError):
                await ask("> ")

    async def test_cancelled_prompt_does_not_block_and_is_harmless(self):
        release = threading.Event()

        def blocking_input(_prompt=""):
            release.wait(5)
            return "late"

        try:
            with patch("builtins.input", blocking_input):
                task = asyncio.create_task(ask("> "))
                await asyncio.sleep(0.05)
                started = time.monotonic()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertLess(time.monotonic() - started, 0.5)
        finally:
            release.set()  # поток дочитает «поздний» ввод в уже отменённый future
        await asyncio.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
