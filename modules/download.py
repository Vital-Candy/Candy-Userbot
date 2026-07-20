# modules/download.py
import os
import re
import asyncio
import logging
import time
import shutil
import aiohttp
from urllib.parse import urlparse, parse_qs

from telethon import events
from core.dispatcher import register_command
from core.client import client
from utils.tools import get_args
from utils.paths import CACHE_DIR, DOWNLOAD_DIR

logger = logging.getLogger("UniversalDownloader")

YT_DLP_DOMAINS = [
    "youtube.com", "youtu.be", "tiktok.com", "twitter.com", "x.com",
    "reddit.com", "bilibili.com", "twitch.tv", "vimeo.com", "dailymotion.com",
    "facebook.com", "fb.watch", "pinterest.com", "pin.it",
]
INSTALOADER_DOMAINS = ["instagram.com"]
GALLERY_DL_DOMAINS = [
    "pixiv.net", "deviantart.com", "artstation.com", "imgur.com",
    "flickr.com", "tumblr.com", "danbooru.donmai.us", "gelbooru.com",
]

VALID_SIGNATURES = {
    b'\xff\xd8\xff': 'jpg',
    b'\x89PNG\r\n\x1a\n': 'png',
    b'GIF8': 'gif',
    b'RIFF': 'webp',  # проверяется отдельно
}

def init():
    register_command(
        "download",
        "Универсальный загрузчик (соцсети, видео, фото)",
        ".download <ссылка> [-c] [-p]\n.download (reply на медиа) [-c] [-p]",
        "Скачивает медиа с YouTube, TikTok, Instagram, Twitter, Pinterest и др.\n"
        "Файлы кешируются в cache/.nomedia (не удаляются).\n"
        "-c : только отправить в чат (не сохранять в загрузки)\n"
        "-p : только сохранить в /sdcard/Download/UserBot (не отправлять в чат)\n"
        "Без флагов: и отправить, и сохранить в загрузки.\n"
        "Reply на любое медиа (включая исчезающее) скачивает оригинал.",
        category="инструменты"
    )
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    logger.info("Модуль download активирован. Кеш: %s", CACHE_DIR)

def get_domain(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    return domain[4:] if domain.startswith("www.") else domain

def get_strategy(url: str) -> str:
    domain = get_domain(url)
    if any(d in domain for d in INSTALOADER_DOMAINS):
        return "instaloader"
    if "pinterest" in domain:
        return "yt-dlp"
    if any(d in domain for d in YT_DLP_DOMAINS):
        return "yt-dlp"
    if any(d in domain for d in GALLERY_DL_DOMAINS):
        return "gallery-dl"
    return "direct"

def parse_flags(args: list):
    url = None
    flags = {"-c": False, "-p": False}
    for a in args:
        if a in flags:
            flags[a] = True
        elif not url:
            url = a
    send_to_chat = not flags["-p"]
    save_to_download = not flags["-c"]
    return url, send_to_chat, save_to_download

def get_unique_filename(directory, filename):
    base, ext = os.path.splitext(filename)
    counter = 1
    new_name = filename
    while os.path.exists(os.path.join(directory, new_name)):
        new_name = f"{base} ({counter}){ext}"
        counter += 1
    return new_name

def _extract_youtube_id(url: str) -> str:
    parsed = urlparse(url)
    if 'youtube.com' in parsed.netloc:
        return parse_qs(parsed.query).get('v', [None])[0]
    elif 'youtu.be' in parsed.netloc:
        return parsed.path[1:]
    return None

def is_valid_media(filepath):
    if not os.path.isfile(filepath):
        return False
    size = os.path.getsize(filepath)
    if size < 1024:
        return False
    try:
        with open(filepath, 'rb') as f:
            header = f.read(12)
        if header.startswith(b'\xff\xd8\xff'):          # JPEG
            return True
        if header.startswith(b'\x89PNG\r\n\x1a\n'):     # PNG
            return True
        if header.startswith(b'GIF8'):                  # GIF
            return True
        if header.startswith(b'RIFF') and header[8:12] == b'WEBP':  # WebP
            return True
        if len(header) >= 8 and header[4:8] == b'ftyp': # MP4 / MOV
            return True
        if header.startswith(b'\x1aE\xdf\xa3'):         # WebM / MKV
            return True
        return False
    except Exception:
        return False

@client.on(events.NewMessage(outgoing=True, pattern=r"^\.download(?: (.+))?"))
async def download_handler(event):
    args = get_args(event)
    url, send_to_chat, save_to_download = parse_flags(args)

    if not url and event.is_reply:
        reply_msg = await event.get_reply_message()
        if reply_msg and reply_msg.media:
            await _download_reply_media(event, reply_msg, send_to_chat, save_to_download)
            return
        else:
            await event.edit("❌ В реплае нет медиа.")
            return

    if not url:
        await event.edit("❌ Укажите ссылку или сделайте reply на медиа.\nПример: `.download https://youtu.be/... -c`")
        return

    if not send_to_chat and not save_to_download:
        await event.edit("❌ Флаги -c и -p вместе не имеют смысла (ничего не делать).")
        return

    status_msg = await event.edit("⏳ Анализирую ссылку...")
    strategy = get_strategy(url)
    logger.info(f"Загрузка {url}, стратегия: {strategy}")
    try:
        if strategy == "yt-dlp":
            await _download_with_ytdlp(status_msg, url, send_to_chat, save_to_download)
        elif strategy == "instaloader":
            await _download_instagram(status_msg, url, send_to_chat, save_to_download)
        elif strategy == "gallery-dl":
            await _download_with_gallerydl(status_msg, url, send_to_chat, save_to_download)
        else:
            await _download_direct(status_msg, url, send_to_chat, save_to_download)
    except Exception as e:
        logger.error(f"Download error: {e}")
        await status_msg.edit(f"❌ Ошибка: {e}")

async def _download_with_ytdlp(status_msg, url, send_to_chat, save_to_download):
    await status_msg.edit("⏳ yt-dlp: скачиваю... (прогресс недоступен)")
    template = os.path.join(CACHE_DIR, "%(title).100s [%(id)s].%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", template,
        "--print", "after_move:filepath",
        url
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise Exception(f"yt-dlp error:\n{stderr.decode()}")

    lines = [l.strip() for l in stdout.decode().splitlines() if l.strip()]
    filepath = None
    if lines:
        filepath = lines[-1]
    if not filepath or not os.path.exists(filepath):
        files = [os.path.join(CACHE_DIR, f) for f in os.listdir(CACHE_DIR) if f.endswith(".mp4")]
        if files:
            filepath = max(files, key=os.path.getctime)
    if not filepath or not os.path.exists(filepath):
        vid = _extract_youtube_id(url)
        if vid:
            for f in os.listdir(CACHE_DIR):
                if vid in f and f.endswith(".mp4"):
                    filepath = os.path.join(CACHE_DIR, f)
                    break
    if not filepath or not os.path.exists(filepath):
        raise Exception("Не удалось найти скачанный файл.")
    await _send_and_save_file(status_msg, filepath, send_to_chat, save_to_download)
    # Удаляем статусное сообщение после обработки
    try:
        await status_msg.delete()
    except:
        pass

async def _download_instagram(status_msg, url, send_to_chat, save_to_download):
    await status_msg.edit("⏳ Instagram: скачиваю...")
    try:
        from instaloader import Instaloader, Post
    except ImportError:
        await status_msg.edit("❌ Установи instaloader: `pip install instaloader`")
        return

    shortcode = None
    for pat in (r'/p/([^/?&]+)', r'/reel/([^/?&]+)', r'/tv/([^/?&]+)'):
        m = re.search(pat, url)
        if m:
            shortcode = m.group(1)
            break
    if not shortcode:
        await status_msg.edit("❌ Не удалось определить код поста Instagram.")
        return

    tmp_dir = os.path.join(CACHE_DIR, f"insta_{shortcode}")
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        loop = asyncio.get_running_loop()
        def _insta_download():
            loader = Instaloader(dirname_pattern=tmp_dir)
            post = Post.from_shortcode(loader.context, shortcode)
            loader.download_post(post, target=tmp_dir)
        await loop.run_in_executor(None, _insta_download)

        # Собираем все медиафайлы
        media_files = []
        for root, dirs, files in os.walk(tmp_dir):
            for f in files:
                filepath = os.path.join(root, f)
                if is_valid_media(filepath):
                    media_files.append(filepath)

        if not media_files:
            raise Exception("Не найдено пригодных медиафайлов после загрузки Instagram.")

        # Перемещаем в кеш и отправляем/сохраняем каждый файл
        for src in media_files:
            filename = os.path.basename(src)
            unique_name = get_unique_filename(CACHE_DIR, filename)
            dst = os.path.join(CACHE_DIR, unique_name)
            shutil.move(src, dst)
            await _send_and_save_file(status_msg, dst, send_to_chat, save_to_download)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Теперь можно удалить статусное сообщение после обработки всех файлов
    try:
        await status_msg.delete()
    except:
        pass

async def _download_with_gallerydl(status_msg, url, send_to_chat, save_to_download):
    await status_msg.edit("⏳ gallery-dl: загружаю коллекцию...")
    cmd = ["gallery-dl", "-d", CACHE_DIR, url]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise Exception(f"gallery-dl error:\n{stderr.decode()}")

    await status_msg.edit("✅ Файлы сохранены. Ищу для отправки...")
    found = False
    for root, dirs, files in os.walk(CACHE_DIR):
        for f in files:
            filepath = os.path.join(root, f)
            if is_valid_media(filepath):
                await _send_and_save_file(status_msg, filepath, send_to_chat, save_to_download)
                found = True
    if not found:
        await status_msg.edit("⚠️ Не найдено новых медиафайлов после gallery-dl.")
    else:
        try:
            await status_msg.delete()
        except:
            pass

async def _download_direct(status_msg, url, send_to_chat, save_to_download):
    """Прямая загрузка с прогрессом (скорость, объём)."""
    await status_msg.edit("⏳ Получаю информацию о файле...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=30)) as head_resp:
                content_length = head_resp.headers.get('Content-Length')
                total_size = int(content_length) if content_length else None
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")
                content_type = resp.headers.get('Content-Type', '').lower()
                if 'video' in content_type:
                    ext = '.mp4'
                elif 'image' in content_type:
                    if 'png' in content_type: ext = '.png'
                    elif 'gif' in content_type: ext = '.gif'
                    else: ext = '.jpg'
                else:
                    ext = '.bin'

                filename = f"direct_{len(os.listdir(CACHE_DIR))}{ext}"
                filename = get_unique_filename(CACHE_DIR, filename)
                filepath = os.path.join(CACHE_DIR, filename)

                downloaded = 0
                start_time = time.time()
                last_update = start_time
                with open(filepath, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if now - last_update >= 2:
                            elapsed = now - start_time
                            speed = downloaded / elapsed if elapsed > 0 else 0
                            if total_size:
                                percent = downloaded / total_size * 100
                                text = (f"⏳ Загружаю... {downloaded/1024/1024:.1f}/{total_size/1024/1024:.1f} МБ "
                                        f"({percent:.0f}%) | {speed/1024/1024:.1f} МБ/с")
                            else:
                                text = f"⏳ Загружаю... {downloaded/1024/1024:.1f} МБ | {speed/1024/1024:.1f} МБ/с"
                            try:
                                await status_msg.edit(text)
                            except:
                                pass
                            last_update = now

                if not is_valid_media(filepath):
                    os.remove(filepath)
                    raise Exception("Скачанный файл не является медиа (возможно, ошибка ссылки).")

                await _send_and_save_file(status_msg, filepath, send_to_chat, save_to_download)
    except Exception as e:
        raise e
    finally:
        try:
            await status_msg.delete()
        except:
            pass

async def _download_reply_media(event, reply_msg, send_to_chat, save_to_download):
    status_msg = await event.edit("⏳ Скачиваю медиа из реплая...")
    timestamp = getattr(reply_msg, 'date', None)
    base_name = f"reply_{timestamp.strftime('%Y%m%d_%H%M%S')}" if timestamp else f"reply_{len(os.listdir(CACHE_DIR))}"

    try:
        temp_path = await reply_msg.download_media(file=os.path.join(CACHE_DIR, base_name))
    except Exception as e:
        await status_msg.edit(f"❌ Ошибка скачивания: {e}")
        return

    if not temp_path:
        await status_msg.edit("❌ Не удалось скачать медиа (возможно, исчезло).")
        return

    ext = os.path.splitext(temp_path)[1]
    final_name = get_unique_filename(CACHE_DIR, f"{base_name}{ext}")
    final_path = os.path.join(CACHE_DIR, final_name)
    os.rename(temp_path, final_path)

    if not is_valid_media(final_path):
        os.remove(final_path)
        await status_msg.edit("❌ Скачанный файл не является медиа.")
        return

    await _send_and_save_file(status_msg, final_path, send_to_chat, save_to_download)
    try:
        await status_msg.delete()
    except:
        pass

async def _send_and_save_file(status_msg, filepath, send_to_chat, save_to_download):
    """Вспомогательная функция: отправка в чат и/или сохранение в загрузки."""
    if not os.path.exists(filepath):
        return

    if send_to_chat:
        try:
            await client.send_file(status_msg.chat_id, filepath)
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
            await client.send_message(status_msg.chat_id, f"❌ Ошибка отправки: {e}")

    if save_to_download:
        dest = os.path.join(DOWNLOAD_DIR, get_unique_filename(DOWNLOAD_DIR, os.path.basename(filepath)))
        try:
            shutil.copy2(filepath, dest)
            await client.send_message(status_msg.chat_id, f"✅ Сохранено в загрузки: `{os.path.basename(dest)}`")
        except Exception as e:
            logger.error(f"Ошибка копирования в загрузки: {e}")
            await client.send_message(status_msg.chat_id, f"❌ Не удалось сохранить: {e}")