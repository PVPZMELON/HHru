"""Подключение к PostgreSQL и вспомогательные функции чтения.

Весь доступ к БД идёт через параметризованные запросы (`text()` + именованные параметры),
подстановка значений в SQL-строки вручную нигде не используется.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text

from src.config import get_settings


@lru_cache(maxsize=1)
def get_engine():
    """Единый Engine приложения (пул соединений). Пароль в логи не попадает."""
    settings = get_settings()
    return create_engine(settings.db.url, pool_pre_ping=True, future=True)


def query_df(conn, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    """Выполняет SELECT и возвращает DataFrame.

    NUMERIC из PostgreSQL приходит как decimal.Decimal -> без приведения столбец получил бы
    dtype=object и сломал статистику, поэтому такие столбцы переводятся в float.
    """
    result = conn.execute(text(sql), params or {})
    rows = result.fetchall()
    columns = list(result.keys())
    df = pd.DataFrame([tuple(r) for r in rows], columns=columns)
    for col in df.columns:
        if df[col].dtype == object:
            non_null = df[col].dropna()
            if not len(non_null):
                continue
            if non_null.map(lambda v: isinstance(v, Decimal)).all():
                df[col] = df[col].astype(float)
            elif non_null.map(lambda v: isinstance(v, datetime)).all():
                df[col] = pd.to_datetime(df[col], utc=True)  # единый UTC-dtype независимо от смещений
    return df


def check_connection(engine=None) -> tuple[bool, str]:
    """Проверка доступности БД: (ok, сообщение без секретов)."""
    engine = engine or get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "соединение установлено"
    except Exception as exc:  # noqa: BLE001 — показываем причину пользователю
        return False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
