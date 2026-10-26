"""Небольшие SQL-помощники без зависимости от SQLAlchemy (переносимы между PostgreSQL и SQLite)."""
from __future__ import annotations

from typing import Iterable


def in_clause(name: str, values: Iterable, params: dict) -> str:
    """Строит `(:name_0, :name_1, ...)` и добавляет значения в params.

    Вместо `= ANY(:list)` (есть только в PostgreSQL) используется `IN (...)` с отдельным
    параметром на каждое значение: значения по-прежнему передаются параметрами, не подстановкой.
    Пустой список даёт `(NULL)` — условие `x IN (NULL)` ничего не выбирает.
    """
    values = list(values)
    if not values:
        return "(NULL)"
    keys = []
    for i, v in enumerate(values):
        key = f"{name}_{i}"
        params[key] = v
        keys.append(f":{key}")
    return "(" + ", ".join(keys) + ")"


def chunks(items: list, size: int = 500) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]
