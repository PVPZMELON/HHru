"""Выбор БД из окружения и переносимые SQL-помощники."""
from pathlib import Path

import pytest

from src import config
from src.db.sqlutil import chunks, in_clause


def _env(**kw):
    return lambda key, default=None: kw.get(key, default)


def test_sqlite_by_default_without_db_host():
    db = config._db_settings(_env())
    assert db.backend == "sqlite" and db.url.startswith("sqlite:///") and db.url.endswith("data/hh_market.sqlite")
    assert db.safe_url == db.url


def test_postgres_when_host_set_or_forced():
    assert config._db_settings(_env(DB_HOST="db", DB_PASSWORD="p@ss")).backend == "postgres"
    db = config._db_settings(_env(DB_BACKEND="postgres", DB_PASSWORD="p@ss", DB_SSLMODE="require"))
    assert "p%40ss" in db.url and db.url.endswith("?sslmode=require") and "p@ss" not in db.safe_url and "***" in db.safe_url
    assert config._db_settings(_env(DB_HOST="db", DB_BACKEND="sqlite")).backend == "sqlite"


def test_invalid_backend_and_relative_path():
    with pytest.raises(ValueError):
        config._db_settings(_env(DB_BACKEND="oracle"))
    db = config._db_settings(_env(DB_PATH="data/x.sqlite"))
    assert db.path == config.PROJECT_ROOT / "data" / "x.sqlite"
    assert config._db_settings(_env(DB_PATH="/tmp/y.sqlite")).path == Path("/tmp/y.sqlite")


def test_in_clause_params_and_empty():
    params = {}
    assert in_clause("r", ["Москва", "Казань"], params) == "(:r_0, :r_1)"
    assert params == {"r_0": "Москва", "r_1": "Казань"}
    assert in_clause("r", [], {}) == "(NULL)"
    assert [len(c) for c in chunks(list(range(5)), 2)] == [2, 2, 1]
