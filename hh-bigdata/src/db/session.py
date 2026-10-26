"""Подключение к БД (SQLite или PostgreSQL) и вспомогательные функции чтения.

Весь доступ к БД идёт через параметризованные запросы (`text()` + именованные параметры),
подстановка значений в SQL-строки вручную нигде не используется.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, event, text

from src.config import get_settings

# Столбцы-даты в SQLite хранятся текстом «YYYY-MM-DD HH:MM:SS» (UTC): так строки сравниваются
# как даты, а при чтении переводятся в datetime с часовым поясом UTC (как в PostgreSQL).
DATETIME_COLUMNS = {
    "published_at", "source_updated_at", "started_at", "finished_at", "first_seen_at",
    "last_seen_at", "updated_at", "created_at", "first_loaded", "last_seen", "d_min", "d_max", "applied_at",
}
BOOLEAN_COLUMNS = {"salary_gross"}


def _adapt_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _py_lower(value):
    """Юникодный lower() для SQLite (встроенный понижает регистр только ASCII, а у нас кириллица)."""
    return value.lower() if isinstance(value, str) else value


sqlite3.register_adapter(datetime, _adapt_datetime)
sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_adapter(Decimal, float)


def dialect_name(conn_or_engine) -> str:
    return conn_or_engine.dialect.name


def is_sqlite(conn_or_engine) -> bool:
    return dialect_name(conn_or_engine) == "sqlite"


def _prepare_sqlite(engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        dbapi_conn.execute("PRAGMA foreign_keys = ON")      # без этого REFERENCES / ON DELETE CASCADE не работают
        dbapi_conn.create_function("lower", 1, _py_lower, deterministic=True)


@lru_cache(maxsize=1)
def get_engine():
    """Единый Engine приложения. Пароль в логи не попадает."""
    settings = get_settings()
    if settings.db.backend == "sqlite":
        settings.db.path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(settings.db.url, future=True)
        _prepare_sqlite(engine)
        return engine
    return create_engine(settings.db.url, pool_pre_ping=True, future=True)


def query_df(conn, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    """Выполняет SELECT и возвращает DataFrame.

    NUMERIC из PostgreSQL приходит как decimal.Decimal -> без приведения столбец получил бы
    dtype=object и сломал статистику, поэтому такие столбцы переводятся в float. Для SQLite даты
    (текст) и логические значения (0/1) приводятся к тем же типам, что и в PostgreSQL.
    """
    result = conn.execute(text(sql), params or {})
    rows = result.fetchall()
    columns = list(result.keys())
    df = pd.DataFrame([tuple(r) for r in rows], columns=columns)
    sqlite = is_sqlite(conn)
    for col in df.columns:
        if sqlite and col in DATETIME_COLUMNS and not pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
            continue
        if sqlite and col in BOOLEAN_COLUMNS:
            df[col] = pd.Series([None if pd.isna(v) else bool(v) for v in df[col]], index=df.index, dtype=object)
            continue
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
