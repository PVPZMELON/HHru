"""Простой раннер миграций: применяет migrations/*.sql по порядку имён, каждую один раз.

Применённые версии хранятся в таблице schema_migrations. Каждая миграция выполняется в
транзакции: при ошибке откатывается целиком, а последующие миграции не применяются.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import text

from src.config import PROJECT_ROOT

log = logging.getLogger(__name__)
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


def split_statements(sql: str) -> list[str]:
    """Делит SQL-скрипт на отдельные команды.

    Миграции проекта не содержат функций с $$ и точек с запятой внутри строк, поэтому
    достаточно удалить построчные комментарии и разделить по `;`.
    """
    without_comments = re.sub(r"--[^\n]*", "", sql)
    return [s.strip() for s in without_comments.split(";") if s.strip()]


def pending_migrations(applied: set[str], directory: Path = MIGRATIONS_DIR) -> list[Path]:
    return [p for p in sorted(directory.glob("*.sql")) if p.name not in applied]


def migrate(engine, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Применяет недостающие миграции; возвращает имена применённых файлов."""
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version TEXT PRIMARY KEY,"
            " applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
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
