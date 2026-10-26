"""Простой раннер миграций: применяет migrations/*.sql по порядку имён, каждую один раз.

Применённые версии хранятся в таблице schema_migrations. Каждая миграция выполняется в
транзакции (PostgreSQL: при ошибке откатывается целиком; SQLite: драйвер не оборачивает DDL в транзакцию,
поэтому при сбое возможно частичное применение — для учебной БД достаточно удалить файл и повторить),
последующие миграции при ошибке не применяются. Для SQLite используется
каталог migrations/sqlite/.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import text

from src.config import PROJECT_ROOT

log = logging.getLogger(__name__)
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"            # PostgreSQL
SQLITE_MIGRATIONS_DIR = MIGRATIONS_DIR / "sqlite"        # SQLite (те же таблицы, другие типы)


def split_statements(sql: str) -> list[str]:
    """Делит SQL-скрипт на отдельные команды.

    Миграции проекта не содержат функций с $$ и точек с запятой внутри строк, поэтому
    достаточно удалить построчные комментарии и разделить по `;`.
    """
    without_comments = re.sub(r"--[^\n]*", "", sql)
    return [s.strip() for s in without_comments.split(";") if s.strip()]


def pending_migrations(applied: set[str], directory: Path = MIGRATIONS_DIR) -> list[Path]:
    return [p for p in sorted(directory.glob("*.sql")) if p.name not in applied]


def migrate(engine, directory: Path | None = None) -> list[str]:
    """Применяет недостающие миграции; возвращает имена применённых файлов."""
    sqlite = engine.dialect.name == "sqlite"
    directory = directory or (SQLITE_MIGRATIONS_DIR if sqlite else MIGRATIONS_DIR)
    ts_type, ts_default = ("TEXT", "(strftime('%Y-%m-%d %H:%M:%f', 'now'))") if sqlite else ("TIMESTAMPTZ", "now()")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version TEXT PRIMARY KEY,"
            f" applied_at {ts_type} NOT NULL DEFAULT {ts_default})"
        ))
        applied = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations")).fetchall()}

    done: list[str] = []
    for path in pending_migrations(applied, directory):
        statements = split_statements(path.read_text(encoding="utf-8"))
        with engine.begin() as conn:  # одна транзакция на миграцию
            for stmt in statements:
                conn.execute(text(stmt))
            conn.execute(text("INSERT INTO schema_migrations (version) VALUES (:v)"), {"v": path.name})
        log.info("Применена миграция %s (%d команд)", path.name, len(statements))
        done.append(path.name)
    if not done:
        log.info("Схема актуальна, новых миграций нет")
    return done
