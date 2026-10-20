"""Безопасное оформление текста для ответов в Telegram (Markdown).

Ответы userbot идут с включённым Markdown, поэтому чужой текст (био, имя) нельзя вставлять
как есть: он мог бы сломать оформление или превратиться в ссылку. ``code`` кладёт значение
в моноширинный фрагмент: в Telegram по нему достаточно нажать, чтобы скопировать.
"""
from __future__ import annotations

# Двойные символы включают оформление в разборе Markdown; между ними вставляется невидимый
# пробел нулевой ширины, и оформление не срабатывает.
_ZERO_WIDTH = "​"
_DOUBLES = ("**", "__", "~~", "||")


def clean(value: object) -> str:
    """Делает чужой текст безопасным для Markdown, почти не меняя его вид."""
    text = str(value).replace("`", "'")
    for pair in _DOUBLES:
        while pair in text:
            text = text.replace(pair, pair[0] + _ZERO_WIDTH + pair[1])
    return text.replace("](", "]" + _ZERO_WIDTH + "(")


def code(value: object) -> str:
    """Значение в моноширинном шрифте (копируется нажатием)."""
    return f"`{clean(value)}`"
