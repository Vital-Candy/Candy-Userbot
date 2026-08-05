# core/session_migration.py
"""
Миграция старой одиночной Telethon-сессии в новую структуру accounts/<id>/.

Правила:
  - Не удаляет старую сессию до успешной проверки новой.
  - Не трогает другие аккаунты.
  - При любой ошибке — откат, старая сессия остаётся.
  - Не требует повторного входа если сессия рабочая.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger("session_migration")


async def migrate_if_needed(project_root: Path, accounts_dir: Path) -> bool:
    """
    Ищет старую сессию. Если найдена и рабочая — мигрирует.
    Возвращает True если миграция выполнена, False если не нужна или не удалась.
    """
    config_path = project_root / "config.json"
    if not config_path.exists():
        return False

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Не удалось прочитать config.json: {e}")
        return False

    api_id   = config.get("api_id")
    api_hash = config.get("api_hash")

    if not api_id or not api_hash:
        return False

    session_name = config.get("session_name", "session")
    old_session  = project_root / f"{session_name}.session"

    if not old_session.exists():
        logger.debug("Старая сессия не найдена — миграция не нужна")
        return False

    logger.info(f"Найдена старая сессия: {old_session}")
    return await _do_migrate(old_session, api_id, api_hash, accounts_dir, config_path)


async def _do_migrate(
    old_session:  Path,
    api_id:       int,
    api_hash:     str,
    accounts_dir: Path,
    config_path:  Path,
) -> bool:
    from telethon import TelegramClient

    # Тестируем старую сессию
    test_client = TelegramClient(
        str(old_session.with_suffix("")), api_id, api_hash
    )
    try:
        await test_client.connect()
        if not await test_client.is_user_authorized():
            logger.info("Старая сессия недействительна — пропускаем миграцию")
            await test_client.disconnect()
            return False

        me = await test_client.get_me()
        identifier = me.username or str(me.id)
        logger.info(f"Сессия рабочая: {identifier}")
        await test_client.disconnect()

    except Exception as e:
        logger.warning(f"Ошибка проверки старой сессии: {e}")
        if test_client.is_connected():
            await test_client.disconnect()
        return False

    # Готовим новую директорию
    new_dir     = accounts_dir / identifier
    new_session = new_dir / "session.session"
    new_dir.mkdir(parents=True, exist_ok=True)

    # Копируем (не перемещаем!) сессию
    try:
        shutil.copy2(old_session, new_session)
    except Exception as e:
        logger.error(f"Не удалось скопировать сессию: {e}")
        return False

    # Проверяем что новая сессия работает
    verify_client = TelegramClient(
        str(new_dir / "session"), api_id, api_hash
    )
    try:
        await verify_client.connect()
        if not await verify_client.is_user_authorized():
            raise RuntimeError("Новая сессия не авторизована")
        me = await verify_client.get_me()
        await verify_client.disconnect()
    except Exception as e:
        logger.error(f"Верификация новой сессии не прошла: {e}")
        if verify_client.is_connected():
            await verify_client.disconnect()
        # Откат
        if new_session.exists():
            new_session.unlink()
        return False

    # Сохраняем профиль
    import json as _json
    from datetime import datetime

    profile = {
        "api_id":      api_id,
        "api_hash":    api_hash,
        "id":          me.id,
        "name":        me.first_name or "",
        "username":    me.username or "",
        "phone":       str(me.phone or ""),
        "added":       datetime.now().strftime("%Y-%m-%d %H:%M"),
        "migrated":    True,
    }
    try:
        (new_dir / "profile.json").write_text(
            _json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        logger.error(f"Не удалось сохранить профиль: {e}")
        return False

    # Переименовываем старую сессию (не удаляем!)
    old_backup = old_session.with_suffix(".session.migrated")
    try:
        old_session.rename(old_backup)
        logger.info(f"Старая сессия сохранена как: {old_backup.name}")
    except Exception as e:
        logger.warning(f"Не удалось переименовать старую сессию: {e}")
        # Не критично — продолжаем

    logger.info(f"✅ Миграция завершена: {identifier}")
    return True
