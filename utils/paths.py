from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
ACCOUNTS_DIR = PROJECT_ROOT / "accounts"

# Папки для временного хранения и загрузок
CACHE_DIR = PROJECT_ROOT / "cache"
DOWNLOAD_DIR = PROJECT_ROOT / "downloads"

SDCARD = Path("/sdcard")
BACKUP_DIR = (
    SDCARD / "Download" / "Candy-Userbot" / "Backup"
    if SDCARD.exists()
    else PROJECT_ROOT / "backup"
)

LOG_PATH = PROJECT_ROOT / "userbot.log"


def ensure_dirs() -> None:
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
