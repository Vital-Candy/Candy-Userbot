from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.background_manager import BackgroundManager


@dataclass
class Account:
    account_id: int
    api_id: int
    api_hash: str
    username: str | None
    first_name: str
    session_path: Path

    background: BackgroundManager = field(init=False)

    def __post_init__(self) -> None:
        self.session_path = Path(self.session_path)
        self.background = BackgroundManager(
            self.session_path.parent / "background_state.json"
        )

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        if self.first_name:
            return self.first_name
        return str(self.account_id)
