"""Разбор аргументов команды ``.spam "<текст>" [повторов] [-d пауза]``.

Текст берётся целиком между первой кавычкой и последней кавычкой, после которой идут
только допустимые параметры. Кавычки внутри текста не считаются:
``.spam "скажи "привет"" 3 -d 0.5`` отправит ``скажи "привет"`` три раза.
Функции чистые (без Telegram), поэтому их удобно проверять тестами.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from core.errors import UserError

DEFAULT_COUNT = 1
DEFAULT_DELAY = 1.0  # секунд между сообщениями
MAX_COUNT = 200
MIN_DELAY = 0.1
MAX_DELAY = 3600.0
MAX_TEXT = 4096  # лимит Telegram на длину сообщения

OPEN_QUOTES = ('"', "“", "«")  # «умные» кавычки клавиатур тоже подходят
CLOSE_QUOTES = ('"', "”", "»")

USAGE = (
    'Использование: .spam "<текст>" [повторов] [-d пауза]\n'
    ".spam stop — остановить\n"
    'Пример: .spam "привет" 3 -d 0.5'
)


@dataclass(slots=True, frozen=True)
class SpamRequest:
    """Разобранная команда: текст, число повторов и пауза в секундах."""

    text: str
    count: int
    delay: float


def _parse_tail(tail: str) -> tuple[int | None, float | None] | None:
    """Разбирает хвост после закрывающей кавычки: число и/или ``-d <пауза>``.

    Возвращает ``(повторов, пауза)`` (каждое может быть None) или None, если хвост не подходит.
    """
    tokens = tail.split()
    count: int | None = None
    delay: float | None = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "-d":
            if delay is not None or index + 1 >= len(tokens):
                return None
            try:
                delay = float(tokens[index + 1].replace(",", "."))
            except ValueError:
                return None
            if not math.isfinite(delay):
                return None
            index += 2
        elif token.isdigit() and count is None:
            count = int(token)
            index += 1
        else:
            return None
    return count, delay


def parse_spam(rest: str) -> SpamRequest:
    """Разбирает текст после ``.spam``; при ошибке бросает ``UserError`` с подсказкой."""
    rest = rest.strip()
    if not rest or rest[0] not in OPEN_QUOTES:
        raise UserError(USAGE)
    # Ищем закрывающую кавычку с конца: последняя, после которой хвост разбирается, и есть конец текста.
    closers = [i for i in range(len(rest) - 1, 0, -1) if rest[i] in CLOSE_QUOTES]
    if not closers:
        raise UserError('Не нашёл закрывающую кавычку.\n' + USAGE)
    for position in closers:
        parsed = _parse_tail(rest[position + 1:])
        if parsed is not None:
            break
    else:
        raise UserError("Не понял параметры после текста.\n" + USAGE)

    text = rest[1:position]
    if not text.strip():
        raise UserError("Текст пустой.\n" + USAGE)
    if len(text) > MAX_TEXT:
        raise UserError(f"Текст длиннее {MAX_TEXT} символов (лимит Telegram).")
    count = DEFAULT_COUNT if parsed[0] is None else parsed[0]
    delay = DEFAULT_DELAY if parsed[1] is None else parsed[1]
    if not 1 <= count <= MAX_COUNT:
        raise UserError(f"Повторов может быть от 1 до {MAX_COUNT}.")
    if not MIN_DELAY <= delay <= MAX_DELAY:
        raise UserError(f"Пауза может быть от {MIN_DELAY:g} до {MAX_DELAY:g} секунд.")
    return SpamRequest(text, count, delay)
