from __future__ import annotations

import asyncio
import logging

from telethon import TelegramClient

from core.account import Account

logger = logging.getLogger("candy_userbot")

_CURRENT_ACCOUNT: Account | None = None

def current_account() -> Account:
    if _CURRENT_ACCOUNT is None:
        raise RuntimeError("Аккаунт приложения не установлен")
    return _CURRENT_ACCOUNT


class UserbotApp:
    def __init__(self, account: Account) -> None:
        self.account = account
        self.client = TelegramClient(
            str(account.session_path),
            account.api_id,
            account.api_hash,
        )
        self.stop_event = asyncio.Event()
        self.running = False

    async def start(self) -> None:
        global _CURRENT_ACCOUNT
        _CURRENT_ACCOUNT = self.account
        await self.client.connect()

        if not await self.client.is_user_authorized():
            await self.client.disconnect()
            raise RuntimeError("Сессия недействительна")

        self.running = True
        logger.info(
            "Запущен аккаунт: %s",
            self.account.display_name,
        )

    async def stop(self) -> None:
        if not self.running:
            return

        self.running = False
        self.stop_event.set()

        # Сначала останавливаются фоновые задачи.
        # Позже time_name сможет восстановить имя в своём
        # shutdown/cleanup до отключения TelegramClient.
        await self.account.background.close()

        if self.client.is_connected():
            await self.client.disconnect()

        global _CURRENT_ACCOUNT
        _CURRENT_ACCOUNT = None

        logger.info(
            "Остановлен аккаунт: %s",
            self.account.display_name,
        )
