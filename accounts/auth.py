"""Интерактивный вход в Telegram (код и пароль 2FA) и сохранение нового аккаунта.

Используется консолью и CLI; результат записывается через AccountManager.
"""
from __future__ import annotations

import inspect
import shutil

from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from accounts.account import Account
from accounts.manager import AccountManager
from core.errors import UserError
from utils.files import secure_dir, secure_file
from utils.logger import logger

MAX_ATTEMPTS = 3


class AuthError(UserError):
    """Вход в Telegram не удался; текст сообщения показывается пользователю."""


async def _read(reader):
    """Вызывает reader; поддерживает и обычную функцию, и корутину."""
    value = reader()
    if inspect.isawaitable(value):
        value = await value
    return value


class AuthManager:
    """Выполняет вход по номеру телефона и регистрирует аккаунт в AccountManager."""

    def __init__(self, account_manager: AccountManager) -> None:
        self.accounts = account_manager

    async def add_account(
        self,
        api_id: int,
        api_hash: str,
        phone: str,
        code_reader,
        password_reader=None,
        *,
        replace_existing: bool = False,
        confirm_replace=None,
    ) -> Account:
        """Входит в аккаунт и сохраняет его (профиль и сессию).

        Если такой аккаунт уже сохранён, его сессия и API-данные заменяются
        только при ``replace_existing=True`` или когда ``confirm_replace(account_id)``
        (функция или корутина) вернул True. Это нужно, когда старая сессия отозвана.
        """
        root = self.accounts.root
        # Вход идёт во временной сессии: в каталог аккаунта она попадёт только после успеха.
        temp_dir = root / ".tmp"
        # Остатки прошлого аварийного запуска не должны мешать новому входу.
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        secure_dir(temp_dir)
        session_path = temp_dir / "session"
        client = TelegramClient(str(session_path), api_id, api_hash)

        try:
            await client.connect()
            if await client.is_user_authorized():
                raise AuthError("Временная сессия неожиданно оказалась авторизованной.")
            await self._login(client, phone, code_reader, password_reader)

            me = await client.get_me()
            if me is None:
                raise AuthError("Telegram не вернул данные аккаунта.")

            # Замена существующего аккаунта разрешается только явно (флаг или подтверждение).
            account_dir = root / str(me.id)
            existed = account_dir.exists()
            if existed and not replace_existing:
                allowed = confirm_replace is not None and await _read(lambda: confirm_replace(me.id))
                if not allowed:
                    raise FileExistsError(f"аккаунт {me.id} уже существует")
            account_dir.mkdir(parents=True, exist_ok=True)
            # Клиент закрываем до переноса: иначе SQLite-файл сессии может быть ещё открыт.
            await client.disconnect()

            source = session_path.with_suffix(".session")
            target = account_dir / "session.session"
            source.replace(target)
            secure_file(target)  # сессия равна доступу к аккаунту: только владелец

            account = Account(me.id, api_id, api_hash, me.username, me.first_name or "", account_dir)
            if existed:
                self.accounts.save(account)
                self.accounts.set_active(account)
            else:
                self.accounts.add(account)
            return account
        finally:
            if client.is_connected():
                await client.disconnect()
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def _login(self, client, phone: str, code_reader, password_reader) -> None:
        """Запрашивает код и входит; до MAX_ATTEMPTS попыток. Бросает AuthError с понятным текстом."""
        try:
            await client.send_code_request(phone)
        except ApiIdInvalidError:
            raise AuthError("Неверные API ID или API Hash. Проверьте их на my.telegram.org/apps.") from None
        except PhoneNumberInvalidError:
            raise AuthError("Неверный номер телефона. Нужен формат +<код страны><номер>.") from None
        except FloodWaitError as exc:
            raise AuthError(f"Telegram просит подождать {exc.seconds} с перед следующей попыткой.") from None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            code = await _read(code_reader)
            try:
                await client.sign_in(phone=phone, code=code)
                return
            except SessionPasswordNeededError:
                await self._sign_in_with_password(client, password_reader)
                return
            except PhoneCodeInvalidError:
                if attempt == MAX_ATTEMPTS:
                    raise AuthError(f"Неверный код ({MAX_ATTEMPTS} попытки). Запустите вход заново.") from None
                logger.warning("Неверный код. Попытка %d из %d.", attempt + 1, MAX_ATTEMPTS)
            except PhoneCodeExpiredError:
                if attempt == MAX_ATTEMPTS:
                    raise AuthError("Код истёк. Запустите вход заново.") from None
                logger.warning("Код истёк, запрашиваю новый.")
                await client.send_code_request(phone)
            except FloodWaitError as exc:
                raise AuthError(f"Telegram просит подождать {exc.seconds} с перед следующей попыткой.") from None

    async def _sign_in_with_password(self, client, password_reader) -> None:
        """Вход с паролем 2FA; без password_reader или после MAX_ATTEMPTS ошибок бросает AuthError."""
        if password_reader is None:
            raise AuthError("На аккаунте включена двухфакторная защита, нужен пароль 2FA.")
        for attempt in range(1, MAX_ATTEMPTS + 1):
            password = await _read(password_reader)
            try:
                await client.sign_in(password=password)
                return
            except PasswordHashInvalidError:
                if attempt == MAX_ATTEMPTS:
                    raise AuthError(f"Неверный пароль 2FA ({MAX_ATTEMPTS} попытки). Запустите вход заново.") from None
                logger.warning("Неверный пароль 2FA. Попытка %d из %d.", attempt + 1, MAX_ATTEMPTS)
            except FloodWaitError as exc:
                raise AuthError(f"Telegram просит подождать {exc.seconds} с перед следующей попыткой.") from None
