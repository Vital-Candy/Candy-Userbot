# utils/paths.py
"""Единое место для путей проекта, чтобы модули не дублировали логику."""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
CACHE_DIR = os.path.join(PROJECT_ROOT, "cache", ".nomedia")
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")
LOG_PATH = os.path.join(PROJECT_ROOT, "userbot.log")

_TERMUX_DOWNLOADS = "/sdcard/Download/UserBot"


def get_download_dir() -> str:
    """На Termux (Android) — общая папка загрузок, иначе — домашняя папка пользователя."""
    if os.path.isdir("/data/data/com.termux") and os.access("/sdcard", os.W_OK):
        return _TERMUX_DOWNLOADS
    return os.path.join(os.path.expanduser("~"), "Downloads", "UserBot")


DOWNLOAD_DIR = get_download_dir()


def is_termux() -> bool:
    return os.path.isdir("/data/data/com.termux")
