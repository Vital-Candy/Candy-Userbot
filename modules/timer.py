# modules/timer.py
import asyncio
import logging
from telethon import events
from core.dispatcher import register_command
from core.client import client
from utils.tools import get_args

logger = logging.getLogger("timer")
_registered_handlers = []

def init():
    global _registered_handlers
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []

    register_command(
    "timer",
    "Таймер с уведомлением",
    ".timer <сек> | .timer <мин.сек> | .timer <час.мин.сек>",
    "Примеры:\n.timer 10\n.timer 1.30\n.timer 2.00.00",
    category="инструменты"
    )
    h = client.add_event_handler(timer_handler, events.NewMessage(outgoing=True, pattern=r"^\.timer(?: (.+))?"))
    _registered_handlers.append(h)
    logger.info("Модуль timer зарегистрирован")

def shutdown():
    global _registered_handlers
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []
    logger.info("Модуль timer: обработчики удалены")

def parse_time(args):
    if not args:
        return None
    time_str = args[0]
    parts = time_str.split(".")
    try:
        if len(parts) == 1:
            seconds = int(parts[0])
        elif len(parts) == 2:
            minutes = int(parts[0])
            seconds = int(parts[1])
            seconds += minutes * 60
        elif len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
            seconds += hours * 3600 + minutes * 60
        else:
            return None
        if seconds <= 0:
            return None
        return seconds
    except ValueError:
        return None

async def timer_handler(event):
    args = get_args(event)
    total_seconds = parse_time(args)
    if total_seconds is None:
        await event.edit("❌ Неверный формат. Пример: `.timer 10` или `.timer 5.30`")
        return
    if total_seconds > 86400:
        await event.edit("❌ Максимум 24 часа.")
        return

    await event.edit(f"⏳ Таймер на {total_seconds} сек запущен.")
    start_time = asyncio.get_event_loop().time()
    message = event

    # Определяем режим обновления
    short_mode = total_seconds <= 30
    long_update_interval = 30   # секунд между обновлениями для длинных таймеров
    final_countdown = 10       # последние секунды, когда включается ежесекундный отсчёт

    try:
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            remaining = total_seconds - int(elapsed)
            if remaining <= 0:
                break

            if short_mode:
                # Каждую секунду обновляем
                await message.edit(f"⏳ Осталось: {remaining} сек...")
                await asyncio.sleep(1)
            else:
                # Длинный таймер
                if remaining <= final_countdown:
                    # За 10 секунд до конца – ежесекундный обратный отсчёт
                    await message.edit(f"⏳ До конца: {remaining} сек...")
                    await asyncio.sleep(1)
                else:
                    # Редкое обновление
                    await message.edit(f"⏳ Осталось: {remaining} сек...")
                    # Спим до следующего обновления (но не дольше оставшегося времени)
                    sleep_time = min(long_update_interval, remaining - final_countdown)
                    await asyncio.sleep(sleep_time)
    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.error(f"Ошибка в таймере: {e}")
        try:
            await event.edit("❌ Таймер прерван.")
        except:
            pass
        return

    # Удаление исходного сообщения (таймерного)
    try:
        await message.delete()
    except:
        pass

    # Отправка оповещения
    sender = await event.get_sender()
    mention = f"[{sender.first_name}](tg://user?id={sender.id})" if sender else "Пользователь"
    await client.send_message(
        event.chat_id,
        f"⏰ **Время истекло!** {mention}\nТаймер на {total_seconds} сек завершён.",
        parse_mode="markdown"
    )