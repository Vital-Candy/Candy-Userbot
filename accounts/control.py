"""Фасад над AccountManager и BackupManager для модулей, консоли и CLI (без Telegram-логики)."""
from __future__ import annotations

from pathlib import Path

from accounts.account import Account
from accounts.backup import BackupManager
from accounts.manager import AccountManager


class AccountControl:
    """Операции над аккаунтами и backup, общие для Telegram-команд, консоли и CLI."""

    def __init__(self, accounts: AccountManager, backups: BackupManager) -> None:
        self.accounts = accounts
        self.backups = backups

    def resolve(self, ref: str) -> Account:
        """Находит аккаунт по числовому ID или по @username (без учёта регистра)."""
        ref = ref.strip().lstrip("@")
        if not ref:
            raise ValueError("укажите ID или @username аккаунта")
        if ref.isdigit():
            account = self.accounts.get(int(ref))
            if account is not None:
                return account
        matches = [
            item for item in self.accounts.list() if item.username and item.username.lower() == ref.lower()
        ]
        if len(matches) == 1:
            return matches[0]
        raise LookupError(f"аккаунт «{ref}» не найден")

    def describe(self) -> str:
        """Многострочный список аккаунтов с отметкой активного; для команды .account и консоли."""
        accounts = self.accounts.list()
        if not accounts:
            return "Аккаунтов нет."
        active = self.accounts.get_active()
        lines = []
        for item in accounts:
            mark = "●" if active is not None and item.account_id == active.account_id else "○"
            suffix = " (активный)" if mark == "●" else ""
            lines.append(f"{mark} {item.display_name} · {item.account_id}{suffix}")
        return "\n".join(lines)

    def backup_create(self, ref: str | None = None) -> Path:
        """Backup аккаунта по ссылке (ID или @username) или активного, если ссылка не задана.

        Бросает LookupError, если аккаунтов нет или ссылка не найдена.
        """
        account = self.resolve(ref) if ref else self.accounts.get_active()
        if account is None:
            raise LookupError("нет аккаунтов для backup")
        return self.backups.create(account)

    def backup_list(self) -> list[Path]:
        """Список архивов backup."""
        return self.backups.list()

    def backup_restore(self, name: str) -> Account:
        """Восстанавливает аккаунт из архива; ошибки те же, что у BackupManager.restore."""
        return self.backups.restore(name)
