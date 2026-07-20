# modules/update.py
"""Обновление бота через git pull из репозитория, из которого он был установлен."""
import os
import sys
import asyncio
import logging
from telethon import events
from core.dispatcher import register_command
from core.client import client
from utils.paths import PROJECT_ROOT

logger = logging.getLogger("update")
_registered_handlers = []


def init():
    global _registered_handlers
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []

    register_command(
        "update",
        "Обновить бота из GitHub",
        ".update",
        "Выполняет git pull в папке бота и перезапускает процесс.\n"
        "Требует, чтобы бот был установлен через git clone.\n"
        "Локальные изменения в отслеживаемых файлах будут утеряны (git reset --hard).",
        category="система"
    )
    h = client.add_event_handler(update_handler, events.NewMessage(outgoing=True, pattern=r"^\.update$"))
    _registered_handlers.append(h)
    logger.info("Модуль update зарегистрирован")


def shutdown():
    global _registered_handlers
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []
    logger.info("Модуль update: обработчики удалены")


async def _run(*cmd):
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=PROJECT_ROOT,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(errors="ignore"), stderr.decode(errors="ignore")


async def update_handler(event):
    if not os.path.isdir(os.path.join(PROJECT_ROOT, ".git")):
        await event.edit("❌ Это не git-репозиторий. Обновление недоступно — переустановите через `git clone`.")
        return

    status_msg = await event.edit("🔄 Проверяю обновления...")

    code, _, err = await _run("git", "fetch", "--quiet")
    if code != 0:
        await status_msg.edit(f"❌ Не удалось получить обновления:\n`{err.strip()[:500]}`")
        return

    code, local, _ = await _run("git", "rev-parse", "HEAD")
    code2, remote, _ = await _run("git", "rev-parse", "@{u}")
    if code != 0 or code2 != 0:
        await status_msg.edit("❌ Не удалось определить текущую/удалённую версию (нет upstream-ветки?).")
        return

    if local.strip() == remote.strip():
        await status_msg.edit("✅ Уже установлена последняя версия.")
        return

    await status_msg.edit("⬇️ Обновление найдено, применяю (git reset --hard)...")
    # config.json, *.session, cache/ и т.д. в .gitignore — pull их не тронет
    code, _, err = await _run("git", "reset", "--hard", "@{u}")
    if code != 0:
        await status_msg.edit(f"❌ Ошибка обновления:\n`{err.strip()[:500]}`")
        return

    await status_msg.edit("✅ Обновлено. Перезапускаю бота...")
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)
