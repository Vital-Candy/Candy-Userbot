"""Общие вспомогательные функции для тестов аккаунтов."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def make_session(path: Path, marker: str = "x") -> None:
    """Создаёт настоящую SQLite-сессию с одной строкой, как у Telethon."""
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS sessions (dc_id INTEGER, note TEXT)")
        connection.execute("INSERT INTO sessions VALUES (1, ?)", (marker,))
        connection.commit()
    finally:
        connection.close()


def make_account(
    root: Path,
    account_id: int = 1,
    username: str | None = "alice",
    *,
    profile: dict | None = None,
    session: bool = True,
) -> Path:
    """Создаёт папку аккаунта на диске. Возвращает путь к ней."""
    directory = root / str(account_id)
    directory.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "account_id": account_id,
        "api_id": 12345,
        "api_hash": "hash",
        "username": username or "",
        "first_name": "First",
        "session": "session.session",
    }
    if profile is not None:
        data = profile
    (directory / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    if session:
        make_session(directory / "session.session", marker=f"acc{account_id}")
    return directory


def session_marker(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT note FROM sessions").fetchone()[0]
    finally:
        connection.close()
