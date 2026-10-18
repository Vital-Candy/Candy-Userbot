"""Фабрика TelegramClient для аккаунта userbot."""
from __future__ import annotations

from telethon import TelegramClient

from accounts.account import Account


def create_client(account: Account) -> TelegramClient:
    """Создаёт TelegramClient из сохранённого профиля аккаунта.

    Только конструирует клиент: подключение и авторизацию выполняет вызывающий код.
    """
    return TelegramClient(
        str(account.session_path),
        account.api_id,
        account.api_hash,
        # Userbot должен переживать обрывы сети: -1 — бесконечные переподключения.
        connection_retries=-1,
        retry_delay=5,
        auto_reconnect=True,
    )
