"""Общий отчёт о состоянии: собирается из жизненного цикла, модулей, задач и плагинов."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.background import FAILING
from core.lifecycle import RUNNING

OK = "ok"
DEGRADED = "degraded"
DOWN = "down"

_ICON = {OK: "✅", DEGRADED: "⚠️", DOWN: "❌"}
_TITLE = {OK: "работает", DEGRADED: "работает с проблемами", DOWN: "не работает"}


@dataclass(slots=True)
class HealthReport:
    """Снимок состояния userbot: общий статус, счётчики и список проблем."""

    status: str
    state: str
    version: str
    uptime: float | None
    connected: bool
    database: bool
    problems: list[str] = field(default_factory=list)
    modules_started: int = 0
    modules_total: int = 0
    tasks_failing: int = 0
    tasks_total: int = 0
    plugins_loaded: int = 0
    plugins_total: int = 0

    @property
    def ok(self) -> bool:
        """True, если общий статус OK (без деградации)."""
        return self.status == OK

    def lines(self) -> list[str]:
        """Отчёт строками для ``.status``: заголовок, связь, счётчики и проблемы."""
        head = f"{_ICON[self.status]} Состояние: {_TITLE[self.status]} ({self.state}), ядро {self.version}"
        if self.uptime is not None:
            head += f", аптайм {format_uptime(self.uptime)}"
        lines = [
            head,
            f"Telegram: {'подключён' if self.connected else 'нет связи'}, "
            f"база: {'открыта' if self.database else 'закрыта'}",
            f"Модули {self.modules_started}/{self.modules_total}, "
            f"плагины {self.plugins_loaded}/{self.plugins_total}, "
            f"задач {self.tasks_total} (сбоит {self.tasks_failing})",
        ]
        lines += [f"• {problem}" for problem in self.problems]
        return lines


def format_uptime(seconds: float) -> str:
    """Человекочитаемый аптайм: две старшие единицы (``2 д 3 ч``, ``5 мин 7 с``)."""
    total = int(seconds)
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days} д {hours} ч"
    if hours:
        return f"{hours} ч {minutes} мин"
    if minutes:
        return f"{minutes} мин {secs} с"
    return f"{secs} с"


def _safe(call, default):
    # Отчёт строится, когда что-то уже сломано, поэтому сбой источника даёт значение по умолчанию.
    try:
        return call()
    except Exception:
        return default


def build_health(app: Any) -> HealthReport:
    """Строит отчёт. Никогда не бросает исключений: он сам нужен, когда что-то сломано.

    DOWN: приложение не в RUNNING, нет связи с Telegram, база закрыта или не запущен
    обязательный модуль. DEGRADED: упал необязательный модуль или плагин, либо
    фоновая задача сбоит. Иначе OK.
    """
    lifecycle = getattr(app, "lifecycle", None)
    state = lifecycle.state if lifecycle is not None else RUNNING
    uptime = lifecycle.uptime if lifecycle is not None else None

    client = getattr(app, "client", None)
    connected = bool(client is not None and _safe(client.is_connected, False))
    storage = getattr(app, "storage", None)
    database = bool(storage is not None and _safe(lambda: storage.database.is_open, False))

    modules = _safe(app.modules.states, [])
    plugins = _safe(app.plugins.states, [])
    tasks = _safe(app.background.list, [])

    down: list[str] = []
    degraded: list[str] = []

    if state != RUNNING:
        down.append(f"приложение в состоянии {state}")
    else:
        # Связь и базу проверяем только в RUNNING: на старте и остановке они закономерно закрыты.
        if not connected:
            down.append("нет связи с Telegram")
        if not database:
            down.append("база данных закрыта")
    for item in modules:
        if item.started:
            continue
        reason = f"модуль {item.module.name}: {_short(item.error) or 'остановлен'}"
        (down if item.required else degraded).append(reason)
    for item in plugins:
        if item.failed:
            degraded.append(f"плагин {item.name}: {_short(getattr(item, 'error', None)) or 'ошибка'}")
    failing = [task for task in tasks if task.status == FAILING]
    for task in failing:
        degraded.append(f"задача {task.name}: сбоев подряд {task.consecutive_failures}")

    status = DOWN if down else (DEGRADED if degraded else OK)
    return HealthReport(
        status=status,
        state=state,
        version=_version(),
        uptime=uptime,
        connected=connected,
        database=database,
        problems=down + degraded,
        modules_started=sum(1 for item in modules if item.started),
        modules_total=len(modules),
        tasks_failing=len(failing),
        tasks_total=len(tasks),
        plugins_loaded=sum(1 for item in plugins if item.loaded),
        plugins_total=len(plugins),
    )


def _short(text: str | None, limit: int = 100) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _version() -> str:
    from core.version import CORE_VERSION

    return CORE_VERSION
