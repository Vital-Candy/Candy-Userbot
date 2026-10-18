"""Значения по умолчанию. Их можно переопределить переменной окружения или файлом .env."""
from __future__ import annotations

# Имена переменных окружения (или ключей в .env).
# Каталог данных: аккаунты, база, резервные копии. Относительный путь считается от корня проекта.
ENV_DATA_DIR = "CANDY_DATA_DIR"
# Уровень логов: одно из VALID_LOG_LEVELS, регистр не важен.
ENV_LOG_LEVEL = "CANDY_LOG_LEVEL"
# Лимит на один обработчик события, секунды (0 или пусто: без лимита).
ENV_HANDLER_TIMEOUT = "CANDY_HANDLER_TIMEOUT"
# Лимит на выполнение одной команды, секунды (0: без лимита).
ENV_COMMAND_TIMEOUT = "CANDY_COMMAND_TIMEOUT"

DEFAULT_DATA_DIR = "data"  # каталог рядом с проектом
DEFAULT_LOG_LEVEL = "INFO"
# Допустимые значения CANDY_LOG_LEVEL, от подробного к редкому.
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Сколько секунд обработчик события / команда может работать, прежде чем диспетчер
# прервёт его и пойдёт дальше. 0 отключает ограничение.
DEFAULT_HANDLER_TIMEOUT = 30.0  # секунды
DEFAULT_COMMAND_TIMEOUT = 120.0  # секунды; больше, чем у обработчика: команды бывают долгими

# Файловые логи с ротацией. CANDY_LOG_DIR=off отключает запись в файл.
ENV_LOG_DIR = "CANDY_LOG_DIR"  # каталог логов; off, none, 0 или false отключают файл
ENV_LOG_MAX_BYTES = "CANDY_LOG_MAX_BYTES"  # размер одного файла лога, байты (не меньше 1024)
ENV_LOG_BACKUPS = "CANDY_LOG_BACKUPS"  # сколько старых файлов хранить (0: не хранить)
ENV_STOP_TIMEOUT = "CANDY_STOP_TIMEOUT"  # лимит на шаг остановки, секунды
DEFAULT_LOG_DIR = "logs"  # относительный путь считается от корня проекта
DEFAULT_LOG_MAX_BYTES = 1_000_000  # около 1 МБ
DEFAULT_LOG_BACKUPS = 3  # итого до 4 файлов: текущий и три старых
# Лимит (секунды) на каждый шаг остановки. 0 отключает ограничение.
DEFAULT_STOP_TIMEOUT = 20.0

# Обновление из GitHub (.update). Репозиторий в формате владелец/имя.
ENV_UPDATE_REPO = "CANDY_UPDATE_REPO"  # откуда брать обновления: владелец/имя
ENV_UPDATE_BRANCH = "CANDY_UPDATE_BRANCH"  # ветка репозитория
DEFAULT_UPDATE_REPO = "Vital-Candy/Candy-userbot"
DEFAULT_UPDATE_BRANCH = "main"

# Вид терминала: menu (экран с меню) или console (строка команд candy>).
ENV_UI = "CANDY_UI"
DEFAULT_UI = "menu"  # в Termux удобнее меню: ввод номером и Enter
VALID_UI = ("menu", "console")
