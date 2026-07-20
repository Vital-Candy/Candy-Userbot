# core/loader.py
import os
import sys
import importlib
import asyncio
import logging
from config import MODULES_DIR
from utils.paths import PROJECT_ROOT

MODULES_PATH = os.path.join(PROJECT_ROOT, MODULES_DIR)

logger = logging.getLogger("loader")

class ModuleLoader:
    def __init__(self):
        self.loaded_modules = []

    def load_modules(self):
        loaded = []
        if not os.path.exists(MODULES_PATH):
            os.makedirs(MODULES_PATH)
        for filename in sorted(os.listdir(MODULES_PATH)):
            if filename.endswith(".py") and not filename.startswith("_"):
                modname = filename[:-3]
                modpath = os.path.join(MODULES_PATH, filename)
                if not self._is_safe_module(modpath):
                    continue
                try:
                    module = importlib.import_module(f"{MODULES_DIR}.{modname}")
                    if not hasattr(module, "init"):
                        logger.warning(f"Модуль {modname} не имеет init(), пропущен")
                        continue
                    module.init()
                    loaded.append(modname)
                    logger.info(f"Модуль {modname} загружен")
                except Exception as e:
                    logger.error(f"Ошибка загрузки модуля {modname}: {e}")
                    continue
        self.loaded_modules = loaded
        return loaded

    async def reload_modules(self):
        if not self.loaded_modules:
            return []
        reloaded = []
        for modname in self.loaded_modules:
            full_name = f"{MODULES_DIR}.{modname}"
            try:
                # Вызов shutdown() перед перезагрузкой
                if full_name in sys.modules:
                    old_module = sys.modules[full_name]
                    if hasattr(old_module, "shutdown"):
                        try:
                            if asyncio.iscoroutinefunction(old_module.shutdown):
                                await old_module.shutdown()
                            else:
                                old_module.shutdown()
                            logger.info(f"Модуль {modname}: shutdown() выполнен")
                        except Exception as e:
                            logger.error(f"Ошибка shutdown() в {modname}: {e}")

                # Перезагрузка модуля
                mod = importlib.reload(sys.modules[full_name] if full_name in sys.modules else importlib.import_module(full_name))
                if hasattr(mod, "init"):
                    mod.init()
                reloaded.append(modname)
                logger.info(f"Модуль {modname} перезагружен")
            except Exception as e:
                logger.error(f"Ошибка перезагрузки модуля {modname}: {e}")
                continue
        return reloaded

    def _is_safe_module(self, filepath):
        import re
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                code = f.read()
            if re.search(r'\beval\(', code) or re.search(r'\bexec\(', code):
                logger.warning(f"Модуль {filepath} содержит опасный вызов: eval/exec")
                return False
            return True
        except Exception:
            return False

loader = ModuleLoader()
load_modules = loader.load_modules
reload_modules = loader.reload_modules    # теперь это асинхронная функция