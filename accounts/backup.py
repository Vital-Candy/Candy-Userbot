"""Резервные копии аккаунтов: ZIP с profile.json и session.session, создание и безопасное восстановление.

Вызывается из AccountControl (команды .backup, консоль, CLI).
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from accounts.account import Account
from accounts.manager import AccountManager
from accounts.migration import migrate_profile
from config.settings import BACKUPS_DIR
from utils.files import secure_dir, secure_file
from utils.logger import logger

PROFILE_NAME = "profile.json"
SESSION_NAME = "session.session"
ALLOWED_NAMES = frozenset({PROFILE_NAME, SESSION_NAME})


class BackupManager:
    """Создаёт, перечисляет и восстанавливает backup-архивы аккаунтов."""

    # Профиль и сессия весят килобайты. Лимиты защищают от «ZIP-бомб».
    MAX_PROFILE_BYTES = 64 * 1024
    MAX_SESSION_BYTES = 32 * 1024 * 1024

    def __init__(self, account_manager: AccountManager, backups_dir: Path = BACKUPS_DIR) -> None:
        self.accounts = account_manager
        self.backups_dir = Path(backups_dir)

    # ------------------------------------------------------------------ create

    def create(self, account: Account) -> Path:
        """Пишет архив ``<id>-<UTC-время>.zip`` в каталог backup и возвращает путь к нему.

        Бросает FileNotFoundError, если у аккаунта нет профиля или сессии.
        """
        if not account.profile_path.is_file() or not account.session_path.is_file():
            raise FileNotFoundError("у аккаунта отсутствует profile.json или session.session")

        self.backups_dir.mkdir(parents=True, exist_ok=True)
        secure_dir(self.backups_dir)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output = self.backups_dir / f"{account.account_id}-{stamp}.zip"
        # Пишем во временный файл и переименовываем: недописанный архив не выглядит как backup.
        temp = output.with_suffix(".zip.tmp")

        with tempfile.TemporaryDirectory(prefix="candy-backup-") as tmp:
            # Копия делается вне итогового архива, чтобы не упаковывать живую базу во время записи.
            session_copy = Path(tmp) / SESSION_NAME
            self._snapshot_session(account.session_path, session_copy)
            try:
                import zipfile  # лениво: модуль нужен только при создании и восстановлении backup

                with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.write(account.profile_path, PROFILE_NAME)
                    archive.write(session_copy, SESSION_NAME)
                secure_file(temp)
                temp.replace(output)  # архив появляется целиком или не появляется вовсе
            finally:
                temp.unlink(missing_ok=True)
        secure_file(output)
        return output

    def list(self) -> list[Path]:
        """Пути ко всем ``*.zip`` в каталоге backup, по имени (то есть по ID и времени)."""
        if not self.backups_dir.is_dir():
            return []
        return sorted(self.backups_dir.glob("*.zip"))

    @staticmethod
    def _snapshot_session(source: Path, destination: Path) -> None:
        """Согласованная копия SQLite-сессии, даже если аккаунт сейчас работает.

        Простое копирование файла во время записи может дать битую базу, поэтому
        используется штатный механизм backup из sqlite3.
        """
        try:
            src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
            try:
                dst = sqlite3.connect(destination)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
        except sqlite3.Error:
            logger.warning("Сессия %s не читается как SQLite, копирую файл как есть.", source)
            destination.unlink(missing_ok=True)
            shutil.copy2(source, destination)

    # ----------------------------------------------------------------- restore

    def restore(self, backup: str | Path) -> Account:
        """Восстанавливает аккаунт из архива и возвращает его.

        ``backup`` это путь или имя файла в каталоге backup. Бросает FileNotFoundError, ValueError
        (повреждённый или небезопасный архив) и FileExistsError, если аккаунт уже есть:
        существующий аккаунт восстановление не перезаписывает.
        """
        source = Path(backup).expanduser()
        if not source.is_absolute() and not source.exists():
            source = self.backups_dir / source
        if not source.is_file():
            raise FileNotFoundError(source)

        with tempfile.TemporaryDirectory(prefix="candy-restore-") as temp:
            temp_dir = Path(temp)
            # Сначала всё распаковываем и проверяем во временном каталоге, и только потом
            # трогаем каталог аккаунтов.
            self._extract_safe(source, temp_dir)
            profile = temp_dir / PROFILE_NAME
            session = temp_dir / SESSION_NAME

            try:
                raw = json.loads(profile.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ValueError(f"profile.json в backup повреждён: {exc}") from None
            data, _ = migrate_profile(raw)
            try:
                account_id = int(data["account_id"])
                api_id = int(data["api_id"])
            except (KeyError, TypeError, ValueError):
                raise ValueError("backup не содержит корректные account_id и API ID") from None
            api_hash = str(data.get("api_hash", "")).strip()
            if not api_id or not api_hash:
                raise ValueError("backup не содержит API ID/API Hash")

            target = self.accounts.root / str(account_id)
            if target.exists():
                raise FileExistsError(f"аккаунт {account_id} уже существует")

            target.mkdir(parents=True)
            # При любой ошибке убираем полусозданный каталог: иначе повторное восстановление
            # упрётся в «аккаунт уже существует».
            try:
                secure_dir(target)
                self.accounts._atomic_write_json(target / PROFILE_NAME, data)
                shutil.copy2(session, target / SESSION_NAME)
                secure_file(target / SESSION_NAME)
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                raise

        self.accounts.load()
        restored = self.accounts.get(account_id)
        if restored is None:
            raise ValueError("не удалось загрузить восстановленный аккаунт")
        return restored

    def _extract_safe(self, source: Path, destination: Path) -> None:
        """Распаковывает только profile.json и session.session, отвергая всё подозрительное.

        Проверяются пути (zip-slip), дубликаты, набор имён и размеры. Бросает ValueError.
        """
        import zipfile  # лениво, см. create()

        root = destination.resolve()
        try:
            archive_file = zipfile.ZipFile(source)
        except zipfile.BadZipFile:
            raise ValueError("файл не является корректным ZIP-архивом") from None
        with archive_file as archive:
            members = archive.infolist()
            for member in members:
                target = (destination / member.filename).resolve()
                if target != root and root not in target.parents:
                    raise ValueError("опасный путь в ZIP")
            names = [member.filename for member in members]
            if len(names) != len(set(names)):
                raise ValueError("backup содержит повторяющиеся имена файлов")
            if not ALLOWED_NAMES <= set(names):
                raise ValueError("неполный backup")
            if set(names) != ALLOWED_NAMES:
                raise ValueError("backup содержит неизвестные файлы")

            limits = {PROFILE_NAME: self.MAX_PROFILE_BYTES, SESSION_NAME: self.MAX_SESSION_BYTES}
            for member in members:
                limit = limits[member.filename]
                if member.file_size > limit:
                    raise ValueError(f"{member.filename} в backup слишком большой")
                # Заголовок ZIP можно подделать, поэтому размер ограничивается и при чтении.
                with archive.open(member) as src, (destination / member.filename).open("wb") as dst:
                    self._copy_limited(src, dst, limit, member.filename)

    @staticmethod
    def _copy_limited(src, dst, limit: int, name: str) -> None:
        """Копирует поток кусками и обрывает с ValueError, если данных больше ``limit`` байт."""
        written = 0
        while chunk := src.read(64 * 1024):
            written += len(chunk)
            if written > limit:
                raise ValueError(f"{name} в backup слишком большой")
            dst.write(chunk)
