"""Общие фикстуры. Интеграционные тесты БД запускаются, только если задан TEST_DATABASE_URL
(отдельная БД, имя которой содержит «test»: схема public в ней ПЕРЕСОЗДАЁТСЯ) и установлен SQLAlchemy."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL не задан — интеграционные тесты БД пропущены")
    db_name = url.rsplit("/", 1)[-1].split("?")[0]
    if "test" not in db_name.lower():
        pytest.skip(f"БД {db_name!r} не похожа на тестовую (в имени должно быть «test») — пропуск из соображений безопасности")
    sqlalchemy = pytest.importorskip("sqlalchemy")
    return sqlalchemy.create_engine(url)


@pytest.fixture()
def db(engine):
    """Чистая схема с применёнными миграциями для каждого теста."""
    from sqlalchemy import text
    from src.db.migrate import migrate
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    migrate(engine)
    return engine


def hh_item(i: int = 1, **over) -> dict:
    """Минимальная вакансия в формате hh.ru для тестов."""
    item = {
        "id": str(i), "name": f"Python-разработчик {i}",
        "area": {"id": "1", "name": "Москва"},
        "employer": {"id": f"e{i}", "name": "ООО «Ромашка»"},
        "professional_roles": [{"id": "96", "name": "Программист, разработчик"}],
        "published_at": "2026-10-01T12:30:00+0300", "experience": {"name": "От 1 года до 3 лет"},
        "employment": {"name": "Полная занятость"}, "schedule": {"name": "Полный день"},
        "salary": {"from": 100000, "to": 200000, "currency": "RUR", "gross": True},
        "key_skills": [{"name": "Python"}, {"name": "SQL"}],
        "description": "<p>Нужен Python и Docker</p>", "alternate_url": f"https://hh.ru/vacancy/{i}",
    }
    item.update(over)
    return item
