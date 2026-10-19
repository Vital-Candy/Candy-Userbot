"""Команда .spam: разбор кавычек и параметров, отправка, защита, остановка."""
from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.dispatcher import Dispatcher
from core.errors import UserError
from modules.spam.module import SpamModule
from modules.spam.parser import DEFAULT_DELAY, MAX_COUNT, MAX_TEXT, SpamRequest, parse_spam

try:
    from telethon.errors import FloodWaitError
except ImportError:  # Telethon не установлен
    FloodWaitError = None


class ParserTests(unittest.TestCase):
    def test_example_from_the_task(self):
        request = parse_spam('"скажи "привет"" 3 -d 0.5')
        self.assertEqual(request, SpamRequest('скажи "привет"', 3, 0.5))

    def test_defaults(self):
        self.assertEqual(parse_spam('"привет"'), SpamRequest("привет", 1, DEFAULT_DELAY))
        self.assertEqual(parse_spam('"привет" 5'), SpamRequest("привет", 5, DEFAULT_DELAY))
        self.assertEqual(parse_spam('"привет" -d 2'), SpamRequest("привет", 1, 2.0))

    def test_flags_in_any_order_and_decimal_comma(self):
        self.assertEqual(parse_spam('"a" -d 0,5 4'), SpamRequest("a", 4, 0.5))

    def test_quotes_inside_text_do_not_count(self):
        self.assertEqual(parse_spam('"a "b" c"').text, 'a "b" c')
        self.assertEqual(parse_spam('""x""').text, '"x"')
        # Цифры и -d внутри кавычек остаются текстом.
        self.assertEqual(parse_spam('"say 3 -d 1" 2'), SpamRequest("say 3 -d 1", 2, DEFAULT_DELAY))
        self.assertEqual(parse_spam('"он сказал " 5 " и ушёл" 2').text, 'он сказал " 5 " и ушёл')

    def test_smart_quotes_from_phone_keyboards(self):
        self.assertEqual(parse_spam("“привет” 2").text, "привет")

    def test_multiline_text_and_spaces_are_kept(self):
        self.assertEqual(parse_spam('"a\n  b" 2').text, "a\n  b")
        self.assertEqual(parse_spam('"  a  "').text, "  a  ")

    def test_errors(self):
        bad = [
            "", "привет", '"привет', '"привет" abc', '"привет" 3 4', '"привет" -d',
            '"привет" -d x', '"привет" -d 1 -d 2', '"привет" 0', f'"привет" {MAX_COUNT + 1}',
            '"привет" -d 0', '"привет" -d 99999', '"привет" -d nan', '"привет" -d inf',
            '""', '"   "', '"привет" -5', "\"x\" 3 -d 1 extra",
        ]
        for text in bad:
            with self.subTest(text=text), self.assertRaises(UserError):
                parse_spam(text)

    def test_text_length_limit(self):
        parse_spam('"' + "a" * MAX_TEXT + '"')
        with self.assertRaises(UserError):
            parse_spam('"' + "a" * (MAX_TEXT + 1) + '"')


def make_event(text, chat_id=10):
    edits: list[str] = []

    async def edit(value):
        edits.append(value)

    event = SimpleNamespace(
        raw_text=text, edit=edit, edits=edits, out=True, chat_id=chat_id, delete=AsyncMock()
    )
    return event


class ModuleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sent: list[tuple] = []
        self.delays: list[float] = []

        async def send_message(chat_id, text, **kwargs):
            self.sent.append((chat_id, text, kwargs))

        self.app = SimpleNamespace(
            dispatcher=Dispatcher(),
            client=SimpleNamespace(send_message=send_message),
            notify_owner=AsyncMock(return_value=True),
        )
        self.module = SpamModule(self.app)

        async def fake_sleep(seconds):
            self.delays.append(seconds)
            await asyncio.sleep(0)

        self.module._sleep = fake_sleep
        await self.module.start()

    async def asyncTearDown(self):
        await self.module.stop()

    async def run_command(self, text, chat_id=10):
        event = make_event(text, chat_id)
        await self.app.dispatcher.dispatch_command(event)
        return event

    async def finish(self):
        for job in list(self.module._jobs.values()):
            await job.task

    async def test_is_optional_module(self):
        self.assertFalse(self.module.required)

    async def test_sends_text_n_times_with_delay_and_deletes_command(self):
        event = await self.run_command('.spam "скажи "привет"" 3 -d 0.5')
        await self.finish()
        self.assertEqual([item[:2] for item in self.sent], [(10, 'скажи "привет"')] * 3)
        self.assertEqual(self.delays, [0.5, 0.5])  # между тремя сообщениями две паузы
        event.delete.assert_awaited_once()
        self.assertEqual(event.edits, [])
        self.assertEqual(self.module._jobs, {})

    async def test_text_is_sent_without_formatting(self):
        await self.run_command('.spam "*жирный* `код`"')
        await self.finish()
        self.assertIsNone(self.sent[0][2]["parse_mode"])

    async def test_default_delay_is_one_second(self):
        await self.run_command('.spam "a" 2')
        await self.finish()
        self.assertEqual(self.delays, [1.0])

    async def test_bad_arguments_answer_with_usage_and_send_nothing(self):
        event = await self.run_command(".spam привет")
        self.assertIn("Использование", event.edits[-1])
        self.assertTrue(event.edits[-1].startswith("❌"))
        self.assertEqual(self.sent, [])
        event.delete.assert_not_awaited()

    async def test_second_spam_in_same_chat_is_refused(self):
        gate = asyncio.Event()

        async def slow_sleep(seconds):
            await gate.wait()

        self.module._sleep = slow_sleep
        await self.run_command('.spam "a" 5')
        await asyncio.sleep(0)
        event = await self.run_command('.spam "b"')
        self.assertIn("уже идёт", event.edits[-1])
        other_chat = await self.run_command('.spam "c"', chat_id=11)  # другой чат можно
        self.assertEqual(other_chat.edits, [])
        gate.set()
        await self.finish()

    async def test_stop_cancels_running_spam(self):
        gate = asyncio.Event()

        async def slow_sleep(seconds):
            await gate.wait()

        self.module._sleep = slow_sleep
        await self.run_command('.spam "a" 50')
        await asyncio.sleep(0)
        sent_before = len(self.sent)
        event = await self.run_command(".spam stop")
        self.assertIn("Остановлено отправок: 1", event.edits[-1])
        self.assertEqual(len(self.sent), sent_before)
        self.assertEqual(self.module._jobs, {})
        again = await self.run_command(".spam stop")
        self.assertIn("ничего не отправляется", again.edits[-1])

    async def test_send_error_stops_and_notifies_owner(self):
        calls = {"n": 0}

        async def flaky(chat_id, text, **kwargs):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("нет прав")

        self.app.client.send_message = flaky
        with self.assertLogs("candy", level="ERROR"):
            await self.run_command('.spam "a" 10')
            await self.finish()
        self.assertEqual(calls["n"], 3)
        text = self.app.notify_owner.await_args.args[0]
        self.assertIn("отправлено 2 из 10", text)
        self.assertIn("нет прав", text)
        self.assertEqual(self.module._jobs, {})

    @unittest.skipIf(FloodWaitError is None, "Telethon не установлен")
    async def test_short_flood_wait_is_waited_and_retried(self):
        calls = {"n": 0}

        async def flood_once(chat_id, text, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise FloodWaitError(request=None, capture=7) if _flood_ok() else FloodWaitError()
            self.sent.append((chat_id, text, kwargs))

        self.app.client.send_message = flood_once
        with self.assertLogs("candy", level="WARNING"):
            await self.run_command('.spam "a"')
            await self.finish()
        self.assertEqual(len(self.sent), 1)  # сообщение доставлено со второй попытки
        self.app.notify_owner.assert_not_awaited()

    async def test_stop_of_module_cancels_jobs(self):
        gate = asyncio.Event()

        async def slow_sleep(seconds):
            await gate.wait()

        self.module._sleep = slow_sleep
        await self.run_command('.spam "a" 50')
        await asyncio.sleep(0)
        await self.module.stop()
        self.assertEqual(self.module._jobs, {})
        self.assertNotIn("spam", self.app.dispatcher.commands)


def _flood_ok() -> bool:
    """Настоящий FloodWaitError принимает request/capture; заглушка — без аргументов."""
    try:
        FloodWaitError(request=None, capture=1)
        return True
    except TypeError:
        return False


if __name__ == "__main__":
    unittest.main()
