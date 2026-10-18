"""Этап 5: метки, .goto, ссылки, экранирование Markdown."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.dispatcher import Dispatcher
from modules.storage.labels import LabelsModule
from storage.service import Storage
from utils.links import message_link
from utils.text import escape_markdown, has_markdown_syntax

CHANNEL = -1001234567890
USER = 555
GROUP = -4242


class LinkTests(unittest.TestCase):
    def test_channel_and_supergroup(self):
        self.assertEqual(message_link(CHANNEL, 7), "https://t.me/c/1234567890/7")

    def test_private_chat_and_saved_messages(self):
        self.assertEqual(message_link(USER, 9), "tg://openmessage?user_id=555&message_id=9")

    def test_basic_group_has_no_link(self):
        self.assertIsNone(message_link(GROUP, 1))
        self.assertIsNone(message_link(0, 1))

    def test_boundary(self):
        self.assertEqual(message_link(-1_000_000_000_001, 5), "https://t.me/c/1/5")
        self.assertIsNone(message_link(-999_999_999_999, 5))


class MarkdownTests(unittest.TestCase):
    def test_plain_text_is_untouched(self):
        for text in ("todo", "к-покупке", "a_b", "v1.2", "#tag", "a@b"):
            self.assertEqual(escape_markdown(text), text)
            self.assertFalse(has_markdown_syntax(text))

    def test_special_characters_are_neutralised(self):
        for text in ("**bold**", "[x](http://e)", "`code`", "~~s~~", "||spoil||", "a\\b", "__it__"):
            safe = escape_markdown(text)
            self.assertTrue(has_markdown_syntax(text), text)
            self.assertFalse(has_markdown_syntax(safe), (text, safe))

    def test_empty(self):
        self.assertEqual(escape_markdown(""), "")


class LabelFixture:
    def __init__(self, path: Path | None = None):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = path or Path(self.tmp.name) / "db" / "candy.sqlite3"
        self.open()

    def open(self):
        self.storage = Storage(self.path)
        self.storage.open()
        self.app = SimpleNamespace(
            dispatcher=Dispatcher(),
            storage=self.storage,
            identity=SimpleNamespace(account_id=AsyncMock(return_value=1)),
        )
        self.module = LabelsModule(self.app)

    async def start(self):
        await self.module.start()

    async def run(self, text, *, chat_id=USER, reply_id=7):
        edits: list[str] = []

        async def edit(value):
            edits.append(value)

        reply = SimpleNamespace(id=reply_id) if reply_id is not None else None
        event = SimpleNamespace(
            raw_text=text,
            chat_id=chat_id,
            get_reply_message=AsyncMock(return_value=reply),
            edit=edit,
        )
        await self.app.dispatcher.dispatch_command(event)
        return edits[-1]

    def close(self):
        self.storage.close()
        self.tmp.cleanup()


class GotoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx = LabelFixture()
        await self.fx.start()

    async def asyncTearDown(self):
        self.fx.close()

    async def test_goto_returns_link_to_labelled_message(self):
        await self.fx.run(".label todo", chat_id=CHANNEL, reply_id=42)
        reply = await self.fx.run(".goto todo", reply_id=None, chat_id=USER)
        self.assertIn("https://t.me/c/1234567890/42", reply)
        self.assertIn("[сообщение](", reply)
        self.assertIn("UTC", reply)

    async def test_goto_works_without_reply_and_from_another_chat(self):
        await self.fx.run(".label read", chat_id=USER, reply_id=3)
        reply = await self.fx.run(".goto read", chat_id=CHANNEL, reply_id=None)
        self.assertIn("tg://openmessage?user_id=555&message_id=3", reply)

    async def test_goto_is_case_insensitive(self):
        await self.fx.run(".label Todo", reply_id=1)
        self.assertIn("tg://", await self.fx.run(".goto TODO", reply_id=None))

    async def test_goto_unknown_label(self):
        reply = await self.fx.run(".goto nothing", reply_id=None)
        self.assertTrue(reply.startswith("❌"))
        self.assertIn("nothing", reply)

    async def test_goto_usage_and_bad_name(self):
        self.assertIn("Использование", await self.fx.run(".goto", reply_id=None))
        self.assertIn("Использование", await self.fx.run(".goto a b", reply_id=None))
        self.assertTrue((await self.fx.run(".goto " + "x" * 80, reply_id=None)).startswith("❌"))

    async def test_goto_lists_several_newest_first(self):
        for message_id in (1, 2, 3):
            await self.fx.run(".label same", reply_id=message_id)
        reply = await self.fx.run(".goto same", reply_id=None)
        lines = reply.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn("message_id=3", lines[1])
        self.assertIn("message_id=1", lines[3])

    async def test_goto_limits_output(self):
        for message_id in range(1, 15):
            await self.fx.run(".label many", reply_id=message_id)
        reply = await self.fx.run(".goto many", reply_id=None)
        self.assertEqual(len(reply.splitlines()), 1 + 10 + 1)
        self.assertIn("ещё 4", reply)

    async def test_goto_for_basic_group_has_no_link_but_says_so(self):
        await self.fx.run(".label grp", chat_id=GROUP, reply_id=8)
        reply = await self.fx.run(".goto grp", reply_id=None)
        self.assertIn("ссылки нет", reply)
        self.assertNotIn("](", reply)

    async def test_labels_are_per_account(self):
        await self.fx.run(".label mine", reply_id=1)
        self.fx.app.identity.account_id.return_value = 2
        self.assertIn("нет", await self.fx.run(".goto mine", reply_id=None))

    async def test_stop_unregisters_goto(self):
        await self.fx.module.stop()
        self.assertNotIn("goto", self.fx.app.dispatcher.commands)


class PersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_label_survives_userbot_restart(self):
        fx = LabelFixture()
        try:
            await fx.start()
            await fx.run(".label keep", chat_id=CHANNEL, reply_id=77)
            await fx.module.stop()
            fx.storage.close()

            fx.open()  # «перезапуск»: новая база, новый диспетчер, новый модуль
            await fx.start()
            reply = await fx.run(".goto keep", reply_id=None)
            self.assertIn("https://t.me/c/1234567890/77", reply)
        finally:
            fx.close()


class MarkdownSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx = LabelFixture()
        await self.fx.start()

    async def asyncTearDown(self):
        self.fx.close()

    async def test_markdown_in_new_names_is_rejected(self):
        for name in ("**x**", "a[b]", "`c`", "a__b", "~~s~~", "a|b", "x(y)"):
            reply = await self.fx.run(f".label {name}")
            self.assertTrue(reply.startswith("❌"), name)
            self.assertIn("Markdown", reply)
        self.assertEqual(self.fx.storage.labels.list_for_message(account_id=1, chat_id=USER, message_id=7), [])

    async def test_ordinary_punctuation_is_allowed(self):
        for name in ("to-do", "a_b", "v1.2", "#tag", "купить!"):
            self.assertIn("установлена", await self.fx.run(f".label {name}"), name)

    async def test_legacy_name_with_markdown_is_escaped_on_output(self):
        # Метка, созданная прежней версией, где такие имена ещё разрешались.
        self.fx.storage.database.execute(
            "INSERT INTO labels(account_id, chat_id, message_id, name, created_at) "
            "VALUES(1, ?, 7, '**evil**[x](y)', '2026-01-01T00:00:00+00:00')",
            (USER,),
        )
        listing = await self.fx.run(".labels")
        self.assertFalse(has_markdown_syntax(listing.split("—", 1)[1]))
        self.assertIn("evil", listing)


if __name__ == "__main__":
    unittest.main()
