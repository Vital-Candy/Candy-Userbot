# core/loader.py
"""
Загрузчик модулей.

Этап 2: load_modules(raw_client, ctx) — принимает явный клиент и контекст.
Модули вызывают init() который регистрирует handlers через proxy `client`.
Shutdown вызывается через shutdown_modules(ctx).
"""
from __future__ import annotations
import asyncio, importlib, logging, sys
from pathlib import Path
from config import MODULES_DIR
from utils.paths import PROJECT_ROOT

MODULES_PATH = PROJECT_ROOT / MODULES_DIR
logger = logging.getLogger("loader")

_loaded_names: list[str] = []   # имена последней загрузки


def load_modules(raw_client, ctx) -> list[str]:
    """
    Загружает все модули из modules/.
    raw_client используется для обновления прокси перед init().
    ctx.handlers будет пополняться через прокси.
    """
    from core.client import _set_current_client
    _set_current_client(raw_client)   # прокси → raw_client этого аккаунта

    MODULES_PATH.mkdir(parents=True, exist_ok=True)
    result = []
    for fname in sorted(MODULES_PATH.iterdir()):
        if not fname.suffix == ".py" or fname.stem.startswith("_"):
            continue
        name = fname.stem
        try:
            mod = importlib.import_module(f"{MODULES_DIR}.{name}")
            if not hasattr(mod, "init"):
                logger.warning(f"{name}: нет init(), пропущен"); continue
            mod.init()
            result.append(name)
            logger.info(f"[LOAD] {name}")
        except Exception as e:
            logger.error(f"[FAIL] {name}: {e}")

    _loaded_names[:] = result
    return result


async def reload_modules(raw_client, ctx) -> list[str]:
    """
    Перезагружает модули: shutdown → reload/import → init.
    Подхватывает новые файлы, убирает удалённые.
    """
    from core.client import _set_current_client
    _set_current_client(raw_client)

    MODULES_PATH.mkdir(parents=True, exist_ok=True)
    on_disk = {
        f.stem for f in MODULES_PATH.iterdir()
        if f.suffix == ".py" and not f.stem.startswith("_")
    }

    # Shutdown удалённых модулей
    for name in set(_loaded_names) - on_disk:
        await _shutdown_one(name)

    result = []
    for name in sorted(on_disk):
        full = f"{MODULES_DIR}.{name}"
        try:
            await _shutdown_one(name)
            mod = importlib.reload(sys.modules[full]) if full in sys.modules else importlib.import_module(full)
            if hasattr(mod, "init"):
                mod.init()
            result.append(name)
            logger.info(f"[RELOAD] {name}")
        except Exception as e:
            logger.error(f"[RELOAD FAIL] {name}: {e}")

    _loaded_names[:] = result
    return result


def shutdown_modules(ctx) -> None:
    """Синхронный shutdown всех загруженных модулей."""
    for name in list(_loaded_names):
        mod = sys.modules.get(f"{MODULES_DIR}.{name}")
        if mod and hasattr(mod, "shutdown"):
            try:
                r = mod.shutdown()
                if asyncio.iscoroutine(r):
                    # Если нужен await — логируем, но не ломаем sync-контекст
                    logger.warning(f"{name}.shutdown() вернул корутину в sync-контексте")
            except Exception as e:
                logger.error(f"[SHUTDOWN FAIL] {name}: {e}")
    _loaded_names.clear()


async def _shutdown_one(name: str) -> None:
    mod = sys.modules.get(f"{MODULES_DIR}.{name}")
    if mod and hasattr(mod, "shutdown"):
        try:
            r = mod.shutdown()
            if asyncio.iscoroutine(r): await r
        except Exception as e:
            logger.error(f"[SHUTDOWN FAIL] {name}: {e}")
