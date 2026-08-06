from __future__ import annotations

import asyncio
import logging
import shlex

from telethon import events, errors

import core.client as client_state
from core.dispatcher import register_command

logger = logging.getLogger("purge")
_handler = None
_task: asyncio.Task[int] | None = None


def _parse_args(raw: str) -> tuple[int | None, bool, bool]:
    """
    Разбирает аргументы команды.

    Возвращает (count, all_msgs, stop)
    count — число сообщений для удаления (None если не указано)
    all_msgs — True если флаг 'all' присутствует
    stop — True если команда 'stop'
    """
    if not raw:
        return None, False, False

    parts = shlex.split(raw)
    first = parts[0].lower()
    if first == "stop":
        return None, False, True

    try:
        count = int(first)
    except ValueError:
        return None, False, False

    if count <= 0:
        return None, False, False

    all_msgs = False
    if len(parts) > 1 and parts[1].lower() == "all":
        all_msgs = True

    return count, all_msgs, False


async def purge_worker(chat_id: int, count: int, all_msgs: bool) -> int:
    """
    Удаляет сообщения из чата.

    Если all_msgs == False — удаляет только свои (исходящие).
    Возвращает количество реально удалённых сообщений.
    """
    deleted = 0
    limit = count * 5 if not all_msgs else count  # берём запас, чтобы наверняка набрать count

    async for msg in client_state.client.iter_messages(chat_id, limit=limit):
        # Если отмена — выходим
        if asyncio.current_task().cancelled():
            break

        if all_msgs or msg.out:
            try:
                await msg.delete()
                deleted += 1
                if deleted >= count:
                    break
                await asyncio.sleep(0.3)
            except errors.FloodWaitError as e:
                logger.warning("FloodWait %s с, жду...", e.seconds)
                await asyncio.sleep(e.seconds)
                # Повторяем удаление после ожидания
                try:
                    await msg.delete()
                    deleted += 1
                    if deleted >= count:
                        break
                    await asyncio.sleep(0.3)
                except Exception as e2:
                    logger.error("Ошибка повторного удаления: %s", e2)
                    break
            except asyncio.CancelledError:
                logger.info("Очистка остановлена пользователем")
                break
            except Exception as e:
                logger.error("Ошибка удаления сообщения: %s", e)
                break

    return deleted


async def purge_command(event) -> None:
    """Обработчик команды .purge."""
    global _task

    try:
        raw = (event.pattern_match.group(1) or "").strip()
        count, all_msgs, stop = _parse_args(raw)

        # Остановка активной задачи
        if stop:
            if _task is not None and not _task.done():
                _task.cancel()
                try:
                    await _task
                except asyncio.CancelledError:
                    pass
                _task = None
                await event.edit("⏹ <b>Очистка остановлена.</b>", parse_mode="html")
            else:
                await event.edit("⚠️ <b>Нет активной очистки.</b>", parse_mode="html")
            return

        # Проверка аргументов
        if count is None:
            await event.edit(
                "❌ <b>Используй:</b>\n"
                "<code>.purge &lt;количество&gt; [all]</code>\n"
                "<code>.purge stop</code>",
                parse_mode="html"
            )
            return

        if count > 100:
            await event.edit("❌ <b>Максимум 100 сообщений за раз.</b>", parse_mode="html")
            return

        # Отмена предыдущей задачи, если есть
        if _task is not None and not _task.done():
            _task.cancel()
            try:
                await _task
            except asyncio.CancelledError:
                pass
            _task = None

        # Удаляем команду
        await event.delete()

        # Запускаем задачу
        chat_id = event.chat_id
        _task = asyncio.create_task(purge_worker(chat_id, count, all_msgs))
        try:
            deleted = await _task
            msg = await client_state.client.send_message(
                chat_id,
                f"✅ <b>Удалено {deleted} сообщений.</b>",
                parse_mode="html"
            )
            # Автоудаление через 2 секунды
            await asyncio.sleep(2)
            await msg.delete()
        except asyncio.CancelledError:
            # Если задача была отменена, не отправляем финальное сообщение
            pass
        finally:
            _task = None

    except Exception as e:
        logger.exception("Ошибка в .purge: %s", e)
        await event.edit(f"❌ <b>Ошибка:</b> <code>{str(e)}</code>", parse_mode="html")


def init() -> None:
    """Инициализация модуля."""
    global _handler
    if client_state.client is None:
        raise RuntimeError("TelegramClient не установлен")

    register_command(
        "purge",
        "Очистка сообщений",
        ".purge <количество> [all] | .purge stop",
        category="Инструменты",
    )
    _handler = client_state.client.add_event_handler(
        purge_command,
        events.NewMessage(outgoing=True, pattern=r"^\.purge(?:\s+(.*))?$"),
    )
    logger.info("Модуль purge зарегистрирован")


async def shutdown() -> None:
    """Остановка модуля."""
    global _handler, _task
    # Отменяем активную задачу, если есть
    if _task is not None and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None

    # Удаляем обработчик
    if client_state.client is not None and _handler is not None:
        client_state.client.remove_event_handler(_handler)
        _handler = None
        logger.info("Модуль purge остановлен")