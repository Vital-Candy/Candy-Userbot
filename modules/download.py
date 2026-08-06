from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path

from telethon import events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, DocumentAttributeVideo

import core.client as client_state
from core.dispatcher import register_command
from utils.paths import CACHE_DIR, DOWNLOAD_DIR

logger = logging.getLogger("download")
_handler = None


def _parse_flags(raw: str) -> tuple[bool, bool]:
    """
    Разбирает флаги -c и -p.

    Возвращает (send_to_chat, save_to_download)
    -c : не отправлять в чат
    -p : не сохранять в загрузки
    """
    if not raw:
        return True, True

    parts = raw.split()
    send_to_chat = True
    save_to_download = True

    for flag in parts:
        if flag == "-c":
            send_to_chat = False
        elif flag == "-p":
            save_to_download = False

    # Если оба флага указаны – бессмысленно, исправляем
    if not send_to_chat and not save_to_download:
        send_to_chat = True
        save_to_download = True

    return send_to_chat, save_to_download


def _is_self_destructing_media(message) -> bool:
    """Проверяет, является ли медиа в сообщении самоуничтожающимся."""
    if not message or not message.media:
        return False

    media = message.media

    # Проверка для фото
    if isinstance(media, MessageMediaPhoto):
        return hasattr(media, 'ttl_seconds') and media.ttl_seconds is not None and media.ttl_seconds > 0

    # Проверка для видео / документов (исчезающие видео)
    if isinstance(media, MessageMediaDocument):
        if not media.document:
            return False
        for attr in media.document.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                return hasattr(attr, 'ttl_seconds') and attr.ttl_seconds is not None and attr.ttl_seconds > 0

    return False


def _get_unique_filename(directory: str, base_name: str, ext: str) -> str:
    """Генерирует уникальное имя файла в папке."""
    counter = 1
    filename = f"{base_name}{ext}"
    while os.path.exists(os.path.join(directory, filename)):
        filename = f"{base_name} ({counter}){ext}"
        counter += 1
    return filename


async def download_command(event) -> None:
    """Обработчик команды .download (только исчезающие медиа)."""
    try:
        raw = (event.pattern_match.group(1) or "").strip()
        send_to_chat, save_to_download = _parse_flags(raw)

        # Проверяем, есть ли реплай
        if not event.is_reply:
            await event.edit(
                "❌ <b>Сделай реплай на исчезающее фото или видео.</b>\n\n"
                "Использование: <code>.download [-c] [-p]</code> (реплай на медиа)",
                parse_mode="html"
            )
            return

        reply_msg = await event.get_reply_message()
        if not reply_msg or not reply_msg.media:
            await event.edit("❌ <b>В реплае нет медиа.</b>", parse_mode="html")
            return

        # Проверка на исчезающее медиа
        if not _is_self_destructing_media(reply_msg):
            await event.edit(
                "❌ <b>Это не исчезающее медиа.</b>\n"
                "Команда работает только с самоуничтожающимися фото/видео.",
                parse_mode="html"
            )
            return

        # Скачиваем
        status_msg = await event.edit("⏳ <b>Скачиваю исчезающее медиа...</b>", parse_mode="html")

        # Генерируем имя файла
        timestamp = getattr(reply_msg.date, 'strftime', lambda f: "unknown")("%Y%m%d_%H%M%S")
        base_name = f"selfdestruct_{timestamp}_{reply_msg.id}"
        temp_path = await reply_msg.download_media(file=os.path.join(CACHE_DIR, base_name))

        if not temp_path:
            await status_msg.edit("❌ <b>Не удалось скачать медиа.</b>", parse_mode="html")
            return

        # Определяем расширение
        ext = os.path.splitext(temp_path)[1]
        if not ext:
            ext = ".bin"
        final_name = _get_unique_filename(CACHE_DIR, base_name, ext)
        final_path = os.path.join(CACHE_DIR, final_name)
        os.rename(temp_path, final_path)

        # Отправляем и/или сохраняем
        if send_to_chat:
            try:
                await client_state.client.send_file(event.chat_id, final_path)
            except Exception as e:
                logger.error("Ошибка отправки файла: %s", e)
                await client_state.client.send_message(
                    event.chat_id,
                    f"❌ Ошибка отправки: <code>{str(e)}</code>",
                    parse_mode="html"
                )

        if save_to_download:
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
            dest_name = _get_unique_filename(DOWNLOAD_DIR, base_name, ext)
            dest_path = os.path.join(DOWNLOAD_DIR, dest_name)
            try:
                shutil.copy2(final_path, dest_path)
                await client_state.client.send_message(
                    event.chat_id,
                    f"✅ Сохранено в загрузки: <code>{dest_name}</code>",
                    parse_mode="html"
                )
            except Exception as e:
                logger.error("Ошибка сохранения файла: %s", e)
                await client_state.client.send_message(
                    event.chat_id,
                    f"❌ Не удалось сохранить: <code>{str(e)}</code>",
                    parse_mode="html"
                )

        # Удаляем статусное сообщение
        await status_msg.delete()

    except Exception as e:
        logger.exception("Ошибка в .download: %s", e)
        await event.edit(f"❌ <b>Ошибка:</b> <code>{str(e)}</code>", parse_mode="html")


def init() -> None:
    """Инициализация модуля."""
    global _handler
    if client_state.client is None:
        raise RuntimeError("TelegramClient не установлен")

    # Создаём папки, если их нет
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    register_command(
        "download",
        "Скачать исчезающее фото/видео (self‑destruct)",
        ".download [-c] [-p] (реплай на сообщение)",
        category="Инструменты",
    )
    _handler = client_state.client.add_event_handler(
        download_command,
        events.NewMessage(outgoing=True, pattern=r"^\.download(?:\s+(.*))?$"),
    )
    logger.info("Модуль download зарегистрирован (только исчезающие медиа)")


async def shutdown() -> None:
    """Остановка модуля."""
    global _handler
    if client_state.client is not None and _handler is not None:
        client_state.client.remove_event_handler(_handler)
        _handler = None
        logger.info("Модуль download остановлен")