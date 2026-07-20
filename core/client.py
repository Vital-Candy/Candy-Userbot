# core/client.py
import json
import os
import secrets
import sys
from telethon import TelegramClient
from utils.paths import CONFIG_PATH, PROJECT_ROOT


class UserBot:
    def __init__(self):
        self.client = None
        self._load_config()

    def _load_config(self):
        need_save = False

        if not os.path.exists(CONFIG_PATH):
            config = {
                "api_id": None,
                "api_hash": None,
                "session_name": "userbot_session",
                "update_token": secrets.token_urlsafe(24),
            }
            need_save = True
        else:
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                print(f"❌ config.json повреждён. Удалите его или исправьте вручную ({CONFIG_PATH}).")
                sys.exit(1)
            # Уникальный токен на каждую установку (никогда не общий для всех)
            if not config.get("update_token"):
                config["update_token"] = secrets.token_urlsafe(24)
                need_save = True

        if not config.get("api_id") or not config.get("api_hash"):
            print("\n=== Первый запуск: введите данные API ===")
            print("Получить api_id и api_hash можно на https://my.telegram.org/apps\n")
            try:
                api_id = int(input("api_id: ").strip())
                api_hash = input("api_hash: ").strip()
            except ValueError:
                print("❌ api_id должен быть числом.")
                sys.exit(1)
            except (KeyboardInterrupt, EOFError):
                print("\nОтмена.")
                sys.exit(0)
            if not api_hash:
                print("❌ api_hash не может быть пустым.")
                sys.exit(1)
            config["api_id"] = api_id
            config["api_hash"] = api_hash
            need_save = True

        if need_save:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            print("✅ config.json обновлён.\n")

        if not config.get("api_id") or not config.get("api_hash"):
            raise ValueError("api_id и api_hash должны быть указаны в config.json")

        self.api_id = config["api_id"]
        self.api_hash = config["api_hash"]
        self.session_name = os.path.join(PROJECT_ROOT, config.get("session_name", "userbot_session"))

        self.client = TelegramClient(
            self.session_name,
            self.api_id,
            self.api_hash
        )

    def get_client(self):
        return self.client


userbot_instance = UserBot()
client = userbot_instance.get_client()
