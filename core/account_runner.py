# core/account_runner.py
"""
Жизненный цикл одного аккаунта: подключение, активация, отключение.

connect_account()   — создаёт TelegramClient, подключает, заполняет контекст.
activate_account()  — регистрирует dispatcher + модули на этом аккаунте.
deactivate_account()— снимает dispatcher + модули.
disconnect_account()— отключает TelegramClient.

Этап 2: одновременно может быть несколько подключённых аккаунтов,
        но только один "активный" (с dispatcher + modules).
Этап 3: dispatcher + модули на каждом аккаунте.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from core.account_context import AccountContext, AccountStatus
from utils.paths import ACCOUNTS_DIR

logger = logging.getLogger("account_runner")


# ── Подключение ──────────────────────────────────────────────────────

async def connect_account(ctx: AccountContext) -> bool:
    """
    Создаёт TelegramClient для контекста, проверяет авторизацию,
    получает актуальные данные через get_me().

    Не меняет активный аккаунт.
    Ошибка одного аккаунта не влияет на остальные.
    """
    from telethon import TelegramClient

    ctx.status = AccountStatus.CONNECTING
    logger.info(f"Подключаю: {ctx.display_name}")

    client = TelegramClient(
        str(ctx.session_path),
        ctx.api_id,
        ctx.api_hash,
    )

    try:
        await client.connect()

        if not await client.is_user_authorized():
            ctx.status    = AccountStatus.NEEDS_LOGIN
            ctx.error_msg = "Сессия недействительна — требуется повторный вход"
            logger.warning(f"[{ctx.display_name}] {ctx.error_msg}")
            await client.disconnect()
            return False

        me = await client.get_me()

        # Обновляем контекст актуальными данными из Telegram
        ctx.telegram_id = me.id
        ctx.username    = me.username
        ctx.first_name  = me.first_name or ""
        ctx.last_name   = me.last_name  or ""
        ctx.phone       = getattr(me, "phone", None)

        from core.account_manager import AccountManager
        ctx.account_id = AccountManager.make_display_name(
            ctx.telegram_id, ctx.username, ctx.first_name, ctx.last_name
        )

        ctx.client = client
        ctx.status = AccountStatus.CONNECTED

        from datetime import datetime
        ctx.connected_at = datetime.now()

        logger.info(f"✅ Подключён: {ctx.display_name}")
        return True

    except Exception as e:
        ctx.status    = AccountStatus.ERROR
        ctx.error_msg = str(e)
        logger.error(f"[{ctx.display_name}] Ошибка подключения: {e}")
        if client.is_connected():
            await client.disconnect()
        return False


# ── Активация dispatcher + modules ───────────────────────────────────

def activate_account(ctx: AccountContext) -> None:
    """
    Регистрирует dispatcher и загружает модули на этом аккаунте.
    Обновляет глобальный прокси client → ctx.client.

    Вызывается только для одного аккаунта за раз (активного).
    """
    if ctx.client is None or not ctx.is_running():
        raise RuntimeError(f"Аккаунт {ctx.display_name} не подключён")

    from core.client import _set_current_client
    from core.dispatcher import setup_dispatcher, reset_uptime
    from core.loader import load_modules

    # Прокси → этот аккаунт
    _set_current_client(ctx.client)
    reset_uptime()

    # Dispatcher регистрируется на ctx.client, handlers → ctx.handlers
    setup_dispatcher(ctx.client, ctx)

    # Модули регистрируются на ctx.client через прокси
    loaded = load_modules(ctx.client, ctx)
    logger.info(f"[{ctx.display_name}] активирован, модулей: {len(loaded)}")


def deactivate_account(ctx: AccountContext) -> None:
    """
    Снимает dispatcher и shutdown модулей с этого аккаунта.
    """
    from core.dispatcher import teardown_dispatcher
    from core.loader import shutdown_modules

    teardown_dispatcher(ctx)
    shutdown_modules(ctx)
    logger.info(f"[{ctx.display_name}] деактивирован")


# ── Отключение ───────────────────────────────────────────────────────

async def disconnect_account(ctx: AccountContext) -> None:
    """
    Корректно отключает один аккаунт:
      1. Отменяет задачи.
      2. Снимает handlers.
      3. Отключает TelegramClient.

    Не удаляет сессию. Не трогает другие аккаунты.
    """
    if ctx.status == AccountStatus.DISCONNECTING:
        return

    ctx.status = AccountStatus.DISCONNECTING
    logger.info(f"Отключаю: {ctx.display_name}")

    await ctx.cancel_tasks()
    ctx.remove_all_handlers()

    if ctx.client is not None:
        try:
            if ctx.client.is_connected():
                await ctx.client.disconnect()
        except Exception as e:
            logger.warning(f"[{ctx.display_name}] disconnect error: {e}")

    ctx.client = None
    ctx.status = AccountStatus.OFFLINE
    logger.info(f"[{ctx.display_name}] отключён")


# ── Сборка AccountContext из профиля ─────────────────────────────────

def build_context_from_profile(profile: dict) -> AccountContext:
    """Создаёт AccountContext из profile.json (без подключения)."""
    from core.account_manager import AccountManager

    identifier   = profile.get("username") or profile.get("phone") or str(profile.get("id", ""))
    session_path = ACCOUNTS_DIR / identifier / "session"

    account_id = AccountManager.make_display_name(
        profile.get("id", 0),
        profile.get("username") or None,
        profile.get("name", "") or profile.get("first_name", ""),
        profile.get("last_name", ""),
    )

    return AccountContext(
        account_id   = account_id,
        api_id       = profile["api_id"],
        api_hash     = profile["api_hash"],
        session_path = session_path,
        telegram_id  = profile.get("id"),
        first_name   = profile.get("name", ""),
        last_name    = profile.get("last_name", ""),
        username     = profile.get("username") or None,
        phone        = profile.get("phone"),
    )
