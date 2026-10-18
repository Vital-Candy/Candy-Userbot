"""``python main.py --check``: проверка окружения без подключения к Telegram и без записи в базу."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

from config import settings as cfg
from storage.database import MIGRATIONS_DIR, load_migrations

# Уровни результата проверки: WARN не влияет на код выхода, FAIL даёт код 2.
OK, WARN, FAIL = "ok", "warn", "fail"
_MARK = {OK: "✓", WARN: "!", FAIL: "✗"}

MIN_PYTHON = (3, 11)  # минимальная версия интерпретатора (asyncio.timeout и др.)

Check = tuple[str, str]  # (уровень, текст)


def _writable(directory: Path) -> bool:
    """Можно ли писать в каталог (создаёт его при необходимости). Проверка реальной записью."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=directory):
            pass
        return True
    except OSError:
        return False


def _database_check(path: Path) -> Check:
    """Сверяет версию схемы базы с последней миграцией. База открывается только на чтение."""
    try:
        latest = max((m.version for m in load_migrations(MIGRATIONS_DIR)), default=0)
    except Exception as exc:
        return FAIL, f"миграции базы не читаются: {exc}"
    if not path.exists():
        return OK, f"база будет создана при первом запуске (схема v{latest})"
    try:
        # mode=ro: проверка не должна создавать файл и менять базу.
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return FAIL, f"база не открывается: {exc}"
    try:
        has = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'"
        ).fetchone()
        row = (
            connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            if has
            else None
        )
        version = int(row[0]) if row else 0
    except (sqlite3.Error, ValueError) as exc:
        return FAIL, f"база повреждена или это не SQLite: {exc}"
    finally:
        connection.close()
    if version > latest:
        return FAIL, f"база новее программы (v{version} при v{latest}): обновите Candy Userbot"
    if version < latest:
        return OK, f"база v{version}, при запуске обновится до v{latest} (с резервной копией)"
    return OK, f"база актуальна (v{version})"


def collect_checks(accounts: Any) -> list[Check]:
    """Список результатов проверок. Ничего не меняет, кроме создания пустых каталогов."""
    checks: list[Check] = []

    version = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info[:2] >= MIN_PYTHON:
        checks.append((OK, f"Python {version}"))
    else:
        checks.append((FAIL, f"Python {version}: нужен {MIN_PYTHON[0]}.{MIN_PYTHON[1]} или новее"))

    if importlib.util.find_spec("telethon") is None:
        checks.append((FAIL, "Telethon не установлен: pip install -r requirements.txt"))
    else:
        checks.append((OK, "Telethon установлен"))

    for label, directory in (("данных", cfg.DATA_DIR), ("баз", cfg.DATABASE_DIR)):
        if _writable(directory):
            checks.append((OK, f"каталог {label} доступен для записи: {directory}"))
        else:
            checks.append((FAIL, f"каталог {label} недоступен для записи: {directory}"))

    log_dir = cfg.settings.log_dir
    if log_dir is None:
        checks.append((OK, "файловые логи выключены"))
    elif _writable(log_dir):
        checks.append((OK, f"логи пишутся в {log_dir}"))
    else:
        checks.append((WARN, f"каталог логов недоступен, логи только в консоль: {log_dir}"))

    # Termux: на общем хранилище Android нет прав доступа, секреты там не защитить.
    if str(cfg.DATA_DIR).startswith("/storage/emulated") or str(cfg.DATA_DIR).startswith("/sdcard"):
        checks.append(
            (WARN, "данные на общем хранилище Android: chmod там не работает, держите data/ в домашней папке Termux")
        )

    checks.append(_database_check(cfg.DATABASE_PATH))

    try:
        accounts.load()
        active = accounts.get_active()
        total = len(accounts.list())
    except Exception as exc:
        checks.append((FAIL, f"аккаунты не читаются: {exc}"))
    else:
        if active is None:
            checks.append((WARN, f"активного аккаунта нет (всего {total}): python main.py --add-account"))
        else:
            if active.session_path.exists():
                checks.append((OK, f"активный аккаунт {active.display_name}, сессия на месте (всего {total})"))
            else:
                checks.append((FAIL, f"у аккаунта {active.display_name} нет файла сессии: --add-account"))
            # Права каталога аккаунта: там лежат сессия и ключи, посторонним доступ не нужен.
            if os.name == "posix":  # на Windows биты прав не имеют смысла
                mode = active.account_dir.stat().st_mode & 0o077
                if mode:
                    checks.append((WARN, f"каталог аккаунта открыт для других пользователей: chmod 700 {active.account_dir}"))

    for message in cfg.settings.warnings:
        checks.append((WARN, f"настройка: {message}"))
    return checks


def run_checks(accounts: Any, out=print) -> int:
    """Печатает отчёт. Код выхода: 0 нет ошибок, 2 есть ошибки (нужен человек)."""
    checks = collect_checks(accounts)
    for level, text in checks:
        out(f"{_MARK[level]} {text}")
    failed = sum(level == FAIL for level, _ in checks)
    warned = sum(level == WARN for level, _ in checks)
    out(
        "\nПроверка не пройдена: ошибок %d, предупреждений %d." % (failed, warned)
        if failed
        else f"\nВсё в порядке (предупреждений: {warned})."
    )
    return 2 if failed else 0
