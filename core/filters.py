"""Фильтры событий. Фильтр: ``f(event) -> bool`` или корутина, возвращающая bool.

Комбинаторы принимают и обычные, и асинхронные фильтры. Если среди проверок
встретилась асинхронная, результат комбинатора тоже нужно ``await``-ить:
диспетчер делает это сам.
"""
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

Filter = Callable[[Any], "bool | Awaitable[bool]"]


async def _finish_all(pending: Awaitable[bool], rest: tuple[Filter, ...], event: Any) -> bool:
    """Продолжение ``all_filters`` после первого асинхронного фильтра (он уже вызван: ждём его)."""
    if not await pending:
        return False
    for check in rest:
        result = check(event)
        if inspect.isawaitable(result):
            result = await result
        if not result:
            return False
    return True


async def _finish_any(pending: Awaitable[bool], rest: tuple[Filter, ...], event: Any) -> bool:
    """Продолжение ``any_filter`` после первого асинхронного фильтра."""
    if await pending:
        return True
    for check in rest:
        result = check(event)
        if inspect.isawaitable(result):
            result = await result
        if result:
            return True
    return False


def all_filters(*filters: Filter) -> Filter:
    """Истина, если прошли все фильтры (пустой набор пропускает всё)."""

    def combined(event: Any):
        """Проверяет фильтры по порядку; возвращает bool или корутину (если встретился async-фильтр)."""
        # Пока фильтры синхронные, обходимся без корутины; при первом асинхронном
        # передаём остаток в _finish_*, чтобы не вызывать фильтры повторно.
        for index, check in enumerate(filters):
            result = check(event)
            if inspect.isawaitable(result):
                return _finish_all(result, filters[index + 1:], event)
            if not result:
                return False
        return True

    return combined


def any_filter(*filters: Filter) -> Filter:
    """Истина, если прошёл хотя бы один фильтр (пустой набор ничего не пропускает)."""

    def combined(event: Any):
        """Возвращает True на первом прошедшем фильтре; bool или корутину."""
        for index, check in enumerate(filters):
            result = check(event)
            if inspect.isawaitable(result):
                return _finish_any(result, filters[index + 1:], event)
            if result:
                return True
        return False

    return combined


def not_filter(check: Filter) -> Filter:
    """Инвертирует фильтр."""

    async def _invert(pending: Awaitable[bool]) -> bool:
        """Ждёт асинхронный фильтр и инвертирует его результат."""
        return not await pending

    def inverted(event: Any):
        """Инвертированная проверка: bool или корутина, если исходный фильтр асинхронный."""
        result = check(event)
        if inspect.isawaitable(result):
            return _invert(result)
        return not result

    return inverted


def incoming(event: Any) -> bool:
    """Сообщение пришло от другого пользователя (нет признака ``out``)."""
    return not bool(getattr(event, "out", False))


def outgoing(event: Any) -> bool:
    """Сообщение отправлено самим аккаунтом."""
    return bool(getattr(event, "out", False))


def private(event: Any) -> bool:
    """Личный чат (включая «Избранное»)."""
    return bool(getattr(event, "is_private", False))


def group(event: Any) -> bool:
    """Группа (в том числе супергруппа)."""
    return bool(getattr(event, "is_group", False))


def channel(event: Any) -> bool:
    """Канал."""
    return bool(getattr(event, "is_channel", False))


def is_reply(event: Any) -> bool:
    """Сообщение написано в ответ на другое."""
    return bool(getattr(event, "is_reply", False))
