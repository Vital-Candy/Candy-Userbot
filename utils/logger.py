# utils/logger.py
import logging
from utils.paths import LOG_PATH


def setup_logger():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_PATH, encoding="utf-8")
        ]
    )
    # Убираем лишние логи от telethon
    logging.getLogger("telethon").setLevel(logging.WARNING)
    return logging.getLogger("main")
