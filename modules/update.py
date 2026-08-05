import asyncio
import os
import sys
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from telethon import events

import core.client as client_state
from core.dispatcher import register_command
from config import VERSION as LOCAL_VERSION
from utils.paths import PROJECT_ROOT, BACKUP_DIR

_handler = None
BACKUP_NAME = "pre_update_backup.zip"


def _parse_version(content: str) -> str:
    match = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', content)
    return match.group(1) if match else None


def _create_backup() -> Path:
    backup_path = BACKUP_DIR / BACKUP_NAME
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    ignore_patterns = {".git", "accounts", "backup", "__pycache__", "*.pyc", "userbot.log", "*.session", "*.session-journal"}

    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in PROJECT_ROOT.rglob("*"):
            rel = path.relative_to(PROJECT_ROOT)
            if any(p in rel.parts for p in ignore_patterns):
                continue
            if path.is_file():
                zf.write(path, arcname=rel)
    return backup_path


def _restore_backup(backup_path: Path) -> None:
    ignore_patterns = {".git", "accounts", "backup", "__pycache__", "*.pyc", "userbot.log", "*.session", "*.session-journal"}
    # Удаляем всё, кроме защищённого
    for path in PROJECT_ROOT.rglob("*"):
        rel = path.relative_to(PROJECT_ROOT)
        if any(p in rel.parts for p in ignore_patterns):
            continue
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass

    with zipfile.ZipFile(backup_path, "r") as zf:
        zf.extractall(PROJECT_ROOT)


def _remove_backup(backup_path: Path) -> None:
    if backup_path.exists():
        backup_path.unlink()


def _restart_app() -> None:
    os.execv(sys.executable, [sys.executable] + sys.argv)


def _run_cmd_sync(cmd: list[str]) -> tuple[int, str, str]:
    """Выполняет команду в папке проекта и возвращает (код, stdout, stderr)."""
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    return proc.returncode, proc.stdout, proc.stderr


def _is_git_repo() -> bool:
    return os.path.isdir(os.path.join(PROJECT_ROOT, ".git"))


def init() -> None:
    global _handler
    if client_state.client is None:
        raise RuntimeError("TelegramClient не установлен")
    register_command(
        "update",
        "Обновить код (автоматический перезапуск)",
        ".update",
        "Система"
    )
    _handler = client_state.client.add_event_handler(
        update_cmd,
        events.NewMessage(outgoing=True, pattern=r"^\.update$")
    )


def shutdown() -> None:
    global _handler
    if client_state.client is not None and _handler is not None:
        client_state.client.remove_event_handler(_handler)
        _handler = None


async def update_cmd(event) -> None:
    try:
        await _do_update(event)
    except Exception as e:
        await event.edit(f"❌ Непредвиденная ошибка: {str(e)}")


async def _do_update(event):
    msg = await event.edit("🔄 Подготовка к обновлению...")

    if not _is_git_repo():
        await msg.edit("❌ Это не git-репозиторий. Обновление невозможно.")
        return

    # === Автоматическое переключение на main ===
    current_branch = _run_cmd_sync(["git", "rev-parse", "--abbrev-ref", "HEAD"])[1].strip()
    if current_branch != "main":
        await msg.edit(f"⚠️ Вы на ветке '{current_branch}'. Переключаю на 'main'...")
        # Сохраняем изменения, если есть
        _run_cmd_sync(["git", "stash", "push", "-m", "auto-stash-before-update"])
        # Переключаемся на main (создаём, если нет)
        switch = _run_cmd_sync(["git", "checkout", "main"])
        if switch[0] != 0:
            # если main нет, создаём
            _run_cmd_sync(["git", "checkout", "-b", "main"])
        # Удаляем старую ветку (если хотим)
        _run_cmd_sync(["git", "branch", "-D", current_branch])
        await msg.edit(f"✅ Переключено на 'main'")

    # Проверяем удалённый репозиторий
    remotes_output = _run_cmd_sync(["git", "remote"])[1].strip()
    if not remotes_output:
        await msg.edit("❌ Удалённый репозиторий не настроен. Добавьте origin вручную.")
        return
    remotes = remotes_output.split()
    if "origin" not in remotes:
        await msg.edit("❌ Удалённый репозиторий 'origin' не найден.")
        return

    # Создаём бэкап
    await msg.edit("📦 Создание резервной копии...")
    backup_path = _create_backup()

    # Получаем версию с удалённого репозитория
    await msg.edit("🔄 Проверка версий...")
    fetch = _run_cmd_sync(["git", "fetch", "origin", "main"])
    if fetch[0] != 0:
        _restore_backup(backup_path)
        _remove_backup(backup_path)
        await msg.edit(f"❌ Ошибка fetch:\n{fetch[2]}")
        return

    show = _run_cmd_sync(["git", "show", "origin/main:config.py"])
    if show[0] != 0:
        _restore_backup(backup_path)
        _remove_backup(backup_path)
        await msg.edit("❌ Не удалось прочитать config.py в удалённом репозитории.")
        return

    remote_content = show[1]
    remote_version = _parse_version(remote_content)
    if not remote_version:
        _restore_backup(backup_path)
        _remove_backup(backup_path)
        await msg.edit("❌ Не удалось определить версию в удалённом config.py.")
        return

    local_version = LOCAL_VERSION
    if local_version == remote_version:
        _remove_backup(backup_path)
        await msg.edit(f"✅ Уже актуальная версия (v{local_version}).")
        return

    # Выполняем pull
    await msg.edit(f"🔄 Обновление с v{local_version} до v{remote_version}...")
    pull = _run_cmd_sync(["git", "pull", "--force", "origin", "main"])
    if pull[0] != 0:
        await msg.edit("❌ Ошибка обновления! Откат к предыдущей версии...")
        _restore_backup(backup_path)
        _remove_backup(backup_path)
        await msg.edit(f"❌ Обновление не удалось. Восстановлена старая версия.\nОшибка:\n{pull[2]}")
        _restart_app()
        return

    # Успешное обновление – удаляем бэкап
    _remove_backup(backup_path)
    await msg.edit(f"✅ Обновлено до v{remote_version}!\nПерезапуск юзербота...")
    # Перезагружаем модули (для уверенности)
    from core.loader import reload_modules
    await reload_modules()
    # Автоматический перезапуск
    _restart_app()