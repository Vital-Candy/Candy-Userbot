# main.py
import asyncio
import os
import sys

from core.client import client
from core.loader import load_modules
from core.dispatcher import setup_dispatcher
from config import VERSION, OWNER
from utils.logger import setup_logger
from utils.paths import ASSETS_DIR
from modules.time_name import shutdown as time_name_shutdown

logger = setup_logger()

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def load_banner():
    path = os.path.join(ASSETS_DIR, "banner.txt")
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

async def main():
    clear_screen()
    banner = load_banner()
    if banner:
        print(banner)
    print(f"✨ UserBot v{VERSION} | Owner: {OWNER}\n")

    try:
        await client.start()
        me = await client.get_me()
        username = f"@{me.username}" if me.username else me.first_name
        print(f"✅ Вошёл как: {username}")

        print("📦 Загрузка модулей...")
        loaded = load_modules()
        if loaded:
            for m in loaded:
                print(f"   ├─ {m}")
        else:
            print("   (нет модулей)")

        setup_dispatcher()
        print("🚀 Бот запущен. Используй .ping для проверки.\n")
        await client.run_until_disconnected()

    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        print(f"❌ Фатальная ошибка: {e}")
    finally:
        # 1. Восстанавливаем оригинальное имя (если часы работали и клиент ещё жив)
        try:
            await time_name_shutdown()
        except Exception as e:
            logger.warning(f"Не удалось восстановить имя: {e}")
        # 2. Отключаем клиент, если ещё не отключён
        if client.is_connected():
            await client.disconnect()
        print("👋 Бот остановлен.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⛔ Остановлено пользователем")