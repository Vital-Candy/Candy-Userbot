# core/accounts.py
"""
Файловые операции с аккаунтами: список, добавление, бэкап, восстановление.
Runtime-состояние хранится в AccountContext (core/account_context.py).
"""
import json
import logging
import os
import zipfile
from datetime import datetime
from pathlib import Path

from utils.paths import PROJECT_ROOT, ACCOUNTS_DIR

logger = logging.getLogger("accounts")

BACKUP_MARKER = "CandyUSERBOT_v1"


# ── Список аккаунтов ──────────────────────────────────────────────────

def list_accounts() -> list[dict]:
    if not ACCOUNTS_DIR.exists():
        return []
    result = []
    for entry in sorted(ACCOUNTS_DIR.iterdir()):
        pf = entry / "profile.json"
        if entry.is_dir() and pf.exists():
            try:
                result.append(json.loads(pf.read_text(encoding="utf-8")))
            except Exception as e:
                logger.warning(f"Ошибка профиля {entry.name}: {e}")
    return result


# ── Профиль ───────────────────────────────────────────────────────────

def get_identifier(profile: dict) -> str:
    return profile.get("username") or profile.get("phone") or str(profile.get("id", "unknown"))


def get_account_dir(profile: dict) -> Path:
    return ACCOUNTS_DIR / get_identifier(profile)


def save_profile(profile: dict) -> None:
    acc_dir = get_account_dir(profile)
    acc_dir.mkdir(parents=True, exist_ok=True)
    (acc_dir / "profile.json").write_text(
        json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ── Добавить аккаунт интерактивно ─────────────────────────────────────

async def add_account_interactive() -> dict | None:
    from telethon import TelegramClient

    G, R, C, W, B = "\033[32m", "\033[31m", "\033[36m", "\033[0m", "\033[1m"
    print(f"\n  {C}── Добавить аккаунт ──{W}\n")
    print(f"  Данные на {B}https://my.telegram.org/apps{W}\n")

    try:
        api_id   = int(input("  API_ID  › ").strip())
        api_hash = input("  API_HASH › ").strip()
        if not api_hash:
            raise ValueError("api_hash пустой")
    except (ValueError, KeyboardInterrupt, EOFError) as e:
        print(f"\n  {R}[✗]{W} Отменено: {e}")
        input("\n  Enter для продолжения...")
        return None

    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = str(ACCOUNTS_DIR / "_tmp")
    client = TelegramClient(tmp, api_id, api_hash)

    try:
        print()
        await client.start()
        me = await client.get_me()

        identifier = me.username or str(me.phone or me.id)
        acc_dir    = ACCOUNTS_DIR / identifier
        acc_dir.mkdir(parents=True, exist_ok=True)
        await client.disconnect()

        for ext in (".session", ".session-journal"):
            src = Path(tmp + ext)
            if src.exists():
                src.replace(acc_dir / ("session" + ext))

        profile = {
            "api_id":   api_id,
            "api_hash": api_hash,
            "id":       me.id,
            "name":     me.first_name or "",
            "username": me.username or "",
            "phone":    str(me.phone or ""),
            "added":    datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        save_profile(profile)
        print(f"\n  {G}[✓]{W} Аккаунт {B}{me.first_name}{W} добавлен!")
        input("\n  Enter для продолжения...")
        return profile

    except KeyboardInterrupt:
        print(f"\n  {R}[✗]{W} Отменено")
    except Exception as e:
        print(f"\n  {R}[✗]{W} Ошибка: {e}")
    finally:
        if client.is_connected():
            await client.disconnect()
        for ext in (".session", ".session-journal"):
            p = Path(tmp + ext)
            if p.exists():
                p.unlink(missing_ok=True)

    input("\n  Enter для продолжения...")
    return None


# ── Бэкап ─────────────────────────────────────────────────────────────

def backup_account(profile: dict) -> str:
    if os.path.isdir("/sdcard") and os.access("/sdcard", os.W_OK):
        dest = Path("/sdcard/Download/Candy-Userbot/Backups")
    else:
        dest = Path.home() / "CandyUserbot-Backups"

    dest.mkdir(parents=True, exist_ok=True)
    identifier = get_identifier(profile)
    acc_dir    = get_account_dir(profile)
    zip_path   = dest / f"candy_backup_{identifier}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("candy_backup.marker", BACKUP_MARKER)
        for fname in ("profile.json", "session.session"):
            p = acc_dir / fname
            if p.exists():
                zf.write(p, fname)
        state = PROJECT_ROOT / "time_name_state.json"
        if state.exists():
            zf.write(state, "time_name_state.json")

    return str(zip_path)


# ── Восстановление ────────────────────────────────────────────────────

def restore_account(zip_path: str) -> str:
    zp = Path(zip_path)
    if not zp.exists():
        raise FileNotFoundError(f"Файл не найден: {zip_path}")

    with zipfile.ZipFile(zp, "r") as zf:
        names = zf.namelist()
        if "candy_backup.marker" not in names:
            raise ValueError("Не бэкап Candy Userbot")
        if "profile.json" not in names:
            raise ValueError("Нет profile.json в архиве")

        profile    = json.loads(zf.read("profile.json").decode("utf-8"))
        identifier = get_identifier(profile)
        acc_dir    = ACCOUNTS_DIR / identifier
        acc_dir.mkdir(parents=True, exist_ok=True)

        for name in names:
            if name == "candy_backup.marker":
                continue
            dest = (PROJECT_ROOT / name) if name == "time_name_state.json" else (acc_dir / name)
            with zf.open(name) as src, open(dest, "wb") as dst:
                dst.write(src.read())

    return identifier
