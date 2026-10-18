"""SQLite-слой: открытие базы, транзакции с SAVEPOINT и версионные SQL-миграции из ``migrations/``.

Над ним работают LabelStore, PermissionStore и PluginDataStore; создаёт его Storage.
"""
from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.errors import UserError
from utils.files import secure_file
from utils.logger import logger

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIGRATION_NAME = re.compile(r"^(\d{3,})_([A-Za-z0-9_\-]+)\.sql$")

_METADATA_DDL = "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"


class DatabaseError(UserError):
    """Базу данных нельзя открыть или обновить. Сообщение рассчитано на пользователя."""


@dataclass(frozen=True, slots=True)
class Migration:
    """Один файл миграции: версия из номера в имени, имя и путь."""

    version: int
    name: str
    path: Path

    def statements(self) -> list[str]:
        """Читает файл и возвращает его SQL-операторы по одному."""
        return split_statements(self.path.read_text(encoding="utf-8"), self.path.name)


def load_migrations(directory: Path) -> list[Migration]:
    """Читает ``NNN_имя.sql``. Номера должны идти подряд с 1 без дублей."""
    found: dict[int, Migration] = {}
    for path in sorted(Path(directory).glob("*.sql")):
        match = _MIGRATION_NAME.match(path.name)
        if match is None:
            raise DatabaseError(
                f"Файл миграции {path.name} назван неверно: ожидается NNN_имя.sql"
            )
        version = int(match.group(1))
        if version in found:
            raise DatabaseError(
                f"Две миграции с номером {version}: {found[version].path.name} и {path.name}"
            )
        found[version] = Migration(version, match.group(2), path)
    if not found:
        raise DatabaseError(f"В {directory} нет ни одной миграции")
    expected = list(range(1, len(found) + 1))
    if sorted(found) != expected:
        raise DatabaseError(
            f"Номера миграций должны идти подряд с 1, найдено: {sorted(found)}"
        )
    return [found[version] for version in expected]


def split_statements(sql: str, source: str = "SQL") -> list[str]:
    """Делит скрипт на операторы так же, как это делает SQLite (триггеры, строки, комментарии)."""
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    leftover = "\n".join(
        part for part in buffer.splitlines() if part.strip() and not part.strip().startswith("--")
    )
    if leftover:
        raise DatabaseError(f"{source}: незавершённый оператор в конце файла: {leftover[:60]!r}")
    return statements


class Database:
    """Небольшой SQLite-слой для постоянных данных userbot.

    Соединение работает в режиме автокоммита; несколько операций, которые должны
    пройти вместе, объединяются через ``with db.transaction():``.
    """

    def __init__(self, path: Path, migrations_dir: Path | None = None) -> None:
        self.path = Path(path)
        self.migrations_dir = Path(migrations_dir) if migrations_dir else MIGRATIONS_DIR
        self._connection: sqlite3.Connection | None = None
        self._depth = 0
        self.version = 0

    # ----------------------------------------------------------- open / close

    def open(self) -> None:
        """Открывает соединение и обновляет схему до последней версии. Повторный вызов ничего не делает.

        Бросает DatabaseError, если файл повреждён, миграция не применилась или база создана
        более новой версией userbot.
        """
        if self._connection is not None:
            return
        migrations = load_migrations(self.migrations_dir)
        latest = migrations[-1].version
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(self.path, isolation_level=None)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Не удалось открыть базу данных {self.path}: {exc}") from exc
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            # Версия проверяется первой: базу от новой версии нельзя ни менять,
            # ни «чинить» миграциями этой версии.
            version = self._read_version(connection)
            if version > latest:
                raise DatabaseError(
                    f"База данных {self.path} создана более новой версией Candy Userbot "
                    f"(схема {version}, эта версия понимает до {latest}). "
                    "Обновите userbot или укажите другой CANDY_DATA_DIR."
                )
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            self._migrate(connection, version, migrations)
        except BaseException as exc:
            # Любой сбой при открытии (включая KeyboardInterrupt) не должен оставлять
            # висящее соединение.
            connection.close()
            self._connection = None
            if isinstance(exc, sqlite3.DatabaseError):
                raise DatabaseError(f"Не удалось открыть базу данных {self.path}: {exc}") from exc
            raise
        self._connection = connection
        self._depth = 0

    def close(self) -> None:
        """Закрывает соединение. Повторный вызов безопасен."""
        connection, self._connection = self._connection, None
        self._depth = 0
        if connection is not None:
            connection.close()  # незавершённая транзакция откатывается

    @property
    def connection(self) -> sqlite3.Connection:
        """Открытое соединение; бросает RuntimeError, если база не открыта."""
        if self._connection is None:
            raise RuntimeError("Database is not open")
        return self._connection

    @property
    def is_open(self) -> bool:
        """Открыта ли база сейчас."""
        return self._connection is not None

    # ------------------------------------------------------------------ query

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        """Выполняет один запрос с параметрами. Вне transaction() изменения коммитятся сразу."""
        return self.connection.execute(sql, parameters)

    def commit(self) -> None:
        """Оставлено для совместимости: вне transaction() каждая операция уже закоммичена."""

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Атомарная группа операций. Вложенные блоки используют SAVEPOINT."""
        connection = self.connection
        # Внешний блок открывает настоящую транзакцию, вложенные только SAVEPOINT:
        # внутренняя ошибка откатывает лишь свою часть.
        savepoint = f"candy_sp_{self._depth}" if self._depth else None
        connection.execute(f"SAVEPOINT {savepoint}" if savepoint else "BEGIN")
        self._depth += 1
        try:
            yield connection
        except BaseException:
            self._depth -= 1
            # Если базу закрыли внутри блока, откатывать уже нечего (close() всё отменил).
            if self._connection is connection:
                if savepoint:
                    connection.execute(f"ROLLBACK TO {savepoint}")
                    connection.execute(f"RELEASE {savepoint}")
                else:
                    connection.execute("ROLLBACK")
            raise
        else:
            self._depth -= 1
            connection.execute(f"RELEASE {savepoint}" if savepoint else "COMMIT")

    # -------------------------------------------------------------- migration

    @staticmethod
    def _read_version(connection: sqlite3.Connection) -> int:
        """Версия схемы из таблицы metadata; 0 для новой базы. Бросает DatabaseError при мусоре."""
        try:
            has_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'metadata'"
            ).fetchone()
            if not has_table:
                return 0
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise DatabaseError(f"Файл базы данных повреждён или это не SQLite: {exc}") from exc
        if row is None:
            return 0
        try:
            version = int(row["value"])
        except (TypeError, ValueError):
            version = -1
        if version < 0:
            raise DatabaseError(f"В базе данных записана неверная версия схемы: {row['value']!r}")
        return version

    def _migrate(
        self, connection: sqlite3.Connection, version: int, migrations: list[Migration]
    ) -> None:
        # Копия делается только для существующей базы (version > 0), пустую копировать незачем.
        pending = [m for m in migrations if m.version > version]
        if pending and version > 0:
            self._backup_before_migration(connection, version)
        for migration in pending:
            self._apply(connection, migration)
            logger.info("Миграция базы данных %03d_%s применена.", migration.version, migration.name)
        self.version = migrations[-1].version

    def _apply(self, connection: sqlite3.Connection, migration: Migration) -> None:
        statements = migration.statements()  # ошибки файла находим до BEGIN
        # DDL в SQLite транзакционный: миграция применяется целиком вместе с записью версии
        # или не применяется вовсе.
        connection.execute("BEGIN")
        try:
            connection.execute(_METADATA_DDL)
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(migration.version),),
            )
            connection.execute("COMMIT")
        except BaseException as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            if isinstance(exc, sqlite3.Error):
                raise DatabaseError(
                    f"Миграция {migration.path.name} не применена: {exc}. "
                    "База данных осталась на прежней версии."
                ) from exc
            raise

    def _backup_before_migration(self, connection: sqlite3.Connection, version: int) -> None:
        """Сохраняет рядом копию ``<база>.v<версия>.bak``; неудача копии миграцию не блокирует."""
        target = self.path.with_name(f"{self.path.name}.v{version}.bak")
        try:
            target.unlink(missing_ok=True)
            copy = sqlite3.connect(target)
            try:
                connection.backup(copy)
            finally:
                copy.close()
            secure_file(target)
            logger.info("Копия базы перед миграцией: %s", target)
        except (OSError, sqlite3.Error) as exc:
            logger.warning("Не удалось сделать копию базы перед миграцией: %s", exc)
