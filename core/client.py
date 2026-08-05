from telethon import TelegramClient

client: TelegramClient | None = None


def set_client(value: TelegramClient | None) -> None:
    global client
    client = value
