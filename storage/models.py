"""Неизменяемые модели строк БД, которые возвращают хранилища меток и прав."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True, frozen=True)
class Label:
    """Метка на сообщении. ``metadata`` это разобранный JSON из колонки metadata_json."""

    id: int
    account_id: int
    chat_id: int
    message_id: int
    name: str
    creator_id: int | None
    created_at: datetime
    metadata: dict[str, Any]


@dataclass(slots=True, frozen=True)
class Permission:
    """Право ``permission`` пользователя ``subject_id``; ``granted_by`` это кто его выдал."""

    account_id: int
    subject_id: int
    permission: str
    granted_by: int
    created_at: datetime
