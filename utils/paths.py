# utils/paths.py
"""
Централизованные пути проекта.
Используй Path везде — не os.path.join().
"""
import os
from pathlib import Path

# Корень проекта (папка где лежит main.py)
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

ASSETS_DIR:   Path = PROJECT_ROOT / "assets"
CACHE_DIR:    Path = PROJECT_ROOT / "cache"
LOG_PATH:     Path = PROJECT_ROOT / "userbot.log"
ACCOUNTS_DIR: Path = PROJECT_ROOT / "accounts"

# Директория для скачанных файлов
def _get_download_dir() -> Path:
    if Path("/data/data/com.termux").is_dir() and os.access("/sdcard", os.W_OK):
        return Path("/sdcard/Download/UserBot")
    return Path.home() / "Downloads" / "UserBot"

DOWNLOAD_DIR: Path = _get_download_dir()


def ensure_dirs() -> None:
    """
    Создаёт нужные директории при старте.
    .nomedia запрещает Android Gallery сканировать cache/.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    nomedia = CACHE_DIR / ".nomedia"
    if not nomedia.exists():
        nomedia.touch()
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
