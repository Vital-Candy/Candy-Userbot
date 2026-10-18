"""Загрузка и проверка настроек из окружения и ``.env``; модульные константы для остального кода.

Значения по умолчанию и имена переменных лежат в ``config.defaults``, чтение ``.env`` в ``config.env``.
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from config.defaults import (
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_DATA_DIR,
    DEFAULT_HANDLER_TIMEOUT,
    DEFAULT_LOG_BACKUPS,
    DEFAULT_LOG_DIR,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_MAX_BYTES,
    DEFAULT_STOP_TIMEOUT,
    DEFAULT_UI,
    DEFAULT_UPDATE_BRANCH,
    DEFAULT_UPDATE_REPO,
    ENV_COMMAND_TIMEOUT,
    ENV_DATA_DIR,
    ENV_HANDLER_TIMEOUT,
    ENV_LOG_BACKUPS,
    ENV_LOG_DIR,
    ENV_LOG_LEVEL,
    ENV_LOG_MAX_BYTES,
    ENV_STOP_TIMEOUT,
    ENV_UI,
    ENV_UPDATE_BRANCH,
    ENV_UPDATE_REPO,
    VALID_LOG_LEVELS,
    VALID_UI,
)
from config.env import load_env_file

# Корень проекта: относительные пути из настроек (CANDY_DATA_DIR, CANDY_LOG_DIR) считаются от него.
BASE_DIR = Path(__file__).resolve().parent.parent
# Допустимый вид «владелец/имя» репозитория и имени ветки: символы ограничены, чтобы
# значение безопасно попадало в URL загрузки.
_REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_BRANCH = re.compile(r"^[A-Za-z0-9_./-]{1,100}$")


@dataclass(frozen=True, slots=True)
class Settings:
    """Неизменяемый набор настроек, собранный ``load_settings`` из окружения.

    Значения уже проверены: неверные заменены умолчаниями, а причины попали в ``warnings``.
    """

    base_dir: Path  # корень проекта
    data_dir: Path  # абсолютный каталог данных (аккаунты, база, backup)
    log_level: str  # один из VALID_LOG_LEVELS, в верхнем регистре
    warnings: tuple[str, ...] = ()  # сообщения о неверных значениях; main выводит их при старте
    handler_timeout: float = DEFAULT_HANDLER_TIMEOUT  # секунды на обработчик события; 0: без лимита
    command_timeout: float = DEFAULT_COMMAND_TIMEOUT  # секунды на команду; 0: без лимита
    log_dir: Path | None = None  # None: файловые логи выключены
    log_max_bytes: int = DEFAULT_LOG_MAX_BYTES  # размер одного файла лога, байты (от 1024)
    log_backups: int = DEFAULT_LOG_BACKUPS  # число старых файлов лога (от 0)
    stop_timeout: float = DEFAULT_STOP_TIMEOUT  # секунды на шаг остановки; 0: без лимита
    update_repo: str = DEFAULT_UPDATE_REPO  # репозиторий обновлений, «владелец/имя»
    update_branch: str = DEFAULT_UPDATE_BRANCH  # ветка репозитория обновлений
    ui: str = DEFAULT_UI  # вид терминала: "menu" или "console"

    @property
    def accounts_dir(self) -> Path:
        """Каталог профилей и сессий аккаунтов."""
        return self.data_dir / "accounts"

    @property
    def backups_dir(self) -> Path:
        """Каталог резервных копий аккаунтов."""
        return self.data_dir / "backups"

    @property
    def database_dir(self) -> Path:
        """Каталог файла базы данных."""
        return self.data_dir / "database"

    @property
    def database_path(self) -> Path:
        """Путь к файлу SQLite-базы."""
        return self.database_dir / "candy.sqlite3"


def _read_timeout(env: Mapping[str, str], name: str, default: float, warnings: list[str]) -> float:
    """Секунды из переменной ``name``: число не меньше 0. Иначе умолчание и запись в ``warnings``."""
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if not value >= 0 or value == float("inf"):  # отрицательное, NaN, inf
        warnings.append(f"{name}={raw!r} не поддерживается, используется {default:g}")
        return default
    return value


def _read_int(env: Mapping[str, str], name: str, default: int, minimum: int, warnings: list[str]) -> int:
    """Целое не меньше ``minimum`` из переменной ``name``. Иначе умолчание и запись в ``warnings``."""
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = minimum - 1
    if value < minimum:
        warnings.append(f"{name}={raw!r} не поддерживается, используется {default}")
        return default
    return value


def load_settings(env: Mapping[str, str], base_dir: Path = BASE_DIR) -> Settings:
    """Собирает настройки из окружения. Не падает на неверных значениях."""
    warnings: list[str] = []

    raw_dir = (env.get(ENV_DATA_DIR) or DEFAULT_DATA_DIR).strip() or DEFAULT_DATA_DIR
    # Относительный путь привязываем к проекту, а не к текущему каталогу: запуск из любого места.
    data_dir = Path(raw_dir).expanduser()
    if not data_dir.is_absolute():
        data_dir = base_dir / data_dir

    level = (env.get(ENV_LOG_LEVEL) or DEFAULT_LOG_LEVEL).strip().upper()
    if level not in VALID_LOG_LEVELS:
        warnings.append(
            f"{ENV_LOG_LEVEL}={level!r} не поддерживается, используется {DEFAULT_LOG_LEVEL}"
        )
        level = DEFAULT_LOG_LEVEL

    handler_timeout = _read_timeout(env, ENV_HANDLER_TIMEOUT, DEFAULT_HANDLER_TIMEOUT, warnings)
    command_timeout = _read_timeout(env, ENV_COMMAND_TIMEOUT, DEFAULT_COMMAND_TIMEOUT, warnings)

    raw_log_dir = (env.get(ENV_LOG_DIR) or DEFAULT_LOG_DIR).strip() or DEFAULT_LOG_DIR
    log_dir: Path | None
    # Особые значения отключают файловые логи (удобно на устройстве с read-only диском).
    if raw_log_dir.lower() in {"off", "none", "0", "false"}:
        log_dir = None
    else:
        log_dir = Path(raw_log_dir).expanduser()
        if not log_dir.is_absolute():
            log_dir = base_dir / log_dir
    log_max_bytes = _read_int(env, ENV_LOG_MAX_BYTES, DEFAULT_LOG_MAX_BYTES, 1024, warnings)
    log_backups = _read_int(env, ENV_LOG_BACKUPS, DEFAULT_LOG_BACKUPS, 0, warnings)
    stop_timeout = _read_timeout(env, ENV_STOP_TIMEOUT, DEFAULT_STOP_TIMEOUT, warnings)

    repo = (env.get(ENV_UPDATE_REPO) or DEFAULT_UPDATE_REPO).strip()
    if not _REPO.match(repo):
        warnings.append(f"{ENV_UPDATE_REPO}={repo!r} не поддерживается (нужно владелец/имя), используется {DEFAULT_UPDATE_REPO}")
        repo = DEFAULT_UPDATE_REPO
    branch = (env.get(ENV_UPDATE_BRANCH) or DEFAULT_UPDATE_BRANCH).strip()
    if not _BRANCH.match(branch) or ".." in branch:
        warnings.append(f"{ENV_UPDATE_BRANCH}={branch!r} не поддерживается, используется {DEFAULT_UPDATE_BRANCH}")
        branch = DEFAULT_UPDATE_BRANCH
    ui = (env.get(ENV_UI) or DEFAULT_UI).strip().lower()
    if ui not in VALID_UI:
        warnings.append(f"{ENV_UI}={ui!r} не поддерживается (menu или console), используется {DEFAULT_UI}")
        ui = DEFAULT_UI

    return Settings(
        base_dir, data_dir, level, tuple(warnings), handler_timeout, command_timeout,
        log_dir, log_max_bytes, log_backups, stop_timeout, repo, branch, ui,
    )


# Модуль-одиночка: настройки читаются один раз при импорте, ниже удобные псевдонимы для
# остального кода (``from config.settings import DATA_DIR``).
# .env необязателен и не перекрывает уже заданные переменные окружения.
load_env_file(BASE_DIR / ".env")
settings = load_settings(os.environ)

DATA_DIR = settings.data_dir
ACCOUNTS_DIR = settings.accounts_dir
BACKUPS_DIR = settings.backups_dir
DATABASE_DIR = settings.database_dir
DATABASE_PATH = settings.database_path
LOG_LEVEL = settings.log_level
HANDLER_TIMEOUT = settings.handler_timeout
COMMAND_TIMEOUT = settings.command_timeout
STOP_TIMEOUT = settings.stop_timeout
UPDATE_REPO = settings.update_repo
UPDATE_BRANCH = settings.update_branch
UI_MODE = settings.ui


def ensure_directories() -> None:
    """Создаёт каталоги аккаунтов, резервных копий и базы, если их ещё нет."""
    for path in (ACCOUNTS_DIR, BACKUPS_DIR, DATABASE_DIR):
        path.mkdir(parents=True, exist_ok=True)
