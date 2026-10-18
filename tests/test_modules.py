import asyncio
import unittest

from core.background import BackgroundManager


class BackgroundManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_callback_does_not_kill_task(self):
        calls = 0

        async def callback():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("test")

        manager = BackgroundManager()
        manager.register("test", callback, interval=0.01)
        await manager.start_all()
        await asyncio.sleep(0.045)
        await manager.stop_all()

        self.assertGreaterEqual(calls, 2)

    async def test_stop_all(self):
        manager = BackgroundManager()
        manager.register("test", lambda: None, interval=0.01)
        await manager.start_all()
        self.assertIsNotNone(manager.list()[0].task)
        await manager.stop_all()
        self.assertIsNone(manager.list()[0].task)


if __name__ == "__main__":
    unittest.main()
