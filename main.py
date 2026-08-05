# main.py
"""
Точка входа Candy-Userbot.

Этап 2: параллельный запуск нескольких аккаунтов.
  1. Миграция старой сессии (если есть).
  2. Загрузка профилей из accounts/.
  3. Параллельное подключение всех аккаунтов.
  4. Если нет аккаунтов — добавление через терминал.
  5. Активация dispatcher + модулей на первом/активном аккаунте.
  6. run_until_disconnected для каждого аккаунта как asyncio.Task.
  7. Ctrl+C → корректная остановка всех.
"""
import asyncio
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import setup_logger
from utils.paths import PROJECT_ROOT, ACCOUNTS_DIR, ensure_dirs

logger = setup_logger()

G  = "\033[32m"; Y = "\033[33m"; R = "\033[31m"
C  = "\033[36m"; W = "\033[0m";  B = "\033[1m"; DIM = "\033[2m"


def _print_banner():
    try:
        print((PROJECT_ROOT / "assets" / "banner.txt").read_text(encoding="utf-8"))
    except Exception:
        pass
    from config import VERSION, OWNER
    print(f"  {B}Candy Userbot{W}  v{VERSION}  {DIM}|{W}  {Y}{OWNER}{W}\n")


async def _run_account_task(ctx) -> None:
    """Держит аккаунт подключённым (run_until_disconnected)."""
    try:
        await ctx.client.run_until_disconnected()
    except Exception as e:
        logger.warning(f"[{ctx.display_name}] run_until_disconnected: {e}")


async def main() -> None:
    ensure_dirs()
    _print_banner()

    from core.account_manager import account_manager
    from core.session_migration import migrate_if_needed

    # 1. Миграция старой сессии
    migrated = await migrate_if_needed(PROJECT_ROOT, ACCOUNTS_DIR)
    if migrated:
        print(f"  {G}[✓]{W} Старая сессия успешно перенесена\n")

    # 2. Загрузка профилей
    profiles = account_manager.load_profiles(ACCOUNTS_DIR)

    # 3. Если нет аккаунтов — добавляем
    if not profiles:
        print(f"  {Y}Аккаунтов нет.{W} Добавим первый.\n")
        print(f"  Данные: {B}https://my.telegram.org/apps{W}\n")
        try:
            api_id   = int(input("  API_ID  › ").strip())
            api_hash = input("  API_HASH › ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  {R}Отменено.{W}"); return

        ctx = await account_manager.add_account(api_id, api_hash)
        if not ctx:
            print(f"  {R}[✗]{W} Не удалось добавить аккаунт."); return

        print(f"\n  {G}[✓]{W} Добавлен: {B}{ctx.display_name}{W}\n")
        account_manager.save_profile(ctx, ACCOUNTS_DIR)
        profiles = account_manager.load_profiles(ACCOUNTS_DIR)

    # 4. Параллельное подключение всех аккаунтов
    print(f"  {C}Подключаю аккаунты...{W}")
    ok, fail = await account_manager.start_all(profiles)
    print(f"  {G}[✓]{W} Подключено: {ok}  {R}[✗]{W} Ошибок: {fail}\n")

    connected = account_manager.connected()
    if not connected:
        print(f"  {R}Нет подключённых аккаунтов. Проверь сессии.{W}")
        return

    # 5. Активируем первый подключённый аккаунт (dispatcher + modules)
    first = connected[0]
    from core.account_runner import activate_account
    activate_account(first)
    account_manager.set_active_account.__func__   # satisfy linters
    account_manager._active_id = first.account_id

    print(f"  {G}[✓]{W} Активный аккаунт: {B}{first.display_name}{W}")
    for ctx in connected:
        flag = " ← активный" if ctx is first else ""
        print(f"       {'🟢' if ctx is first else '🔵'} {ctx.display_name}{flag}")
    print(f"\n  {DIM}Ctrl+C → остановка  |  .stop → меню  |  .accounts → список{W}\n")

    # 6. run_until_disconnected для каждого аккаунта как Task
    run_tasks = [
        asyncio.ensure_future(_run_account_task(ctx))
        for ctx in connected
    ]

    try:
        await asyncio.gather(*run_tasks, return_exceptions=True)
    except KeyboardInterrupt:
        pass
    finally:
        print(f"\n  {Y}Останавливаю все аккаунты...{W}")
        for t in run_tasks:
            if not t.done(): t.cancel()
        await account_manager.stop_all()
        print(f"  {G}[✓]{W} Завершено.\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
