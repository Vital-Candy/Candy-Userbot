from __future__ import annotations

import asyncio
from datetime import datetime

from telethon import events
from telethon.tl.functions.account import UpdateProfileRequest

import core.client as client_state
from core.dispatcher import register_command

TASK = "time_name"
STYLES = {
    1: "𝟭𝟰:𝟯𝟱",
    2: "𝟙𝟜:𝟛𝟝",
    3: "𝟷𝟺:𝟹𝟻",
    4: "¹⁴:³⁵",
    5: "⑭:㉟",
}
_handler = None
_conversation_handler = None
_waiting: dict[int, tuple[str, int | None]] = {}


def _state():
    from core.app import UserbotApp
    # account is attached by init; avoids global account singleton
    return _account.background.get_state(TASK, {})


def _format(style: int) -> str:
    now = datetime.now().strftime("%H:%M")

    alphabets = {
        1: "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵",
        2: "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡",
        3: "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿",
        4: "⁰¹²³⁴⁵⁶⁷⁸⁹",
        5: "⓪①②③④⑤⑥⑦⑧⑨",
    }

    table = str.maketrans(
        "0123456789",
        alphabets[style],
    )

    return now.translate(table)


async def _set_name(name: str) -> None:
    await client_state.client(UpdateProfileRequest(first_name=name))


async def _worker() -> None:
    while True:
        state = _account.background.get_state(TASK, {})
        if not state.get("enabled"):
            return
        style = int(state.get("style", 1))
        original = state.get("original_name", "")
        await _set_name(f"{original} | {_format(style)}")
        delay = 60 - datetime.now().second
        await asyncio.sleep(max(1, delay))


async def _enable(style: int) -> None:
    me = await client_state.client.get_me()
    current = (me.first_name or "").strip()
    state = _account.background.get_state(TASK, {})
    original = state.get("original_name") if state.get("enabled") else current
    if not original:
        original = current
    _account.background.set_state(TASK, {
        "enabled": True, "style": style, "original_name": original,
    })
    await _account.background.stop(TASK)
    await _account.background.start(TASK, _worker)


async def _disable() -> None:
    state = _account.background.get_state(TASK, {})
    await _account.background.stop(TASK)
    original = state.get("original_name", "")
    if original:
        await _set_name(original)
    _account.background.set_state(TASK, {
        "enabled": False, "style": int(state.get("style", 1)),
        "original_name": original,
    })


def _menu() -> str:
    return "🎨 <b>Выбери стиль:</b>\n\n" + "\n".join(
        f"[{n}] {v}" for n, v in STYLES.items()
    ) + "\n\nОтветь номером от 1 до 5."


async def _conversation(event):
    chat_id = event.chat_id
    waiting = _waiting.get(chat_id)
    if not waiting:
        return
    text = (event.raw_text or "").strip().lower()
    stage, command_id = waiting
    if stage == "confirm":
        if text not in {"да", "нет"}:
            return
        _waiting.pop(chat_id, None)
        await event.delete()
        if text == "нет":
            if command_id:
                await client_state.client.delete_messages(chat_id, command_id)
            return
        await client_state.client.edit_message(chat_id, command_id, _menu(), parse_mode="html")
        _waiting[chat_id] = ("style", command_id)
        return
    if stage == "style":
        if text not in {"1", "2", "3", "4", "5"}:
            return
        _waiting.pop(chat_id, None)
        await event.delete()
        await _enable(int(text))
        await client_state.client.edit_message(chat_id, command_id, f"✅ Часы включены\nСтиль: <code>{_format(int(text))}</code>", parse_mode="html")


async def _command(event):
    parts = (event.pattern_match.group(1) or "").strip().lower().split()
    state = _account.background.get_state(TASK, {})
    enabled = bool(state.get("enabled"))
    if parts[:1] == ["off"]:
        await _disable()
        await event.edit("✅ Часы выключены. Оригинальное имя восстановлено.")
        return
    if parts[:1] == ["on"] and len(parts) == 2 and parts[1].isdigit() and int(parts[1]) in STYLES:
        await _enable(int(parts[1]))
        await event.edit(f"✅ Часы включены. Стиль: <code>{_format(int(parts[1]))}</code>", parse_mode="html")
        return
    if parts:
        await event.edit("❌ Использование: <code>.time</code>, <code>.time on 1</code> или <code>.time off</code>", parse_mode="html")
        return
    if enabled:
        await event.edit(_menu(), parse_mode="html")
        _waiting[event.chat_id] = ("style", event.id)
    else:
        await event.edit("🕒 Часы выключены.\n\nВключить?\nОтветь: <b>Да</b> или <b>Нет</b>", parse_mode="html")
        _waiting[event.chat_id] = ("confirm", event.id)


def init() -> None:
    global _handler, _conversation_handler, _account
    if client_state.client is None:
        raise RuntimeError("TelegramClient не установлен")
    from core.app import current_account
    _account = current_account()
    register_command("time", "Часы в имени", ".time [on <1-5>/off]", "Дизайн")
    _handler = client_state.client.add_event_handler(_command, events.NewMessage(outgoing=True, pattern=r"^\.time(?:\s+(.*))?$"))
    _conversation_handler = client_state.client.add_event_handler(_conversation, events.NewMessage(outgoing=True))
    state = _account.background.get_state(TASK, {})
    if state.get("enabled"):
        asyncio.create_task(_resume())


async def _resume() -> None:
    me = await client_state.client.get_me()
    state = _account.background.get_state(TASK, {})
    # On every new launch, current Telegram name becomes the new original.
    current = (me.first_name or "").strip()
    old = state.get("original_name", "")
    suffix = f" | {_format(int(state.get('style', 1)))}"
    if old and current.startswith(old + " | "):
        current = old
    _account.background.update_state(TASK, original_name=current)
    await _account.background.start(TASK, _worker)


async def shutdown() -> None:
    global _handler, _conversation_handler
    _waiting.clear()
    state = _account.background.get_state(TASK, {})
    was_enabled = bool(state.get("enabled"))
    try:
        await _account.background.stop(TASK)
        original = state.get("original_name", "")
        if was_enabled and original:
            await _set_name(original)
    finally:
        # .stop restores the name but keeps auto-start enabled for the next launch.
        _account.background.set_state(TASK, {**state, "enabled": was_enabled})
    if client_state.client is not None:
        if _handler is not None:
            client_state.client.remove_event_handler(_handler)
        if _conversation_handler is not None:
            client_state.client.remove_event_handler(_conversation_handler)
    _handler = None
    _conversation_handler = None
