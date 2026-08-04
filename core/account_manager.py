# core/account_manager.py
"""
AccountManager — реестр и координатор AccountContext.

Этап 1:
  - Хранит один AccountContext (текущий single-account запуск).
  - Предоставляет интерфейс, который без изменений заработает
    при добавлении нескольких аккаунтов в Этапе 2+.
  - Не меняет поведение существующего userbot.

Этап 2+ (не здесь):
  - несколько одновременных контекстов
  - Multi Mode
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterator

from core.account_context import AccountContext

logger = logging.getLogger("account_manager")


class AccountManager:
    """
    Центральный реестр AccountContext.

    Обычный режим (Этап 1):
        Один активный аккаунт.
        Команда выполняется только на том аккаунте,
        с которого она отправлена — проверяется через ctx.telegram_id.

    Multi Mode (Этап 2+):
        Несколько активных аккаунтов одновременно.
        Multi Mode НЕ влияет на обычные команды из Telegram.
    """

    def __init__(self) -> None:
        # account_id → AccountContext
        self._contexts: dict[str, AccountContext] = {}
        self._active_id: str | None = None

    # ── Регистрация / получение ───────────────────────────────────────

    def register(self, ctx: AccountContext) -> None:
        """Добавляет контекст в реестр и устанавливает как активный."""
        self._contexts[ctx.account_id] = ctx
        if self._active_id is None:
            self._active_id = ctx.account_id
        logger.info(f"Зарегистрирован: {ctx.display_name}")

    def unregister(self, account_id: str) -> None:
        """Удаляет контекст из реестра."""
        ctx = self._contexts.pop(account_id, None)
        if ctx:
            logger.info(f"Удалён: {ctx.display_name}")
        if self._active_id == account_id:
            self._active_id = next(iter(self._contexts), None)

    def get(self, account_id: str) -> AccountContext | None:
        return self._contexts.get(account_id)

    def get_by_telegram_id(self, telegram_id: int) -> AccountContext | None:
        """
        Поиск по Telegram ID.
        Используется для обычного режима:
        команда из @account1 исполняется только на @account1.
        """
        for ctx in self._contexts.values():
            if ctx.telegram_id == telegram_id:
                return ctx
        return None

    def all(self) -> list[AccountContext]:
        return list(self._contexts.values())

    def __iter__(self) -> Iterator[AccountContext]:
        return iter(self._contexts.values())

    def __len__(self) -> int:
        return len(self._contexts)

    # ── Активный аккаунт (обычный режим) ─────────────────────────────

    @property
    def active(self) -> AccountContext | None:
        """
        Текущий активный аккаунт.
        Если аккаунт один — он активный автоматически.
        """
        if self._active_id and self._active_id in self._contexts:
            return self._contexts[self._active_id]
        if len(self._contexts) == 1:
            ctx = next(iter(self._contexts.values()))
            self._active_id = ctx.account_id
            return ctx
        return None

    def set_active(self, account_id: str) -> None:
        if account_id not in self._contexts:
            raise KeyError(f"Аккаунт не найден: {account_id!r}")
        self._active_id = account_id
        logger.info(f"Активный аккаунт: {self._contexts[account_id].display_name}")

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def make_display_name(telegram_id: int, username: str | None,
                          first_name: str, last_name: str) -> str:
        """
        Формирует отображаемое имя по правилам проекта:
          - "@username"        если username есть
          - "Имя Фамилия [ID]" если нет
        """
        if username:
            return f"@{username}"
        parts = [p for p in (first_name, last_name) if p]
        name  = " ".join(parts) or "Unknown"
        return f"{name} [{telegram_id}]"

    @staticmethod
    def make_fs_identifier(telegram_id: int, username: str | None) -> str:
        """
        Стабильный идентификатор для файловой системы
        (имя директории в accounts/).
        """
        return username or str(telegram_id)

    def build_context(
        self,
        *,
        api_id:      int,
        api_hash:    str,
        session_path: Path,
        telegram_id: int,
        username:    str | None,
        first_name:  str,
        last_name:   str,
        phone:       str | None,
        client:      object | None = None,
    ) -> AccountContext:
        """
        Создаёт и регистрирует AccountContext.
        Используется в main.py при запуске аккаунта.
        """
        account_id = self.make_display_name(telegram_id, username, first_name, last_name)
        ctx = AccountContext(
            account_id   = account_id,
            api_id       = api_id,
            api_hash     = api_hash,
            session_path = session_path,
            client       = client,
            telegram_id  = telegram_id,
            first_name   = first_name,
            last_name    = last_name,
            username     = username,
            phone        = phone,
        )
        self.register(ctx)
        return ctx

    # ── Профили на диске ──────────────────────────────────────────────

    @staticmethod
    def load_profiles(accounts_dir: Path) -> list[dict]:
        """
        Читает profile.json из accounts/<id>/.
        Используется при отображении списка аккаунтов в меню.
        """
        if not accounts_dir.exists():
            return []
        profiles = []
        for entry in sorted(accounts_dir.iterdir()):
            pf = entry / "profile.json"
            if entry.is_dir() and pf.exists():
                try:
                    profiles.append(json.loads(pf.read_text(encoding="utf-8")))
                except Exception as e:
                    logger.warning(f"Ошибка чтения профиля {entry.name}: {e}")
        return profiles

    @staticmethod
    def save_profile(ctx: AccountContext, accounts_dir: Path) -> None:
        """Сохраняет метаданные аккаунта в accounts/<id>/profile.json."""
        identifier = AccountManager.make_fs_identifier(ctx.telegram_id or 0, ctx.username)
        acc_dir    = accounts_dir / identifier
        acc_dir.mkdir(parents=True, exist_ok=True)
        profile = {
            "account_id":  ctx.account_id,
            "telegram_id": ctx.telegram_id,
            "username":    ctx.username,
            "first_name":  ctx.first_name,
            "last_name":   ctx.last_name,
            "phone":       ctx.phone,
            "api_id":      ctx.api_id,
            "api_hash":    ctx.api_hash,
            "session_path": str(ctx.session_path),
        }
        (acc_dir / "profile.json").write_text(
            json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.debug(f"Профиль сохранён: {identifier}")


# ── Глобальный синглтон ───────────────────────────────────────────────
# Импортируется там где нужен:
#   from core.account_manager import account_manager
account_manager: AccountManager = AccountManager()
