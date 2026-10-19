"""Стили часов для имени: как выглядит время и как узнать в имени «наши» часы.

Модуль чистый: не знает про Telegram и не читает настройки, поэтому легко проверяется тестами.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Эмодзи-циферблаты: целые часы (12, 1, 2 ... 11) и половины (12:30, 1:30 ... 11:30).
_FULL = "🕛🕐🕑🕒🕓🕔🕕🕖🕗🕘🕙🕚"
_HALF = "🕧🕜🕝🕞🕟🕠🕡🕢🕣🕤🕥🕦"


def _table(first: str) -> dict[int, str]:
    """Таблица замены цифр 0-9 на десять подряд идущих символов, начиная с ``first``."""
    return str.maketrans("0123456789", "".join(chr(ord(first) + i) for i in range(10)))


_BOLD = _table("\U0001D7CE")  # 𝟎𝟏𝟐
_DOUBLE = _table("\U0001D7D8")  # 𝟘𝟙𝟚
_SANS = _table("\U0001D7E2")  # 𝟢𝟣𝟤
_MONO = _table("\U0001D7F6")  # 𝟶𝟷𝟸
_FULLWIDTH = _table("０")  # ０１２
_CIRCLED = str.maketrans("0123456789", "⓪①②③④⑤⑥⑦⑧⑨")
_BLACK_CIRCLED = str.maketrans("0123456789", "⓿❶❷❸❹❺❻❼❽❾")
_SUPER = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def _hm(hour: int, minute: int) -> str:
    """Время в виде ``ЧЧ:ММ``."""
    return f"{hour:02d}:{minute:02d}"


def _emoji_clock(hour: int, minute: int) -> str:
    """Эмодзи-циферблат, ближайший к времени (с точностью до получаса)."""
    slot = ((hour * 60 + minute + 15) // 30) % 24
    faces = _FULL if slot % 2 == 0 else _HALF
    return faces[(slot // 2) % 12]


def _twelve_hour(hour: int, minute: int) -> str:
    """12-часовой формат с AM/PM и без ведущего нуля у часа."""
    return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def _styled(table: dict[int, str]) -> Callable[[int, int], str]:
    """Стиль «обычное время, цифры заменены по таблице»."""
    return lambda hour, minute: _hm(hour, minute).translate(table)


@dataclass(frozen=True, slots=True)
class Style:
    """Стиль часов: номер для пользователя, название и функция вывода времени."""

    number: int
    title: str
    render: Callable[[int, int], str]


_DEFINITIONS: tuple[tuple[str, Callable[[int, int], str]], ...] = (
    ("обычный", _hm),
    ("эмодзи-циферблат", lambda h, m: f"{_emoji_clock(h, m)} {_hm(h, m)}"),
    ("будильник", lambda h, m: f"⏰ {_hm(h, m)}"),
    ("наручные часы", lambda h, m: f"⌚ {_hm(h, m)}"),
    ("квадратные скобки", lambda h, m: f"[{_hm(h, m)}]"),
    ("круглые скобки", lambda h, m: f"({_hm(h, m)})"),
    ("кавычки", lambda h, m: f"「{_hm(h, m)}」"),
    ("чёрточки", lambda h, m: f"| {_hm(h, m)} |"),
    ("звёздочки", lambda h, m: f"✦ {_hm(h, m)} ✦"),
    ("точка", lambda h, m: f"{h:02d}·{m:02d}"),
    ("12 часов AM/PM", _twelve_hour),
    ("полная ширина", _styled(_FULLWIDTH)),
    ("жирные цифры", _styled(_BOLD)),
    ("двойные цифры", _styled(_DOUBLE)),
    ("без засечек", _styled(_SANS)),
    ("моноширинные", _styled(_MONO)),
    ("в кружках", _styled(_CIRCLED)),
    ("в чёрных кружках", _styled(_BLACK_CIRCLED)),
    ("верхний индекс", _styled(_SUPER)),
    ("нижний индекс", _styled(_SUB)),
    ("циферблат и жирные", lambda h, m: f"{_emoji_clock(h, m)} {_hm(h, m).translate(_BOLD)}"),
    ("секундомер и моно", lambda h, m: f"⏱ {_hm(h, m).translate(_MONO)}"),
)

STYLES: tuple[Style, ...] = tuple(
    Style(number, title, render) for number, (title, render) in enumerate(_DEFINITIONS, start=1)
)
STYLE_COUNT = len(STYLES)
MAX_CLOCK_CHARS = 12  # длиннейшая запись часов (проверяется тестом), в символах


def get_style(number: int) -> Style:
    """Стиль по номеру (с 1). Неверный номер: ``ValueError``."""
    if not isinstance(number, int) or not 1 <= number <= STYLE_COUNT:
        raise ValueError(f"номер стиля от 1 до {STYLE_COUNT}")
    return STYLES[number - 1]


def utf16_len(text: str) -> int:
    """Длина в единицах UTF-16: так надёжнее всего оценивать лимит длины имени в Telegram."""
    return len(text.encode("utf-16-le")) // 2


def render_time(number: int, hour: int, minute: int) -> str:
    """Время ``hour:minute`` в стиле ``number``."""
    return get_style(number).render(hour, minute)


@lru_cache(maxsize=None)
def max_length(number: int) -> int:
    """Самая длинная запись стиля по всем 1440 минутам суток (в единицах UTF-16)."""
    style = get_style(number)
    return max(utf16_len(style.render(h, m)) for h in range(24) for m in range(60))


@lru_cache(maxsize=2)
def _renders_of(number: int) -> frozenset[str]:
    """Все 1440 записей одного стиля (малый кэш: обычно проверяется выбранный стиль)."""
    style = get_style(number)
    return frozenset(style.render(h, m) for h in range(24) for m in range(60))


def is_clock_text(text: str, prefer: int | None = None) -> bool:
    """True, если ``text`` это запись часов какого-либо стиля.

    Сначала проверяется стиль ``prefer`` по маленькому кэшу. Остальные стили перебираются без
    хранения: так не держим в памяти таблицу всех 30 тысяч записей ради редкой проверки.
    """
    if not text or len(text) > MAX_CLOCK_CHARS:
        return False  # самая длинная запись короче: длинные суффиксы даже не перебираем
    if prefer is not None and text in _renders_of(prefer):
        return True
    return any(
        style.render(hour, minute) == text
        for style in STYLES
        if style.number != prefer
        for hour in range(24)
        for minute in range(60)
    )


def strip_clock(name: str, prefer: int | None = None) -> str:
    """Убирает с конца имени часы вида ``<имя> <запись часов>``; если их нет, возвращает имя как есть."""
    # Запись может сама содержать пробелы (``| 12:34 |``), поэтому пробуем каждый пробел слева направо:
    # первый подходящий даёт самый длинный суффикс.
    for index, char in enumerate(name):
        if char == " " and index > 0 and is_clock_text(name[index + 1 :], prefer):
            return name[:index]
    return name


def is_ours(current: str, base: str, prefer: int | None = None) -> bool:
    """True, если ``current`` это ``base`` либо ``base`` с нашими часами на конце."""
    if current == base:
        return True
    prefix = base + " "
    return current.startswith(prefix) and is_clock_text(current[len(prefix) :], prefer)


# ---------------------------------------------------------------- часовой пояс

_OFFSET = re.compile(r"^(?:utc|gmt)?\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?$", re.IGNORECASE)
AUTO = "auto"


def parse_timezone(spec: str) -> tuple[str, tzinfo | None]:
    """Разбирает часовой пояс: ``auto`` (часы устройства), смещение (``+5``, ``-03:30``) или имя
    (``Asia/Samarkand``). Возвращает (нормализованная запись, пояс; ``None`` для ``auto``).

    Неизвестный пояс: ``ValueError`` с понятным текстом.
    """
    text = spec.strip()
    if text.lower() in {"", AUTO, "авто"}:
        return AUTO, None
    match = _OFFSET.match(text)
    if match:
        sign, hours, minutes = match.group(1), int(match.group(2)), int(match.group(3) or 0)
        if hours > 14 or minutes > 59:
            raise ValueError("смещение должно быть от -14:00 до +14:00")
        delta = timedelta(hours=hours, minutes=minutes)
        offset = delta if sign == "+" else -delta
        return f"{sign}{hours:02d}:{minutes:02d}", timezone(offset)
    try:
        return text, ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError(
            "не знаю такой пояс. Примеры: +5, -3:30, Asia/Samarkand, auto (по часам устройства)"
        ) from None


def moment(epoch: float, tz: tzinfo | None) -> datetime:
    """Момент ``epoch`` в поясе ``tz`` (``None``: часовой пояс устройства)."""
    if tz is None:
        return datetime.fromtimestamp(epoch).astimezone()
    return datetime.fromtimestamp(epoch, tz)


def describe_timezone(spec: str, tz: tzinfo | None, epoch: float) -> str:
    """Подпись пояса для ответа: ``UTC+5`` или ``UTC+5:30`` (для ``auto`` с пометкой про устройство)."""
    offset = moment(epoch, tz).utcoffset() or timedelta(0)
    total = int(offset.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    hours, minutes = divmod(abs(total), 60)
    label = f"UTC{sign}{hours}" + (f":{minutes:02d}" if minutes else "")
    return label + (" (по часам устройства)" if spec == AUTO else "")
