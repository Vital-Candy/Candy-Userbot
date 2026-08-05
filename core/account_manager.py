from __future__ import annotations

import json

from core.account import Account
from utils.paths import ACCOUNTS_DIR


class AccountManager:

    def __init__(self) -> None:
        self.accounts: list[Account] = []
        self.active_account_id: int | None = None

    def load(self) -> None:
        self.accounts.clear()

        for profile_path in sorted(
            ACCOUNTS_DIR.glob(
                "*/profile.json"
            )
        ):
            try:
                data = json.loads(
                    profile_path.read_text(
                        encoding="utf-8"
                    )
                )

                account_dir = (
                    profile_path.parent
                )

                account = Account(
                    account_id=int(
                        data["account_id"]
                    ),
                    api_id=int(
                        data["api_id"]
                    ),
                    api_hash=str(
                        data["api_hash"]
                    ),
                    username=(
                        data.get("username")
                        or None
                    ),
                    first_name=str(
                        data.get(
                            "first_name",
                            "",
                        )
                    ),
                    session_path=(
                        account_dir
                        / "session"
                    ),
                )

                self.accounts.append(
                    account
                )

            except Exception as error:
                print(
                    "Не удалось загрузить "
                    f"{profile_path}: {error}"
                )

        self._load_active()

    def _load_active(self) -> None:
        path = (
            ACCOUNTS_DIR
            / "active.json"
        )

        if not path.exists():
            return

        try:
            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            self.active_account_id = int(
                data["account_id"]
            )

        except Exception:
            self.active_account_id = None

    def save_active(
        self,
        account: Account,
    ) -> None:
        path = (
            ACCOUNTS_DIR
            / "active.json"
        )

        data = {
            "account_id": (
                account.account_id
            )
        }

        path.write_text(
            json.dumps(
                data,
                indent=2,
            ),
            encoding="utf-8",
        )

        self.active_account_id = (
            account.account_id
        )

    def get_active(
        self,
    ) -> Account | None:

        for account in self.accounts:
            if (
                account.account_id
                == self.active_account_id
            ):
                return account

        if self.accounts:
            account = self.accounts[0]

            self.save_active(
                account
            )

            return account

        return None

    def get(
        self,
        account_id: int,
    ) -> Account | None:

        for account in self.accounts:
            if (
                account.account_id
                == account_id
            ):
                return account

        return None

    def add(
        self,
        account: Account,
    ) -> None:

        account_dir = (
            ACCOUNTS_DIR
            / str(
                account.account_id
            )
        )

        account_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        profile = {
            "account_id": (
                account.account_id
            ),
            "api_id": (
                account.api_id
            ),
            "api_hash": (
                account.api_hash
            ),
            "username": (
                account.username
                or ""
            ),
            "first_name": (
                account.first_name
            ),
        }

        (
            account_dir
            / "profile.json"
        ).write_text(
            json.dumps(
                profile,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        account.session_path = (
            account_dir
            / "session"
        )

        self.accounts.append(
            account
        )

        self.save_active(
            account
        )


account_manager = AccountManager()