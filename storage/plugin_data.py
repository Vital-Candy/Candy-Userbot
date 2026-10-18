"""Хранилище «ключ-значение» для плагинов (таблица plugin_data) с лимитами на размер данных.

Доступно плагинам через PluginAPI; данные не пересекаются между аккаунтами и плагинами.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from storage.database import Database

MAX_KEY_LENGTH = 128
MAX_VALUE_BYTES = 64 * 1024
MAX_KEYS_PER_PLUGIN = 1000


class PluginDataStore:
    """Ключ-значение для плагинов. Изолировано по аккаунту и по имени плагина."""

    def __init__(self, database: Database) -> None:
        self.db = database

    def get(self, *, account_id: int, plugin: str, key: str, default: Any = None) -> Any:
        """Значение по ключу или ``default``, если ключа нет."""
        row = self.db.execute(
            "SELECT value_json FROM plugin_data WHERE account_id = ? AND plugin = ? AND key = ?",
            (account_id, self._plugin(plugin), self._key(key)),
        ).fetchone()
        return json.loads(row["value_json"]) if row else default

    def set(self, *, account_id: int, plugin: str, key: str, value: Any) -> None:
        """Сохраняет JSON-значение. Бросает ValueError, если оно не сериализуется, больше
        MAX_VALUE_BYTES или у плагина уже MAX_KEYS_PER_PLUGIN ключей (обновление старого ключа
        лимит не затрагивает)."""
        plugin, key = self._plugin(plugin), self._key(key)
        try:
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"значение не сохраняется как JSON: {exc}") from exc
        if len(payload.encode("utf-8")) > MAX_VALUE_BYTES:
            raise ValueError(f"значение больше {MAX_VALUE_BYTES // 1024} КиБ")
        # Проверка лимита и запись в одной транзакции, чтобы параллельные set не обошли его.
        with self.db.transaction():
            exists = self.db.execute(
                "SELECT 1 FROM plugin_data WHERE account_id = ? AND plugin = ? AND key = ?",
                (account_id, plugin, key),
            ).fetchone()
            if not exists:
                count = self.db.execute(
                    "SELECT COUNT(*) FROM plugin_data WHERE account_id = ? AND plugin = ?",
                    (account_id, plugin),
                ).fetchone()[0]
                if count >= MAX_KEYS_PER_PLUGIN:
                    raise ValueError(f"у плагина уже {MAX_KEYS_PER_PLUGIN} ключей")
            self.db.execute(
                """
                INSERT INTO plugin_data(account_id, plugin, key, value_json, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(account_id, plugin, key)
                DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
                """,
                (account_id, plugin, key, payload, datetime.now(timezone.utc).isoformat()),
            )

    def delete(self, *, account_id: int, plugin: str, key: str) -> bool:
        """Удаляет ключ; True, если он существовал."""
        with self.db.transaction():
            cursor = self.db.execute(
                "DELETE FROM plugin_data WHERE account_id = ? AND plugin = ? AND key = ?",
                (account_id, self._plugin(plugin), self._key(key)),
            )
        return cursor.rowcount > 0

    def keys(self, *, account_id: int, plugin: str) -> list[str]:
        """Ключи плагина в алфавитном порядке."""
        rows = self.db.execute(
            "SELECT key FROM plugin_data WHERE account_id = ? AND plugin = ? ORDER BY key",
            (account_id, self._plugin(plugin)),
        ).fetchall()
        return [row["key"] for row in rows]

    def clear(self, *, account_id: int, plugin: str) -> int:
        """Удаляет все ключи плагина и возвращает их количество."""
        with self.db.transaction():
            cursor = self.db.execute(
                "DELETE FROM plugin_data WHERE account_id = ? AND plugin = ?",
                (account_id, self._plugin(plugin)),
            )
        return cursor.rowcount

    @staticmethod
    def _plugin(plugin: str) -> str:
        """Обрезает пробелы в имени плагина; пустое имя: ValueError."""
        plugin = str(plugin).strip()
        if not plugin:
            raise ValueError("имя плагина не может быть пустым")
        return plugin

    @staticmethod
    def _key(key: str) -> str:
        """Проверяет ключ (1..MAX_KEY_LENGTH символов); иначе ValueError."""
        key = str(key)
        if not key or len(key) > MAX_KEY_LENGTH:
            raise ValueError(f"ключ должен быть длиной от 1 до {MAX_KEY_LENGTH} символов")
        return key
