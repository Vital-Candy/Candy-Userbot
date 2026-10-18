"""Разбор текста сообщения в команду userbot (префикс, имя, аргументы)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ParsedCommand:
    """Результат разбора: имя команды (в нижнем регистре), аргументы и исходный текст."""

    name: str
    args: tuple[str, ...]
    raw: str


class CommandParser:
    """Разбирает команды userbot вида `.name arg1 arg2`."""

    def __init__(self, prefix: str = ".") -> None:
        if not prefix:
            raise ValueError("Префикс команды не может быть пустым")
        self.prefix = prefix

    def parse(self, text: str | None) -> ParsedCommand | None:
        """Возвращает ``ParsedCommand`` или None, если текст не команда (нет префикса, пусто)."""
        if not text:
            return None

        text = text.strip()
        if not text.startswith(self.prefix):
            return None

        body = text[len(self.prefix):].strip()
        if not body:
            return None

        # Аргументы делятся по любым пробельным символам; кавычек и экранирования нет.
        parts = body.split()
        return ParsedCommand(
            name=parts[0].lower(),
            args=tuple(parts[1:]),
            raw=text,
        )
