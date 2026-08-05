from __future__ import annotations

import asyncio
import os
import re
import sys
import zipfile
from pathlib import Path

from telethon import events

import core.client as client_state
from config import VERSION as LOCAL_VERSION
from core.dispatcher import register_command
from utils.paths import BACKUP_DIR, PROJECT_ROOT


REMOTE_NAME = "origin"
REMOTE_BRANCH = "main"
BACKUP_NAME = "pre_update_backup.zip"

_handler = None


def _parse_version(content: str) -> str | None:
    match = re.search(
        r'^\s*VERSION\s*=\s*["\']([^"\']+)["\']',
        content,
        flags=re.MULTILINE,
    )

    if match is None:
        return None

    return match.group(1).strip()


def _is_protected(path: Path) -> bool:
    """
    Личные данные и временные файлы.

    Они не должны попадать в backup
    и не должны удаляться при восстановлении.
    """

    try:
        relative = path.relative_to(PROJECT_ROOT)
    except ValueError:
        return True

    parts = relative.parts
    name = path.name

    if ".git" in parts:
        return True

    if "accounts" in parts:
        return True

    if "backup" in parts:
        return True

    if "__pycache__" in parts:
        return True

    if name == "userbot.log":
        return True

    if name.endswith(".pyc"):
        return True

    if name.endswith(".session"):
        return True

    if name.endswith(".session-journal"):
        return True

    return False


def _create_backup() -> Path:
    """
    Создаёт временный ZIP-бэкап текущего кода.

    Личные данные в архив не добавляются.
    """

    BACKUP_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    backup_path = BACKUP_DIR / BACKUP_NAME

    if backup_path.exists():
        backup_path.unlink()

    with zipfile.ZipFile(
        backup_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:

        for path in PROJECT_ROOT.rglob("*"):

            if not path.is_file():
                continue

            if _is_protected(path):
                continue

            relative = path.relative_to(
                PROJECT_ROOT
            )

            archive.write(
                path,
                arcname=str(relative),
            )

    return backup_path


def _restore_backup(
    backup_path: Path,
) -> None:
    """
    Восстанавливает код из временного ZIP.

    accounts/, backup/, сессии,
    логи и Git не изменяются.
    """

    if not backup_path.is_file():
        raise FileNotFoundError(
            "Backup не найден"
        )

    files_to_delete = []

    for path in PROJECT_ROOT.rglob("*"):

        if not path.is_file():
            continue

        if _is_protected(path):
            continue

        files_to_delete.append(path)

    for path in files_to_delete:

        path.unlink(
            missing_ok=True
        )

    with zipfile.ZipFile(
        backup_path,
        mode="r",
    ) as archive:

        for info in archive.infolist():

            if info.is_dir():
                continue

            relative = Path(
                info.filename
            )

            if relative.is_absolute():
                raise RuntimeError(
                    "Небезопасный путь "
                    "в backup"
                )

            if ".." in relative.parts:
                raise RuntimeError(
                    "Небезопасный путь "
                    "в backup"
                )

            destination = (
                PROJECT_ROOT / relative
            )

            if _is_protected(
                destination
            ):
                continue

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with archive.open(
                info,
                "r",
            ) as source:

                with destination.open(
                    "wb"
                ) as target:

                    target.write(
                        source.read()
                    )


def _remove_backup(
    backup_path: Path,
) -> None:

    try:

        backup_path.unlink(
            missing_ok=True
        )

    except OSError:
        pass


async def _run_git(
    *arguments: str,
) -> tuple[int, str, str]:
    """
    Асинхронно запускает Git.

    Возвращает:
    код,
    stdout,
    stderr.
    """

    try:

        process = (
            await asyncio.create_subprocess_exec(
                "git",
                *arguments,
                cwd=str(PROJECT_ROOT),
                stdout=(
                    asyncio.subprocess.PIPE
                ),
                stderr=(
                    asyncio.subprocess.PIPE
                ),
            )
        )

    except FileNotFoundError:

        return (
            127,
            "",
            "Git не установлен",
        )

    stdout, stderr = (
        await process.communicate()
    )

    return (
        process.returncode,
        stdout.decode(
            "utf-8",
            errors="replace",
        ),
        stderr.decode(
            "utf-8",
            errors="replace",
        ),
    )


async def _get_git_output(
    *arguments: str,
) -> str | None:

    code, output, _ = (
        await _run_git(
            *arguments
        )
    )

    if code != 0:
        return None

    return output.strip()


async def _is_git_repository() -> bool:

    result = await _get_git_output(
        "rev-parse",
        "--is-inside-work-tree",
    )

    return result == "true"


async def _has_origin() -> bool:

    output = await _get_git_output(
        "remote"
    )

    if output is None:
        return False

    remotes = {
        line.strip()
        for line in output.splitlines()
    }

    return REMOTE_NAME in remotes


async def _get_commit(
    reference: str,
) -> str | None:

    return await _get_git_output(
        "rev-parse",
        "--verify",
        reference,
    )


async def _get_remote_version() -> str | None:

    code, content, _ = (
        await _run_git(
            "show",
            (
                f"{REMOTE_NAME}/"
                f"{REMOTE_BRANCH}:"
                "config.py"
            ),
        )
    )

    if code != 0:
        return None

    return _parse_version(
        content
    )


async def _update(
    event,
) -> None:

    message = await event.edit(
        "🔄 <b>Проверяю обновления...</b>",
        parse_mode="html",
    )

    if not await _is_git_repository():

        await message.edit(
            "❌ <b>Это не Git-репозиторий.</b>",
            parse_mode="html",
        )

        return

    if not await _has_origin():

        await message.edit(
            "❌ <b>Удалённый репозиторий "
            "origin не найден.</b>",
            parse_mode="html",
        )

        return

    await message.edit(
        "📡 <b>Получаю данные "
        "из GitHub...</b>",
        parse_mode="html",
    )

    fetch_code, _, fetch_error = (
        await _run_git(
            "fetch",
            REMOTE_NAME,
            REMOTE_BRANCH,
            "--quiet",
        )
    )

    if fetch_code != 0:

        error_text = (
            fetch_error.strip()
            or "Неизвестная ошибка"
        )

        await message.edit(
            "❌ <b>Не удалось получить "
            "обновления.</b>\n\n"
            f"<code>{error_text[:700]}</code>",
            parse_mode="html",
        )

        return

    local_commit = await _get_commit(
        "HEAD"
    )

    remote_commit = await _get_commit(
        (
            f"{REMOTE_NAME}/"
            f"{REMOTE_BRANCH}"
        )
    )

    if (
        local_commit is None
        or remote_commit is None
    ):

        await message.edit(
            "❌ <b>Не удалось определить "
            "Git-версию.</b>",
            parse_mode="html",
        )

        return

    remote_version = (
        await _get_remote_version()
    )

    if local_commit == remote_commit:

        version = (
            remote_version
            or LOCAL_VERSION
        )

        await message.edit(
            "✅ <b>Уже установлена "
            "последняя версия.</b>\n\n"
            f"Версия: <code>v{version}</code>",
            parse_mode="html",
        )

        return

    await message.edit(
        "📦 <b>Создаю временный "
        "backup кода...</b>",
        parse_mode="html",
    )

    try:

        backup_path = (
            _create_backup()
        )

    except Exception as error:

        await message.edit(
            "❌ <b>Не удалось создать "
            "backup.</b>\n\n"
            f"<code>{str(error)[:700]}</code>",
            parse_mode="html",
        )

        return

    new_version = (
        remote_version
        or "новая"
    )

    await message.edit(
        "⬇️ <b>Обновляю код...</b>\n\n"
        f"<code>v{LOCAL_VERSION}</code>"
        " → "
        f"<code>v{new_version}</code>",
        parse_mode="html",
    )

    reset_code, _, reset_error = (
        await _run_git(
            "reset",
            "--hard",
            (
                f"{REMOTE_NAME}/"
                f"{REMOTE_BRANCH}"
            ),
        )
    )

    if reset_code != 0:

        try:

            _restore_backup(
                backup_path
            )

        except Exception:
            pass

        _remove_backup(
            backup_path
        )

        error_text = (
            reset_error.strip()
            or "Неизвестная ошибка"
        )

        await message.edit(
            "❌ <b>Обновление не "
            "выполнено.</b>\n\n"
            "Старый код восстановлен.\n\n"
            f"<code>{error_text[:700]}</code>",
            parse_mode="html",
        )

        return

    clean_code, _, clean_error = (
        await _run_git(
            "clean",
            "-fd",
        )
    )

    if clean_code != 0:

        try:

            _restore_backup(
                backup_path
            )

        except Exception:
            pass

        _remove_backup(
            backup_path
        )

        error_text = (
            clean_error.strip()
            or "Неизвестная ошибка"
        )

        await message.edit(
            "❌ <b>Не удалось завершить "
            "обновление.</b>\n\n"
            "Старый код восстановлен.\n\n"
            f"<code>{error_text[:700]}</code>",
            parse_mode="html",
        )

        return

    _remove_backup(
        backup_path
    )

    await message.edit(
        "✅ <b>Обновление завершено.</b>\n\n"
        f"Версия: <code>v{new_version}</code>\n"
        "🔄 Перезапускаю юзербот...",
        parse_mode="html",
    )

    await asyncio.sleep(1)

    os.execv(
        sys.executable,
        [
            sys.executable,
            *sys.argv,
        ],
    )


async def update_command(
    event,
) -> None:

    try:

        await _update(
            event
        )

    except Exception as error:

        await event.edit(
            "❌ <b>Непредвиденная "
            "ошибка.</b>\n\n"
            f"<code>{str(error)[:700]}</code>",
            parse_mode="html",
        )


def init() -> None:

    global _handler

    if client_state.client is None:

        raise RuntimeError(
            "TelegramClient "
            "не установлен"
        )

    register_command(
        "update",
        "Обновить Candy-Userbot",
        ".update",
        category="Система",
    )

    _handler = (
        client_state.client.add_event_handler(
            update_command,
            events.NewMessage(
                outgoing=True,
                pattern=r"^\.update$",
            ),
        )
    )


async def shutdown() -> None:

    global _handler

    if (
        client_state.client is not None
        and _handler is not None
    ):

        client_state.client.remove_event_handler(
            _handler
        )

    _handler = None