from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from core.account import Account
from utils.paths import ACCOUNTS_DIR, BACKUP_DIR


def profiles() -> list[dict]:
    result: list[dict] = []
    for path in sorted(ACCOUNTS_DIR.glob("*/profile.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                result.append(data)
        except Exception:
            continue
    return result


def account_from_profile(data: dict) -> Account:
    name = data.get("username") or str(data["id"])
    return Account(
        account_id=int(data["id"]),
        api_id=int(data["api_id"]),
        api_hash=str(data["api_hash"]),
        username=data.get("username") or None,
        first_name=data.get("name") or "",
        session_path=ACCOUNTS_DIR / name / "session",
    )


async def add_account() -> dict:
    api_id = int(input("API_ID: ").strip())
    api_hash = input("API_HASH: ").strip()
    phone = input("Номер (+...): ").strip()

    tmp_dir = ACCOUNTS_DIR / "_new"
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    client = TelegramClient(
        str(tmp_dir / "session"),
        api_id,
        api_hash,
    )

    try:
        await client.connect()
        await client.send_code_request(phone)

        code = input("Код Telegram: ").strip()
        try:
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            password = input("Пароль 2FA: ").strip()
            await client.sign_in(password=password)

        me = await client.get_me()
        name = me.username or str(me.id)
        account_dir = ACCOUNTS_DIR / name
        account_dir.mkdir(parents=True, exist_ok=True)

        await client.disconnect()

        for suffix in (".session", ".session-journal"):
            source = Path(str(tmp_dir / "session") + suffix)
            if source.exists():
                shutil.move(
                    str(source),
                    str(account_dir / source.name),
                )

        data = {
            "id": me.id,
            "username": me.username or "",
            "name": me.first_name or "",
            "api_id": api_id,
            "api_hash": api_hash,
            "session": "session",
        }
        (account_dir / "profile.json").write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return data
    finally:
        if client.is_connected():
            await client.disconnect()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def create_backup(profile: dict) -> Path:
    name = profile.get("username") or str(profile["id"])
    folder = ACCOUNTS_DIR / name
    if not folder.is_dir():
        raise FileNotFoundError(folder)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    output = BACKUP_DIR / f"{name}.zip"

    with zipfile.ZipFile(
        output,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as archive:
        for path in folder.rglob("*"):
            if path.is_file():
                archive.write(
                    path,
                    path.relative_to(ACCOUNTS_DIR),
                )
    return output


def restore_backup(path: str) -> None:
    source = Path(path).expanduser()
    if not source.exists() and not source.is_absolute():
        source = BACKUP_DIR / source

    if not source.is_file():
        raise FileNotFoundError(source)

    root = ACCOUNTS_DIR.resolve()
    with zipfile.ZipFile(source) as archive:
        for member in archive.infolist():
            target = (ACCOUNTS_DIR / member.filename).resolve()
            if target != root and root not in target.parents:
                raise ValueError("Опасный путь в ZIP")

        archive.extractall(ACCOUNTS_DIR)
