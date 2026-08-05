from __future__ import annotations

import asyncio
import os

from config import VERSION
from core.accounts import (
    account_from_profile,
    add_account,
    create_backup,
    profiles,
    restore_backup,
)
from core.app import UserbotApp
from core.client import set_client
from utils.logger import setup_logger
from utils.paths import ASSETS_DIR, ensure_dirs

logger = setup_logger()


def banner() -> None:
    os.system("cls" if os.name == "nt" else "clear")

    path = ASSETS_DIR / "banner.txt"
    if path.is_file():
        print(
            path.read_text(
                encoding="utf-8"
            )
        )

    print(f"🍬 Candy-Userbot v{VERSION}\n")


def choose(
    items: list[dict],
    title: str,
) -> str:
    print(title)
    for index, item in enumerate(
        items,
        start=1,
    ):
        name = (
            item.get("username")
            or item.get("name")
            or item.get("id")
        )
        print(f"[{index}] {name}")

    return input("\nВыбор: ").strip()


def backup_menu() -> None:
    while True:
        banner()
        print(
            "[1] Создать backup\n"
            "[2] Восстановить backup\n"
            "[0] Назад"
        )

        choice = input("\nВыбор: ").strip()

        if choice == "0":
            return

        if choice == "1":
            items = profiles()
            if not items:
                input(
                    "Нет аккаунтов. Enter"
                )
                continue

            selected = choose(
                items,
                "Выбери аккаунт",
            )
            if (
                selected.isdigit()
                and 1 <= int(selected)
                <= len(items)
            ):
                output = create_backup(
                    items[int(selected) - 1]
                )
                input(
                    f"✅ {output}\nEnter"
                )

        elif choice == "2":
            from utils.paths import BACKUP_DIR

            print(
                "Папка:",
                BACKUP_DIR,
            )
            path = input(
                "Имя ZIP или полный путь: "
            ).strip()

            try:
                restore_backup(path)
                print(
                    "✅ Backup восстановлен"
                )
            except Exception as exc:
                print("❌", exc)

            input("Enter")


async def run_account(
    profile: dict,
) -> None:
    from core.dispatcher import setup
    from core.loader import (
        load_modules,
        shutdown_modules,
    )

    account = account_from_profile(
        profile
    )
    app = UserbotApp(account)

    try:
        await app.start()
    except Exception as exc:
        print("❌", exc)
        input("Enter")
        return

    set_client(app.client)
    setup(
        app.client,
        app.stop_event,
    )
    load_modules()

    print(
        f"✅ Запущен: "
        f"{account.display_name}\n"
        "Команды: .help | .stop"
    )

    try:
        await app.stop_event.wait()
    finally:
        await shutdown_modules()
        set_client(None)
        await app.stop()


async def main() -> None:
    ensure_dirs()

    while True:
        banner()
        items = profiles()

        print("Аккаунты:\n")
        for index, item in enumerate(
            items,
            start=1,
        ):
            name = (
                item.get("username")
                or item.get("name")
                or item.get("id")
            )
            print(f"[{index}] {name}")

        print(
            "\n[A] Добавить аккаунт"
            "\n[B] Backup"
            "\n[0] Выход"
        )

        choice = input(
            "\nВыбор: "
        ).strip().lower()

        if choice == "0":
            return

        if choice == "a":
            try:
                await add_account()
                print(
                    "✅ Аккаунт добавлен"
                )
            except Exception as exc:
                print("❌", exc)

            input("Enter")
            continue

        if choice == "b":
            backup_menu()
            continue

        if (
            choice.isdigit()
            and 1 <= int(choice)
            <= len(items)
        ):
            await run_account(
                items[int(choice) - 1]
            )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
