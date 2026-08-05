# core/client.py
"""
Прокси к активному TelegramClient.

Этап 2:
  - _set_current_client() вызывается из account_runner.activate_account()
    при смене активного аккаунта.
  - get_context() возвращает AccountContext активного аккаунта.
  - Модули продолжают использовать `from core.client import client`.
"""
from __future__ import annotations
import logging
from telethon import TelegramClient

logger = logging.getLogger("client")

_current_client: TelegramClient | None = None


class _ClientProxy:
    """
    Прокси к _current_client.
    При смене активного аккаунта _set_current_client() обновляет _current_client,
    и прокси автоматически делегирует к новому клиенту.
    """
    def __getattr__(self, name: str):
        if _current_client is None:
            raise RuntimeError("TelegramClient не инициализирован. Вызови activate_account().")
        return getattr(_current_client, name)

    def __call__(self, *args, **kwargs):
        if _current_client is None:
            raise RuntimeError("TelegramClient не инициализирован.")
        return _current_client(*args, **kwargs)

    def __bool__(self) -> bool:
        return _current_client is not None and _current_client.is_connected()

    def __repr__(self) -> str:
        return f"<_ClientProxy → {_current_client!r}>"


# Единственный экземпляр — импортируется всеми модулями
client: _ClientProxy = _ClientProxy()


def _set_current_client(raw: TelegramClient | None) -> None:
    """Обновляет активный клиент. Вызывается только из account_runner."""
    global _current_client
    _current_client = raw


def get_raw_client() -> TelegramClient | None:
    return _current_client


def get_context():
    """Возвращает AccountContext активного аккаунта."""
    from core.account_manager import account_manager
    return account_manager.active


# Обратная совместимость: старый код мог использовать init_client()
def init_client(profile: dict, ctx=None) -> TelegramClient:
    """
    Создаёт TelegramClient для профиля.
    Используй account_runner.connect_account() для нового кода.
    """
    from utils.paths import ACCOUNTS_DIR
    identifier   = profile.get("username") or profile.get("phone") or str(profile.get("id", "unknown"))
    session_path = ACCOUNTS_DIR / identifier / "session"

    raw = TelegramClient(str(session_path), profile["api_id"], profile["api_hash"])
    _set_current_client(raw)

    if ctx is not None:
        ctx.client = raw

    logger.info(f"init_client: {profile.get('username') or profile.get('id')}")
    return raw
