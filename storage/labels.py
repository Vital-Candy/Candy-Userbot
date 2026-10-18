"""Хранилище меток сообщений (таблица labels). Используется модулем меток (.label, .goto)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from storage.database import Database
from storage.models import Label
from utils.text import MARKDOWN_SPECIAL_HINT, has_markdown_syntax


class LabelStore:
    """CRUD для меток сообщений. Все метки изолированы по Telegram account_id."""

    def __init__(self, database: Database) -> None:
        self.db = database

    def create(
        self,
        *,
        account_id: int,
        chat_id: int,
        message_id: int,
        name: str,
        creator_id: int | None = None,
        metadata: dict | None = None,
    ) -> Label:
        """Создаёт метку и возвращает её.

        Имя нормализуется (нижний регистр, без пробелов и Markdown). Бросает ValueError для
        неверного имени и sqlite3.IntegrityError, если такая метка на сообщении уже есть.
        """
        normalized = self._normalize_name(name)
        created_at = datetime.now(timezone.utc)
        payload = json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":"))
        # Вставка и чтение в одной транзакции: вернётся ровно та строка, что записана.
        with self.db.transaction():
            cursor = self.db.execute(
                """
                INSERT INTO labels(
                    account_id, chat_id, message_id, name, creator_id, created_at, metadata_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (account_id, chat_id, message_id, normalized, creator_id, created_at.isoformat(), payload),
            )
            return self.get_by_id(cursor.lastrowid)

    def get_by_id(self, label_id: int | None) -> Label:
        """Метка по ID. Бросает KeyError, если её нет, и RuntimeError для ``None``."""
        if label_id is None:
            raise RuntimeError("Не удалось получить ID метки")
        row = self.db.execute("SELECT * FROM labels WHERE id = ?", (label_id,)).fetchone()
        if row is None:
            raise KeyError(f"Метка {label_id} не найдена")
        return self._from_row(row)

    def get(
        self, *, account_id: int, chat_id: int, message_id: int, name: str
    ) -> Label | None:
        """Метка с точным именем на сообщении или None."""
        row = self.db.execute(
            """
            SELECT * FROM labels
            WHERE account_id = ? AND chat_id = ? AND message_id = ? AND name = ?
            """,
            (account_id, chat_id, message_id, self._normalize_name(name)),
        ).fetchone()
        return self._from_row(row) if row else None

    def list_for_message(self, *, account_id: int, chat_id: int, message_id: int) -> list[Label]:
        """Все метки сообщения в порядке создания."""
        rows = self.db.execute(
            """
            SELECT * FROM labels
            WHERE account_id = ? AND chat_id = ? AND message_id = ?
            ORDER BY id
            """,
            (account_id, chat_id, message_id),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_by_name(
        self, *, account_id: int, name: str, newest_first: bool = False
    ) -> list[Label]:
        """Все метки с таким именем во всех чатах аккаунта, по порядку создания (или обратному)."""
        # Направление подставляется в SQL строкой, но берётся только из двух констант.
        order = "DESC" if newest_first else "ASC"
        rows = self.db.execute(
            f"""
            SELECT * FROM labels
            WHERE account_id = ? AND name = ?
            ORDER BY id {order}
            """,
            (account_id, self._normalize_name(name)),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def delete(self, *, account_id: int, chat_id: int, message_id: int, name: str) -> bool:
        """Удаляет метку; True, если она существовала."""
        with self.db.transaction():
            cursor = self.db.execute(
                """
                DELETE FROM labels
                WHERE account_id = ? AND chat_id = ? AND message_id = ? AND name = ?
                """,
                (account_id, chat_id, message_id, self._normalize_name(name)),
            )
        return cursor.rowcount > 0

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Приводит имя к нижнему регистру и проверяет его; бросает ValueError (1-64 символа, без
        пробелов и Markdown, чтобы имя безопасно вставлялось в ответы бота)."""
        value = name.strip().lower()
        if not value or len(value) > 64:
            raise ValueError("Имя метки должно содержать от 1 до 64 символов")
        if any(char.isspace() for char in value):
            raise ValueError("Имя метки не должно содержать пробелы")
        if has_markdown_syntax(value):
            raise ValueError(
                "Имя метки не должно содержать символы Markdown: " + MARKDOWN_SPECIAL_HINT
            )
        return value

    @staticmethod
    def _from_row(row) -> Label:
        """Строка БД в модель Label (дата и metadata_json разбираются)."""
        return Label(
            id=int(row["id"]),
            account_id=int(row["account_id"]),
            chat_id=int(row["chat_id"]),
            message_id=int(row["message_id"]),
            name=str(row["name"]),
            creator_id=int(row["creator_id"]) if row["creator_id"] is not None else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
            metadata=json.loads(str(row["metadata_json"])),
        )
