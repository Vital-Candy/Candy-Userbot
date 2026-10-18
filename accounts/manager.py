"""Реестр аккаунтов на диске: ``accounts/<id>/profile.json``, ``session.session`` и ``active.json``."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from accounts.account import Account
from accounts.migration import CURRENT_VERSION, migrate_profile
from config.settings import ACCOUNTS_DIR
from utils.files import secure_dir, secure_file
from utils.logger import logger


class AccountManager:
    """Загружает, сохраняет аккаунты и помнит, какой из них активный."""

    PROFILE_VERSION = CURRENT_VERSION

    def __init__(self, root: Path = ACCOUNTS_DIR) -> None:
        self.root = root
        self.accounts: dict[int, Account] = {}
        self.active_account_id: int | None = None

    def load(self) -> None:
        """Перечитывает все аккаунты с диска. Битые профили пропускаются с записью в лог."""
        self.accounts.clear()
        self.root.mkdir(parents=True, exist_ok=True)

        for profile_path in sorted(self.root.glob("*/profile.json")):
            try:
                account = self._read_profile(profile_path)
            except Exception as exc:
                logger.error("Не удалось загрузить %s: %s", profile_path, exc)
                continue
            self.accounts[account.account_id] = account

        self._load_active()

    def _read_profile(self, path: Path) -> Account:
        """Читает профиль, при необходимости мигрирует его на диске и чинит права файлов."""
        data = json.loads(path.read_text(encoding="utf-8"))
        data, migrated = migrate_profile(data)

        account_id = int(data["account_id"])
        api_id = int(data["api_id"])
        api_hash = str(data["api_hash"]).strip()
        if not api_id or not api_hash:
            raise ValueError("отсутствует API ID или API Hash")

        account_dir = path.parent
        session_path = account_dir / "session.session"
        if not session_path.is_file():
            raise FileNotFoundError(f"session не найдена: {session_path}")

        if migrated:
            # Старый файл сохраняем рядом: миграцию можно откатить вручную.
            backup = path.with_suffix(".json.bak")
            shutil.copy2(path, backup)
            secure_file(backup)
            self._atomic_write_json(path, data)
            logger.info("Профиль %s обновлён до версии %s.", path, CURRENT_VERSION)

        # Профиль и сессия содержат секреты: подтягиваем права и у старых установок.
        secure_dir(account_dir)
        secure_file(path)
        secure_file(session_path)

        return Account(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            username=data.get("username") or None,
            first_name=str(data.get("first_name", "")),
            account_dir=account_dir,
        )

    def _load_active(self) -> None:
        """Читает ID активного аккаунта из active.json; при ошибке остаётся None."""
        path = self.root / "active.json"
        self.active_account_id = None
        if not path.is_file():
            return
        try:
            self.active_account_id = int(json.loads(path.read_text(encoding="utf-8"))["account_id"])
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            logger.warning("Не удалось прочитать active.json: %s", exc)

    def save(self, account: Account) -> None:
        """Записывает profile.json аккаунта (создавая каталог) и обновляет реестр; активность не меняет."""
        account.account_dir.mkdir(parents=True, exist_ok=True)
        secure_dir(account.account_dir)
        profile = {
            "version": self.PROFILE_VERSION,
            "account_id": account.account_id,
            "api_id": account.api_id,
            "api_hash": account.api_hash,
            "username": account.username or "",
            "first_name": account.first_name,
            "session": "session.session",
        }
        self._atomic_write_json(account.profile_path, profile)
        self.accounts[account.account_id] = account

    def set_active(self, account: Account) -> None:
        """Делает аккаунт активным и запоминает выбор в active.json."""
        self._atomic_write_json(self.root / "active.json", {"account_id": account.account_id})
        self.active_account_id = account.account_id

    def add(self, account: Account, *, make_active: bool = True) -> None:
        """Добавляет новый аккаунт. Бросает ValueError, если аккаунт с таким ID уже есть."""
        if account.account_id in self.accounts:
            raise ValueError(f"аккаунт {account.account_id} уже существует")
        self.save(account)
        if make_active:
            self.set_active(account)

    def get(self, account_id: int) -> Account | None:
        """Аккаунт по ID или None."""
        return self.accounts.get(account_id)

    def get_active(self) -> Account | None:
        """Активный аккаунт; если выбранного нет, первый из списка, а без аккаунтов None."""
        if self.active_account_id is not None:
            account = self.get(self.active_account_id)
            if account:
                return account
        return next(iter(self.accounts.values()), None)

    def list(self) -> list[Account]:
        """Копия списка аккаунтов в порядке загрузки."""
        return list(self.accounts.values())

    @staticmethod
    def _atomic_write_json(path: Path, data: dict) -> None:
        """Пишет JSON через временный файл и rename, чтобы сбой не оставил обрезанный файл."""
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        secure_file(temp)  # права выставляем до переименования: файл не бывает открытым
        temp.replace(path)
