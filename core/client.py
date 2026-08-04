# core/client.py
"""
Клиент Telethon.

Этап 1:
  - _ClientProxy остаётся — один аккаунт работает как прежде.
  - init_client() теперь опционально принимает AccountContext
    для будущей интеграции.
  - get_raw_client() / get_context() — для модулей которые
    хотят получить текущий контекст.

Этап 2+:
  - _current_client → dict[account_id, TelegramClient]
  - _ClientProxy станет мультиплексором (не сейчас).
"""
from __future__ import annotations

import logging
from pathlib import Path

from telethon import TelegramClient

logger = logging.getLogger("client")

_current_client: TelegramClient | None = None
_current_context = None  # AccountContext | None — избегаем циклического импорта


# ── Прокси ───────────────────────────────────────────────────────────

class _ClientProxy:
    """
    Прокси к активному TelegramClient.
    Все модули импортируют `client` — этот объект.
    При смене аккаунта (init_client) proxy автоматически
    указывает на новый клиент.
    """

    def __getattr__(self, name: str):
        if _current_client is None:
            raise RuntimeError(
                "TelegramClient не инициализирован. "
                "Вызови init_client() перед использованием."
            )
        return getattr(_current_client, name)

    def __call__(self, *args, **kwargs):
        """Поддержка await client(SomeRequest())."""
        if _current_client is None:
            raise RuntimeError("TelegramClient не инициализирован.")
        return _current_client(*args, **kwargs)

    def __bool__(self) -> bool:
        return _current_client is not None and _current_client.is_connected()

    def __repr__(self) -> str:
        return f"<_ClientProxy → {_current_client!r}>"


# Единственный экземпляр — импортируется всеми модулями
client: _ClientProxy = _ClientProxy()


# ── Инициализация ─────────────────────────────────────────────────────

def init_client(profile: dict, ctx=None) -> TelegramClient:
    """
    Создаёт TelegramClient для указанного профиля.
    
    ctx (AccountContext | None):
        Если передан — сохраняется в _current_context.
        Модули могут получить его через get_context().
        В Этапе 1 используется опционально.
    """
    global _current_client, _current_context

    from utils.paths import ACCOUNTS_DIR
    identifier   = profile.get("username") or profile.get("phone") or str(profile.get("id", "unknown"))
    session_path = ACCOUNTS_DIR / identifier / "session"

    _current_client = TelegramClient(
        str(session_path),
        profile["api_id"],
        profile["api_hash"],
    )

    if ctx is not None:
        _current_context = ctx
        ctx.client = _current_client

    logger.info(f"Client ready: {profile.get('username') or profile.get('phone') or profile.get('id')}")
    return _current_client


def get_raw_client() -> TelegramClient | None:
    """Возвращает сырой TelegramClient (для внутреннего использования)."""
    return _current_client


def get_context():
    """
    Возвращает текущий AccountContext (или None если не установлен).
    Используется модулями которым нужен изолированный state.
    """
    return _current_context
