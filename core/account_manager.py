# core/account_manager.py
"""
AccountManager — реестр и координатор всех AccountContext.

Этап 2:
  - start_all()        — параллельное подключение всех аккаунтов.
  - stop_all()         — корректное отключение всех.
  - stop_account()     — отключение одного без остановки остальных.
  - get_by_client()    — поиск контекста по TelegramClient (изоляция событий).
  - set_active_account / get_active_account.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Iterator

from core.account_context import AccountContext, AccountStatus

logger = logging.getLogger("account_manager")


class AccountManager:

    def __init__(self) -> None:
        self._contexts: dict[str, AccountContext] = {}
        self._active_id: str | None = None

    # ── Регистрация ───────────────────────────────────────────────────

    def register(self, ctx: AccountContext) -> None:
        self._contexts[ctx.account_id] = ctx
        if self._active_id is None:
            self._active_id = ctx.account_id
        logger.info(f"Зарегистрирован: {ctx.display_name}")

    def unregister(self, account_id: str) -> None:
        ctx = self._contexts.pop(account_id, None)
        if ctx:
            logger.info(f"Удалён из реестра: {ctx.display_name}")
        if self._active_id == account_id:
            self._active_id = next(iter(self._contexts), None)

    def get(self, account_id: str) -> AccountContext | None:
        return self._contexts.get(account_id)

    def get_by_telegram_id(self, telegram_id: int) -> AccountContext | None:
        """
        Поиск по Telegram ID.
        Используется для обычного режима:
        команда от @account1 исполняется только на @account1.
        """
        for ctx in self._contexts.values():
            if ctx.telegram_id == telegram_id:
                return ctx
        return None

    def get_by_client(self, client_instance) -> AccountContext | None:
        """
        Поиск контекста по объекту TelegramClient.
        Используется в обработчиках событий:

            async def handler(event):
                ctx = account_manager.get_by_client(event.client)
                # ctx — контекст аккаунта который получил событие

        Это основа изоляции событий между аккаунтами.
        """
        for ctx in self._contexts.values():
            if ctx.client is client_instance:
                return ctx
        return None

    def all(self) -> list[AccountContext]:
        return list(self._contexts.values())

    def connected(self) -> list[AccountContext]:
        return [c for c in self._contexts.values() if c.is_running()]

    def __iter__(self) -> Iterator[AccountContext]:
        return iter(self._contexts.values())

    def __len__(self) -> int:
        return len(self._contexts)

    # ── Активный аккаунт ──────────────────────────────────────────────

    @property
    def active(self) -> AccountContext | None:
        if self._active_id and self._active_id in self._contexts:
            return self._contexts[self._active_id]
        if len(self._contexts) == 1:
            ctx = next(iter(self._contexts.values()))
            self._active_id = ctx.account_id
            return ctx
        return None

    def set_active_account(self, account_id: str) -> None:
        """
        Переключает активный аккаунт.
        - Не перезапускает Python.
        - Не отключает другие аккаунты.
        - Деактивирует dispatcher/модули старого, активирует нового.
        """
        if account_id not in self._contexts:
            raise KeyError(f"Аккаунт не найден: {account_id!r}")

        old = self.active
        new = self._contexts[account_id]

        if old and old.account_id != account_id:
            from core.account_runner import deactivate_account
            deactivate_account(old)

        self._active_id = account_id

        from core.account_runner import activate_account
        activate_account(new)
        logger.info(f"Активный аккаунт: {new.display_name}")

    def get_active_account(self) -> AccountContext | None:
        return self.active

    # ── Старт всех аккаунтов ──────────────────────────────────────────

    async def start_all(self, profiles: list[dict]) -> tuple[int, int]:
        """
        Параллельно подключает все аккаунты из профилей.
        Ошибка одного не останавливает остальных.
        Возвращает (успешно, ошибок).
        """
        from core.account_runner import connect_account, build_context_from_profile

        if not profiles:
            logger.info("Нет сохранённых аккаунтов")
            return 0, 0

        contexts = []
        for p in profiles:
            ctx = build_context_from_profile(p)
            self.register(ctx)
            contexts.append(ctx)

        results = await asyncio.gather(
            *[connect_account(ctx) for ctx in contexts],
            return_exceptions=True,
        )

        ok = fail = 0
        for ctx, result in zip(contexts, results):
            if isinstance(result, Exception):
                ctx.status    = AccountStatus.ERROR
                ctx.error_msg = str(result)
                logger.error(f"[{ctx.display_name}] исключение: {result}")
                fail += 1
            elif result:
                ok += 1
            else:
                fail += 1

        logger.info(f"start_all: подключено {ok}, ошибок {fail}")
        return ok, fail

    # ── Остановка ─────────────────────────────────────────────────────

    async def stop_account(self, account_id: str) -> None:
        """Отключает один аккаунт. Остальные продолжают работу."""
        ctx = self.get(account_id)
        if not ctx:
            return

        if ctx.account_id == self._active_id:
            from core.account_runner import deactivate_account
            deactivate_account(ctx)

        from core.account_runner import disconnect_account
        await disconnect_account(ctx)
        self.unregister(account_id)

    async def stop_all(self) -> None:
        """
        Корректно останавливает все аккаунты.
        Ошибка одного disconnect не мешает остальным.
        """
        from core.account_runner import deactivate_account, disconnect_account

        active = self.active
        if active:
            try: deactivate_account(active)
            except Exception as e: logger.warning(f"deactivate error: {e}")

        results = await asyncio.gather(
            *[disconnect_account(ctx) for ctx in list(self._contexts.values())],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                logger.warning(f"disconnect error: {r}")

        self._contexts.clear()
        self._active_id = None
        logger.info("Все аккаунты остановлены")

    # ── Добавление нового аккаунта ────────────────────────────────────

    async def add_account(self, api_id: int, api_hash: str) -> AccountContext | None:
        """
        Программный API добавления нового аккаунта.
        Процесс: телефон → код → 2FA → get_me() → сохранение → подключение.
        Возвращает AccountContext или None при ошибке.
        """
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError
        from utils.paths import ACCOUNTS_DIR
        from core.account_context import AccountContext
        from datetime import datetime
        import json

        tmp_session = ACCOUNTS_DIR / "_tmp_add"
        tmp_session.parent.mkdir(parents=True, exist_ok=True)

        client = TelegramClient(str(tmp_session), api_id, api_hash)

        try:
            await client.connect()

            if not await client.is_user_authorized():
                phone = input("  Номер телефона (+7...): ").strip()
                await client.send_code_request(phone)

                code = input("  Код из Telegram: ").strip()
                try:
                    await client.sign_in(phone, code)
                except SessionPasswordNeededError:
                    pw = input("  Пароль 2FA: ").strip()
                    await client.sign_in(password=pw)

            me = await client.get_me()
            identifier   = me.username or str(me.id)
            new_dir      = ACCOUNTS_DIR / identifier
            new_session  = new_dir / "session.session"
            new_dir.mkdir(parents=True, exist_ok=True)

            await client.disconnect()

            # Переносим сессию
            for ext in (".session", ".session-journal"):
                src = tmp_session.parent / (tmp_session.name + ext)
                if src.exists():
                    src.replace(new_dir / ("session" + ext))

            profile = {
                "api_id":   api_id,   "api_hash": api_hash,
                "id":       me.id,    "name":     me.first_name or "",
                "username": me.username or "",
                "phone":    str(me.phone or ""),
                "added":    datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            (new_dir / "profile.json").write_text(
                json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            ctx = AccountContext(
                account_id   = self.make_display_name(me.id, me.username, me.first_name or "", me.last_name or ""),
                api_id       = api_id,
                api_hash     = api_hash,
                session_path = new_dir / "session",
                telegram_id  = me.id,
                first_name   = me.first_name or "",
                last_name    = me.last_name or "",
                username     = me.username,
                phone        = str(me.phone or ""),
            )

            from core.account_runner import connect_account
            success = await connect_account(ctx)
            if success:
                self.register(ctx)
                return ctx
            return None

        except Exception as e:
            logger.error(f"add_account error: {e}")
            if client.is_connected():
                await client.disconnect()
            for ext in (".session", ".session-journal"):
                p = tmp_session.parent / (tmp_session.name + ext)
                if p.exists():
                    try: p.unlink()
                    except Exception: pass
            return None

    # ── Вспомогательные ──────────────────────────────────────────────

    @staticmethod
    def make_display_name(
        telegram_id: int,
        username:    str | None,
        first_name:  str,
        last_name:   str,
    ) -> str:
        if username:
            return f"@{username}"
        parts = [p for p in (first_name, last_name) if p]
        name  = " ".join(parts) or "Unknown"
        return f"{name} [{telegram_id}]"

    @staticmethod
    def make_fs_identifier(telegram_id: int, username: str | None) -> str:
        return username or str(telegram_id)

    @staticmethod
    def load_profiles(accounts_dir: Path) -> list[dict]:
        if not accounts_dir.exists():
            return []
        profiles = []
        for entry in sorted(accounts_dir.iterdir()):
            pf = entry / "profile.json"
            if entry.is_dir() and pf.exists() and not entry.name.startswith("_"):
                try:
                    profiles.append(json.loads(pf.read_text(encoding="utf-8")))
                except Exception as e:
                    logger.warning(f"Ошибка профиля {entry.name}: {e}")
        return profiles

    @staticmethod
    def save_profile(ctx: AccountContext, accounts_dir: Path) -> None:
        identifier = AccountManager.make_fs_identifier(ctx.telegram_id or 0, ctx.username)
        acc_dir    = accounts_dir / identifier
        acc_dir.mkdir(parents=True, exist_ok=True)
        profile = {
            "account_id":  ctx.account_id,  "telegram_id": ctx.telegram_id,
            "username":    ctx.username,     "first_name":  ctx.first_name,
            "last_name":   ctx.last_name,    "phone":       ctx.phone,
            "api_id":      ctx.api_id,       "api_hash":    ctx.api_hash,
            "session_path": str(ctx.session_path),
        }
        (acc_dir / "profile.json").write_text(
            json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
        )


# Глобальный синглтон
account_manager: AccountManager = AccountManager()
