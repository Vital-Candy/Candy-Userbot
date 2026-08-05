from __future__ import annotations

import importlib
import inspect
import pkgutil

_loaded: list[object] = []


def _call_init(module: object) -> None:
    callback = getattr(module, "init", None)
    if callback is None:
        return
    result = callback()
    if inspect.isawaitable(result):
        raise RuntimeError("Асинхронный init() не поддерживается")


def load_modules() -> list[str]:
    global _loaded
    import modules
    _loaded = []
    for info in pkgutil.iter_modules(modules.__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"modules.{info.name}")
        _call_init(module)
        _loaded.append(module)
    return [module.__name__ for module in _loaded]


async def shutdown_modules() -> None:
    global _loaded
    for module in reversed(_loaded):
        callback = getattr(module, "shutdown", None)
        if callback is None:
            continue
        result = callback()
        if inspect.isawaitable(result):
            await result
    _loaded = []


async def reload_modules() -> list[str]:
    global _loaded
    old = list(_loaded)
    await shutdown_modules()
    importlib.invalidate_caches()
    _loaded = []
    for module in old:
        module = importlib.reload(module)
        _call_init(module)
        _loaded.append(module)
    return [module.__name__ for module in _loaded]
