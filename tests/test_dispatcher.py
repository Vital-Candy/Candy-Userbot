from __future__ import annotations

import asyncio
import unittest

from core.dispatcher import Dispatcher
from core.parser import CommandParser


class FakeEvent:
    def __init__(self, text: str) -> None:
        self.raw_text = text


class DispatcherTests(unittest.TestCase):
    def test_command_parser(self) -> None:
        parser = CommandParser(".")
        result = parser.parse(".hello one two")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.name, "hello")
        self.assertEqual(result.args, ("one", "two"))
        self.assertIsNone(parser.parse("hello"))

    def test_priority_and_error_isolation(self) -> None:
        async def scenario() -> None:
            dispatcher = Dispatcher()
            order: list[str] = []

            async def broken(_event) -> None:
                raise RuntimeError("test error")

            async def high(_event) -> None:
                order.append("high")

            async def low(_event) -> None:
                order.append("low")

            dispatcher.register("new_message", low, priority=1)
            dispatcher.register("new_message", broken, priority=20)
            dispatcher.register("new_message", high, priority=10)

            await dispatcher.dispatch("new_message", FakeEvent("hello"))
            self.assertEqual(order, ["high", "low"])

        asyncio.run(scenario())

    def test_command_context(self) -> None:
        async def scenario() -> None:
            dispatcher = Dispatcher()
            received: list[tuple[str, tuple[str, ...]]] = []

            async def command(event) -> None:
                parsed = dispatcher.get_command(event)
                assert parsed is not None
                received.append((parsed.name, parsed.args))

            dispatcher.register_command("test", command)
            event = FakeEvent(".test alpha beta")
            await dispatcher.dispatch_command(event)

            self.assertEqual(received, [("test", ("alpha", "beta"))])
            self.assertIsNone(dispatcher.get_command(event))

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
