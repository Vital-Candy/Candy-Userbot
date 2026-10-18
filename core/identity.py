"""Определение и кэширование Telegram ID текущего аккаунта. Нужен storage и access.py."""
from __future__ import annotations

from typing import Any


class IdentityService:
    """Кэширует Telegram ID текущего аккаунта для storage/permissions."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self._account_id: int | None = None

    async def account_id(self) -> int:
        """ID аккаунта: первый вызов обращается к Telegram, дальше берётся из кэша.

        Raises:
            RuntimeError: Telegram не вернул данные о себе (``get_me()`` дал None).
        """
        if self._account_id is None:
            me = await self.client.get_me()
            if me is None:
                raise RuntimeError("Не удалось определить текущий Telegram account_id")
            self._account_id = int(me.id)
        return self._account_id
