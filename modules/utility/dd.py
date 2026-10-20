"""Команда .dd: сохранить медиа из сообщения, на которое ответили.

Синтаксис: ответом на сообщение ``.dd`` или ``.dd -c``. Файл сначала скачивается в каталог кэша
(``data/cache/dd``), затем копируется в каталог загрузок, а копия в кэше удаляется. Сообщение
с командой сразу удаляется, результат приходит в «Избранное». Флаг ``-c`` дополнительно
отправляет сохранённый файл в этот чат.

Не сохраняются: самоуничтожающиеся медиа (фото, видео, кружки с таймером) и сообщения из чатов
с защитой от копирования. Отправитель выбрал для них такие правила, и модуль их не обходит.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from config.settings import DATA_DIR
from core.errors import UserError
from core.module import Module
from core.reply import answer
from utils.logger import logger

ENV_DOWNLOADS = "CANDY_DOWNLOADS_DIR"
USAGE = "Использование: ответьте на сообщение с медиа командой .dd или .dd -c"

DETAILS = """\
Сохраняет медиа (фото, видео, документ, голосовое, кружок, стикер и т. д.) из сообщения, на которое вы ответили. Сообщение с командой сразу удаляется, результат приходит в «Избранное».

.dd — скачать и сохранить в каталог загрузок
.dd -c — то же и сразу отправить сохранённый файл в этот чат

Файл сначала скачивается в кэш (data/cache/dd), затем копируется в загрузки, а копия в кэше удаляется. Каталог загрузок: переменная CANDY_DOWNLOADS_DIR в .env; если её нет, то ~/storage/downloads/Candy (в Termux сначала выполните termux-setup-storage), а иначе data/downloads.

Не сохраняются: самоуничтожающиеся медиа (с таймером) и сообщения из чатов с защитой от копирования, чтобы не обходить выбор отправителя.

Права: только владелец аккаунта."""


def downloads_dir(env=None, home: Path | None = None) -> Path:
    """Каталог загрузок: из ``CANDY_DOWNLOADS_DIR``, иначе Termux-хранилище, иначе ``data/downloads``."""
    env = os.environ if env is None else env
    value = (env.get(ENV_DOWNLOADS) or "").strip()
    if value:
        return Path(value).expanduser()
    storage = (home or Path.home()) / "storage" / "downloads"
    if storage.is_dir():
        return storage / "Candy"
    return DATA_DIR / "downloads"


def cache_dir() -> Path:
    """Каталог кэша для скачивания перед копированием в загрузки."""
    return DATA_DIR / "cache" / "dd"


def unique_path(directory: Path, name: str) -> Path:
    """Путь в каталоге, не совпадающий с существующим файлом (``имя (1).ext``, ``имя (2).ext``)."""
    target = directory / name
    stem, suffix = Path(name).stem, Path(name).suffix
    number = 0
    while target.exists():
        number += 1
        target = directory / f"{stem} ({number}){suffix}"
    return target


def copy_from_cache(cached: Path, target_dir: Path) -> Path:
    """Копирует файл из кэша в каталог загрузок и удаляет копию в кэше. Возвращает новый путь."""
    target_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(target_dir, cached.name)
    shutil.copy2(cached, target)
    try:
        cached.unlink()
    except OSError as exc:
        logger.debug("Не удалось удалить файл из кэша %s: %s", cached, exc)
    return target


def refusal_reason(message) -> str | None:
    """Почему сообщение нельзя сохранять (или None, если можно)."""
    if getattr(message, "media", None) is None:
        return "в сообщении нет медиа."
    if getattr(getattr(message, "media", None), "ttl_seconds", None):
        return "это самоуничтожающееся медиа: такие не сохраняются."
    if getattr(message, "noforwards", False) or getattr(getattr(message, "chat", None), "noforwards", False):
        return "в этом чате включена защита от копирования."
    return None


class DDModule(Module):
    """Команда ``.dd``: сохранение медиа из сообщения-ответа."""

    name = "utility.dd"
    description = "Команда .dd: сохранить медиа из сообщения"
    # Необязательный: без него userbot работает, сбой запуска только пришлёт уведомление.

    def __init__(self, app) -> None:
        super().__init__(app)
        self._tasks: set[asyncio.Task] = set()
        self._downloads = downloads_dir  # подменяется в тестах
        self._cache = cache_dir

    async def start(self) -> None:
        """Регистрирует команду ``.dd``."""
        self.app.dispatcher.register_command(
            "dd",
            self.dd_command,
            description="сохранить медиа из сообщения (-c: и отправить в чат)",
            usage=".dd [-c] (ответом на сообщение)",
            priority=20,
            details=DETAILS,
        )

    async def stop(self) -> None:
        """Снимает команду и отменяет незавершённые скачивания."""
        self.app.dispatcher.unregister_command("dd")
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def dd_command(self, event) -> None:
        """``.dd [-c]``: удаляет команду и в фоне скачивает медиа из сообщения-ответа."""
        command = self.app.dispatcher.get_command(event)
        args = [item.lower() for item in (command.args if command else [])]
        if any(item != "-c" for item in args) or len(args) > 1:
            await answer(event, USAGE)
            return
        message = await event.get_reply_message()
        if message is None:
            await answer(event, USAGE)
            return
        chat_id = getattr(event, "chat_id", None)
        # Сначала убираем команду: так в чате никто не заметит.
        try:
            await event.delete()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Не удалось удалить сообщение с командой .dd: %s", exc)
        task = asyncio.get_running_loop().create_task(self._save(message, chat_id, send=bool(args)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _save(self, message, chat_id, *, send: bool) -> None:
        """Скачивает, копирует в загрузки, при ``send`` отправляет в чат; итог приходит в «Избранное»."""
        notify = self.app.notify_owner
        reason = refusal_reason(message)
        if reason:
            await notify(f"ℹ️ .dd: {reason}")
            return
        try:
            cache = self._cache()
            cache.mkdir(parents=True, exist_ok=True)
            downloaded = await self.app.client.download_media(message, file=str(cache) + os.sep)
            if not downloaded:
                raise UserError("Telegram не отдал файл.")
            saved = await asyncio.to_thread(copy_from_cache, Path(downloaded), self._downloads())
            if send and chat_id is not None:
                await self.app.client.send_file(chat_id, str(saved))
        except asyncio.CancelledError:
            raise
        except UserError as exc:
            await notify(f"❌ .dd: {exc}")
        except Exception as exc:
            logger.exception("Ошибка .dd.")
            reason = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            await notify(f"❌ .dd не удалось: {reason}")
        else:
            tail = " и отправлено в чат" if send else ""
            await notify(f"✅ .dd: сохранено{tail}:\n`{saved}`")
