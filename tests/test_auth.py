"""Этап 2: вход в аккаунт (повторы кода и 2FA, ошибки, замена сессии)."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from telethon.errors import (
        ApiIdInvalidError,
        FloodWaitError,
        PasswordHashInvalidError,
        PhoneCodeExpiredError,
        PhoneCodeInvalidError,
        PhoneNumberInvalidError,
        SessionPasswordNeededError,
    )

    from accounts.auth import AuthError, AuthManager
    from accounts.manager import AccountManager
except ImportError:  # Telethon не установлен
    AuthManager = None

from tests.helpers import make_account

POSIX = os.name == "posix"


class FakeClient:
    """Минимальный TelegramClient: ответы на sign_in задаются сценарием."""

    def __init__(self, *, send_code_error=None, sign_in_script=(), me=None):
        self.send_code_error = send_code_error
        self.script = list(sign_in_script)
        self.me = me or SimpleNamespace(id=777, username="bob", first_name="Bob")
        self.path = ""
        self.connected = False
        self.send_code_calls = 0
        self.sign_in_calls: list[dict] = []

    def __call__(self, session, api_id, api_hash):  # подменяет конструктор TelegramClient
        self.path = session
        return self

    async def connect(self):
        self.connected = True
        Path(self.path + ".session").write_bytes(b"fresh-session")

    def is_connected(self):
        return self.connected

    async def is_user_authorized(self):
        return False

    async def send_code_request(self, phone):
        self.send_code_calls += 1
        if self.send_code_error is not None:
            raise self.send_code_error

    async def sign_in(self, **kwargs):
        self.sign_in_calls.append(kwargs)
        outcome = self.script.pop(0) if self.script else None
        if isinstance(outcome, Exception):
            raise outcome

    async def get_me(self):
        return self.me

    async def disconnect(self):
        self.connected = False


class Reader:
    """Источник ответов пользователя; считает обращения."""

    def __init__(self, *values):
        self.values = list(values)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.values.pop(0) if self.values else self.values_exhausted()

    @staticmethod
    def values_exhausted():
        raise AssertionError("пользователя спросили больше раз, чем ожидалось")


@unittest.skipIf(AuthManager is None, "Telethon не установлен")
class AuthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "accounts"
        self.manager = AccountManager(self.root)
        self.auth = AuthManager(self.manager)

    def tearDown(self):
        self.tmp.cleanup()

    async def add(self, client, code_reader, password_reader=None, **kwargs):
        with patch("accounts.auth.TelegramClient", client):
            return await self.auth.add_account(
                api_id=11, api_hash="hash", phone="+100", code_reader=code_reader,
                password_reader=password_reader, **kwargs,
            )

    def assert_clean(self, client):
        self.assertFalse((self.root / ".tmp").exists(), "временная папка не удалена")
        self.assertFalse(client.connected, "клиент остался подключённым")

    async def test_successful_login_saves_account(self):
        client = FakeClient()
        account = await self.add(client, Reader("12345"))
        self.assertEqual((account.account_id, account.username), (777, "bob"))
        self.assertEqual(account.session_path.read_bytes(), b"fresh-session")
        profile = json.loads(account.profile_path.read_text(encoding="utf-8"))
        self.assertEqual((profile["api_id"], profile["api_hash"]), (11, "hash"))
        self.assertEqual(self.manager.get_active().account_id, 777)
        self.assertEqual(client.sign_in_calls, [{"phone": "+100", "code": "12345"}])
        self.assert_clean(client)
        if POSIX:
            self.assertEqual(stat.S_IMODE(account.session_path.stat().st_mode), 0o600)

    async def test_async_readers_are_supported(self):
        async def code():
            return "555"

        client = FakeClient()
        await self.add(client, code)
        self.assertEqual(client.sign_in_calls[0]["code"], "555")

    async def test_wrong_code_is_retried(self):
        client = FakeClient(sign_in_script=[PhoneCodeInvalidError(request=None)] * 2)
        reader = Reader("1", "2", "3")
        with self.assertLogs("candy", level="WARNING"):
            account = await self.add(client, reader)
        self.assertEqual(reader.calls, 3)
        self.assertEqual(account.account_id, 777)

    async def test_three_wrong_codes_give_clear_error(self):
        client = FakeClient(sign_in_script=[PhoneCodeInvalidError(request=None)] * 3)
        reader = Reader("1", "2", "3")
        with self.assertLogs("candy", level="WARNING"), self.assertRaisesRegex(AuthError, "Неверный код"):
            await self.add(client, reader)
        self.assertEqual(reader.calls, 3)
        self.assertFalse((self.root / "777").exists())
        self.assert_clean(client)

    async def test_expired_code_requests_a_new_one(self):
        client = FakeClient(sign_in_script=[PhoneCodeExpiredError(request=None)])
        with self.assertLogs("candy", level="WARNING"):
            await self.add(client, Reader("old", "new"))
        self.assertEqual(client.send_code_calls, 2)

    async def test_expired_code_gives_up_after_three_attempts(self):
        client = FakeClient(sign_in_script=[PhoneCodeExpiredError(request=None)] * 3)
        with self.assertLogs("candy", level="WARNING"), self.assertRaisesRegex(AuthError, "Код истёк"):
            await self.add(client, Reader("a", "b", "c"))

    async def test_two_factor_password_with_retry(self):
        client = FakeClient(
            sign_in_script=[SessionPasswordNeededError(request=None), PasswordHashInvalidError(request=None)]
        )
        passwords = Reader("wrong", "right")
        with self.assertLogs("candy", level="WARNING"):
            await self.add(client, Reader("1"), passwords)
        self.assertEqual(passwords.calls, 2)
        self.assertEqual(client.sign_in_calls[-1], {"password": "right"})

    async def test_two_factor_without_reader_is_clear_error(self):
        client = FakeClient(sign_in_script=[SessionPasswordNeededError(request=None)])
        with self.assertRaisesRegex(AuthError, "2FA"):
            await self.add(client, Reader("1"), None)
        self.assert_clean(client)

    async def test_two_factor_attempts_are_limited(self):
        client = FakeClient(
            sign_in_script=[SessionPasswordNeededError(request=None)] + [PasswordHashInvalidError(request=None)] * 3
        )
        with self.assertLogs("candy", level="WARNING"), self.assertRaisesRegex(AuthError, "пароль 2FA"):
            await self.add(client, Reader("1"), Reader("a", "b", "c"))

    async def test_invalid_api_credentials(self):
        client = FakeClient(send_code_error=ApiIdInvalidError(request=None))
        with self.assertRaisesRegex(AuthError, "API"):
            await self.add(client, Reader())
        self.assert_clean(client)

    async def test_invalid_phone(self):
        client = FakeClient(send_code_error=PhoneNumberInvalidError(request=None))
        with self.assertRaisesRegex(AuthError, "номер телефона"):
            await self.add(client, Reader())

    async def test_flood_wait_reports_seconds(self):
        client = FakeClient(send_code_error=FloodWaitError(request=None, capture=45))
        with self.assertRaisesRegex(AuthError, "45"):
            await self.add(client, Reader())

    async def test_flood_wait_during_sign_in(self):
        client = FakeClient(sign_in_script=[FloodWaitError(request=None, capture=60)])
        with self.assertRaisesRegex(AuthError, "60"):
            await self.add(client, Reader("1"))

    async def test_auth_error_is_a_user_error_without_traceback_need(self):
        from core.errors import UserError

        self.assertTrue(issubclass(AuthError, UserError))
        self.assertTrue(issubclass(AuthError, RuntimeError))

    async def test_stale_tmp_folder_is_cleaned_before_login(self):
        stale = self.root / ".tmp"
        stale.mkdir(parents=True)
        (stale / "session.session").write_bytes(b"leftover")
        client = FakeClient()
        account = await self.add(client, Reader("1"))
        self.assertEqual(account.session_path.read_bytes(), b"fresh-session")
        self.assert_clean(client)

    async def test_existing_account_is_refused_by_default_and_untouched(self):
        directory = make_account(self.root, 777, "bob")
        before = (directory / "session.session").read_bytes()
        client = FakeClient()
        with self.assertRaises(FileExistsError):
            await self.add(client, Reader("1"))
        self.assertEqual((directory / "session.session").read_bytes(), before)
        self.assert_clean(client)

    async def test_replace_existing_overwrites_session_and_credentials(self):
        directory = make_account(self.root, 777, "bob")
        self.manager.load()
        client = FakeClient()
        account = await self.add(client, Reader("1"), replace_existing=True)
        self.assertEqual((directory / "session.session").read_bytes(), b"fresh-session")
        self.assertEqual(account.api_id, 11)
        profile = json.loads((directory / "profile.json").read_text(encoding="utf-8"))
        self.assertEqual((profile["api_id"], profile["api_hash"]), (11, "hash"))
        self.assertEqual(self.manager.get_active().account_id, 777)

    async def test_confirm_replace_callback_decides(self):
        directory = make_account(self.root, 777, "bob")
        before = (directory / "session.session").read_bytes()
        asked: list[int] = []

        async def decline(account_id):
            asked.append(account_id)
            return False

        with self.assertRaises(FileExistsError):
            await self.add(FakeClient(), Reader("1"), confirm_replace=decline)
        self.assertEqual(asked, [777])
        self.assertEqual((directory / "session.session").read_bytes(), before)

        account = await self.add(FakeClient(), Reader("1"), confirm_replace=lambda _id: True)
        self.assertEqual(account.session_path.read_bytes(), b"fresh-session")


if __name__ == "__main__":
    unittest.main()
