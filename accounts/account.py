"""Модель аккаунта Telegram: данные профиля и пути к его файлам на диске."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Account:
    """Один сохранённый аккаунт: API-данные, имя и каталог с профилем и сессией."""

    account_id: int
    api_id: int
    api_hash: str
    username: str | None
    first_name: str
    account_dir: Path

    @property
    def session_path(self) -> Path:
        """Путь к SQLite-файлу сессии Telethon."""
        return self.account_dir / "session.session"

    @property
    def profile_path(self) -> Path:
        """Путь к profile.json с API-данными аккаунта."""
        return self.account_dir / "profile.json"

    @property
    def display_name(self) -> str:
        """Имя для показа: @username, иначе имя, иначе числовой ID."""
        if self.username:
            return f"@{self.username}"
        if self.first_name:
            return self.first_name
        return str(self.account_id)
