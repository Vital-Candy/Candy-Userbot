"""Абстрактный базовый класс плагина. Загрузкой и выгрузкой занимается core/plugins.py."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.plugin_api import PluginAPI


class Plugin(ABC):
    """Базовый класс плагина.

    * ``version``: версия самого плагина;
    * ``min_core``: минимальная версия ядра (например ``"0.6"``), пусто: любая;
    * ``requires``: имена других плагинов (имена их файлов без ``.py``), они загружаются раньше.

    Перед ``setup()`` менеджер кладёт в ``self.api`` объект :class:`PluginAPI`.
    Всё, что зарегистрировано через него, снимается при выгрузке автоматически.
    """

    name = "unnamed"
    description = ""
    version = "1.0.0"
    min_core = ""
    requires: tuple[str, ...] = ()

    def __init__(self, app: Any) -> None:
        self.app = app
        self.api: PluginAPI | None = None

    @abstractmethod
    async def setup(self) -> None:
        """Подготовить плагин: зарегистрировать команды, обработчики и задачи через ``self.api``."""
        ...

    async def teardown(self) -> None:
        """Освободить ресурсы плагина. По умолчанию ничего не делает.

        Регистрации через ``self.api`` снимаются сами, здесь нужны только собственные ресурсы.
        """
        pass
