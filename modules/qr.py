# modules/qr.py
import io
import logging
import qrcode
from PIL import Image
from telethon import events
from core.dispatcher import register_command
from core.client import client
from utils.tools import get_args

logger = logging.getLogger("qr")
_registered_handlers = []

def init():
    global _registered_handlers
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []

    register_command(
        "qr",
        "Создать QR-код",
        ".qr <текст или ссылка>",
        "Генерирует QR-код и отправляет его картинкой.",
        category="инструменты"
    )
    h = client.add_event_handler(qr_cmd, events.NewMessage(outgoing=True, pattern=r"^\.qr(?: (.+))?"))
    _registered_handlers.append(h)
    logger.info("Модуль qr зарегистрирован (изображение)")

def shutdown():
    global _registered_handlers
    for handler in _registered_handlers:
        client.remove_event_handler(handler)
    _registered_handlers = []
    logger.info("Модуль qr: обработчики удалены")

async def qr_cmd(event):
    args = get_args(event)
    if not args:
        await event.edit("❌ Укажи текст или ссылку.\nПример: `.qr https://google.com`")
        return

    data = " ".join(args)
    try:
        # Генерация QR-кода с нормальным размером
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,          # крупные пиксели – чёткое изображение
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        # Масштабируем до 300x300 для дополнительной чёткости
        img = img.resize((300, 300), Image.LANCZOS)

        bio = io.BytesIO()
        bio.name = "qr.jpg"
        img.convert("RGB").save(bio, format="JPEG", quality=85)
        bio.seek(0)

        await event.delete()
        await client.send_file(
            event.chat_id,
            bio,
            caption=f"📱 QR-код для `{data[:50]}{'…' if len(data) > 50 else ''}`",
            parse_mode="markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка QR: {e}")
        await event.edit(f"❌ Не удалось создать QR-код: {e}")