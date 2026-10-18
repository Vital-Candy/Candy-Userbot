from __future__ import annotations
import asyncio,tempfile
from pathlib import Path
import unittest
from core.console import ConsoleManager
from core.module import Module
from core.modules import ModuleManager
from core.plugin import Plugin
from core.plugins import PluginManager
class App:
    def __init__(self): self.modules=ModuleManager(self); self.plugins=None
    async def stop(self): pass
class Tests(unittest.TestCase):
    def test_plugin_lifecycle(self):
        async def run():
            app=App()
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/"demo.py"; p.write_text("from core.plugin import Plugin\nclass Demo(Plugin):\n async def setup(self): self.app.loaded=True\n async def teardown(self): self.app.loaded=False\ndef create_plugin(app): return Demo(app)\n",encoding="utf-8")
                app.plugins=PluginManager(app,Path(d)); await app.plugins.load_all(); self.assertTrue(app.loaded); await app.plugins.unload("demo"); self.assertFalse(app.loaded)
        asyncio.run(run())
    def test_console_help(self):
        async def run():
            app=App(); app.plugins=PluginManager(app,Path(tempfile.mkdtemp())); result=await ConsoleManager(app).execute("help"); self.assertIn("plugin load",result or "")
        asyncio.run(run())
if __name__=="__main__": unittest.main()
