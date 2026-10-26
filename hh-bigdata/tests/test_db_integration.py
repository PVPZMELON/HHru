"""Интеграционные тесты БД: SQLite всегда, PostgreSQL — при заданном TEST_DATABASE_URL (см. conftest.py)."""
import copy

import pytest
from sqlalchemy import text

from src.analytics import queries as q
from src.analytics.filters import Filters
from src.db.loader import LoadStats, finish_run, load_records, save_issues, start_run
from src.db.migrate import migrate, split_statements
from src.db.session import query_df
from src.etl.transform import transform_batch
from src.pipeline import run_etl
from tests.conftest import hh_item


def scalar(engine, sql, **p):
    with engine.connect() as c:
        return c.execute(text(sql), p).scalar()


def load(engine, items, origin="import"):
    res = transform_batch(items, origin)
    run = start_run(engine, origin, "test")
    with engine.begin() as conn:
        stats = load_records(conn, run, res.records)
        save_issues(conn, run, res.issues)
    return stats, run


def test_split_statements_ignores_comments():
    assert split_statements("-- c; x\nCREATE TABLE a (x int); -- tail\nSELECT 1;") == ["CREATE TABLE a (x int)", "SELECT 1"]


def test_migrations_applied_once(db):
    assert migrate(db) == []                                   # fixture уже применила все
    assert scalar(db, "SELECT count(*) FROM schema_migrations") == 2
    listing = ("SELECT name FROM sqlite_master WHERE type='table'" if db.dialect.name == "sqlite"
               else "SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
    tables = {r[0] for r in query_df_rows(db, listing)}
    assert {"vacancies", "employers", "regions", "skills", "vacancy_skills", "etl_runs", "data_quality_issues",
            "professional_roles"} <= tables


def query_df_rows(engine, sql):
    with engine.connect() as c:
        return c.execute(text(sql)).fetchall()


def test_load_is_idempotent(db):
    items = [hh_item(i) for i in range(1, 11)]
    s1, _ = load(db, items)
    links_before = scalar(db, "SELECT count(*) FROM vacancy_skills")
    s2, _ = load(db, items)
    s3, _ = load(db, copy.deepcopy(items))
    assert (s1.inserted, s1.updated, s1.unchanged) == (10, 0, 0)
    assert (s2.inserted, s2.updated, s2.unchanged) == (0, 0, 10) == (s3.inserted, s3.updated, s3.unchanged)
    assert scalar(db, "SELECT count(*) FROM vacancies") == 10
    assert scalar(db, "SELECT count(*) FROM vacancy_skills") == links_before > 0
    assert scalar(db, "SELECT count(*) FROM regions") == 1 and scalar(db, "SELECT count(*) FROM employers") == 10
    assert scalar(db, "SELECT count(*) FROM skills WHERE name_norm = 'python'") == 1


def test_unchanged_load_updates_only_last_seen(db):
    load(db, [hh_item(1)])
    first = scalar(db, "SELECT last_seen_at FROM vacancies WHERE source_id='1'")
    updated_before = scalar(db, "SELECT updated_at FROM vacancies WHERE source_id='1'")
    load(db, [hh_item(1)])
    assert scalar(db, "SELECT last_seen_at FROM vacancies WHERE source_id='1'") > first
    assert scalar(db, "SELECT updated_at FROM vacancies WHERE source_id='1'") == updated_before
    assert scalar(db, "SELECT first_seen_at <= last_seen_at FROM vacancies WHERE source_id='1'")


def test_changed_vacancy_is_updated_and_skills_replaced(db):
    load(db, [hh_item(1)])
    changed = hh_item(1, salary={"from": 300000, "to": 400000, "currency": "RUR", "gross": False},
                      key_skills=[{"name": "Go"}, {"name": "Kafka"}], description="<p>нет технологий</p>")
    stats, _ = load(db, [changed])
    assert (stats.inserted, stats.updated, stats.unchanged) == (0, 1, 0)
    assert scalar(db, "SELECT count(*) FROM vacancies") == 1
    assert float(scalar(db, "SELECT salary_mid FROM vacancies")) == 350000 and scalar(db, "SELECT salary_gross FROM vacancies") is not None and not scalar(db, "SELECT salary_gross FROM vacancies")
    names = {r[0] for r in query_df_rows(db, "SELECT s.name FROM vacancy_skills vs JOIN skills s ON s.id=vs.skill_id")}
    assert names == {"Go", "Apache Kafka"}                      # старые навыки удалены, алиас нормализован


def test_empty_load(db):
    with db.begin() as conn:
        assert load_records(conn, start_run(db, "import", "t"), []) == LoadStats()
    assert scalar(db, "SELECT count(*) FROM vacancies") == 0


def test_dictionary_reuse_and_missing_ids(db):
    a = hh_item(1, employer={"id": None, "name": "ООО Без Ид"}, area={"id": None, "name": "Казань"})
    b = hh_item(2, employer={"id": None, "name": "Без Ид"}, area={"id": "88", "name": "Казань"})
    load(db, [a, b])
    assert scalar(db, "SELECT count(*) FROM employers") == 1           # «ООО Без Ид» и «Без Ид» — один работодатель
    assert scalar(db, "SELECT count(*) FROM regions") == 1 and scalar(db, "SELECT source_id FROM regions") == "88"   # id дописан


def test_transaction_rolls_back_on_error(db):
    res = transform_batch([hh_item(1), hh_item(2)], "import")
    run = start_run(db, "import", "t")
    with pytest.raises(RuntimeError):
        with db.begin() as conn:
            load_records(conn, run, res.records)
            raise RuntimeError("сбой после загрузки")
    assert scalar(db, "SELECT count(*) FROM vacancies") == 0 and scalar(db, "SELECT count(*) FROM regions") == 0


def test_constraints(db):
    load(db, [hh_item(1)])
    base = "INSERT INTO vacancies (source_id, title, data_origin, content_hash{c}) VALUES ('{sid}', 't', 'api', 'h'{v})"
    bad = [
        base.format(c="", sid="1", v=""),                                                  # дубль (source, source_id)
        base.format(c=", salary_from, salary_to", sid="x1", v=", 10, 5"),                    # from > to
        base.format(c=", salary_kind, salary_mid", sid="x2", v=", 'none', 5"),               # mid без range
        base.format(c=", employer_id", sid="x3", v=", 999999"),                              # внешний ключ
        "INSERT INTO vacancies (source_id, title, data_origin, content_hash) VALUES ('x4','t','bogus','h')",
        "INSERT INTO vacancies (source_id, title, data_origin, content_hash, salary_kind) VALUES ('x5','t','api','h','zzz')",
        "INSERT INTO vacancy_skills (vacancy_id, skill_id) VALUES (1, 999999)",
    ]
    for sql in bad:
        with pytest.raises(Exception):
            with db.begin() as conn:
                conn.execute(text(sql))
    assert scalar(db, "SELECT count(*) FROM vacancies") == 1


def test_cascade_delete_of_vacancy_skills(db):
    load(db, [hh_item(1)])
    with db.begin() as conn:
        conn.execute(text("DELETE FROM vacancies"))
    assert scalar(db, "SELECT count(*) FROM vacancy_skills") == 0 and scalar(db, "SELECT count(*) FROM skills") > 0


def test_run_etl_statuses_and_log(db):
    ok = run_etl(db, [hh_item(1), hh_item(1), {"name": "без id"}], origin="import", description="t", params={})
    assert ok.status == "success" and (ok.fetched, ok.valid, ok.rejected, ok.duplicates_removed, ok.inserted) == (3, 1, 1, 1, 1)
    partial = run_etl(db, [hh_item(2)], origin="api", description="t", params={}, source_errors=["сбой деталей"])
    assert partial.status == "partial"
    failed = run_etl(db, [], origin="api", description="t", params={}, source_errors=["HTTP 403"])
    assert failed.status == "failed"
    rows = query_df_rows(db, "SELECT status, finished_at IS NOT NULL, error_message FROM etl_runs ORDER BY id")
    assert [r[0] for r in rows] == ["success", "partial", "failed"] and all(r[1] for r in rows) and rows[2][2] == "HTTP 403"
    assert scalar(db, "SELECT count(*) FROM data_quality_issues WHERE issue_type='missing_id'") == 1
    quality_sql = ("SELECT json_extract(params, '$.quality') IS NOT NULL FROM etl_runs WHERE id=1" if db.dialect.name == "sqlite"
                   else "SELECT params->'quality' IS NOT NULL FROM etl_runs WHERE id=1")
    assert scalar(db, quality_sql)


def test_run_etl_failure_recorded(db, monkeypatch):
    import src.pipeline as pipeline
    monkeypatch.setattr(pipeline, "load_records", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    with pytest.raises(ValueError):
        pipeline.run_etl(db, [hh_item(1)], origin="import", description="t", params={})
    assert scalar(db, "SELECT status FROM etl_runs") == "failed" and "boom" in scalar(db, "SELECT error_message FROM etl_runs")
    assert scalar(db, "SELECT count(*) FROM vacancies") == 0


# ---- аналитические запросы ----
@pytest.fixture()
def loaded(db):
    items = [hh_item(1), hh_item(2, area={"id": "2", "name": "Санкт-Петербург"}, name="Аналитик 100% _данных_"),
             hh_item(3, salary=None, key_skills=[{"name": "Excel"}], description="Excel"),
             hh_item(4, published_at="2026-09-01T10:00:00+0300")]
    load(db, items)
    return db


def test_filters(loaded):
    with loaded.connect() as c:
        assert len(q.load_vacancies(c, Filters())) == 4
        assert len(q.load_vacancies(c, Filters(regions=("Москва",)))) == 3
        assert len(q.load_vacancies(c, Filters(regions=("Москва", "Санкт-Петербург"), roles=("Программист, разработчик",)))) == 4
        from datetime import date
        assert len(q.load_vacancies(c, Filters(date_from=date(2026, 10, 1)))) == 3
        assert len(q.load_vacancies(c, Filters(date_to=date(2026, 9, 1)))) == 1          # граница «до» включительно
        assert q.load_vacancies(c, Filters(origins=("api",))).empty
        empty = q.load_vacancies(c, Filters(regions=("Нет такого",)))
        assert empty.empty and "salary_mid" in empty.columns                              # структура сохраняется
        sk = q.load_vacancy_skills(c, Filters(regions=("Санкт-Петербург",)))
        assert set(sk["skill"]) == {"Python", "SQL", "Docker"} and set(sk["vacancy_id"]) == {int(q.load_vacancies(c, Filters(regions=("Санкт-Петербург",)))["id"].iloc[0])}


def test_numeric_types_from_db(loaded):
    with loaded.connect() as c:
        df = q.load_vacancies(c, Filters())
    assert df["salary_mid"].dtype.kind == "f"            # NUMERIC -> float, а не object/Decimal
    assert df["published_at"].dt.tz is not None


def test_catalog_search_escape_and_skills_all(loaded):
    with loaded.connect() as c:
        f = Filters()
        assert q.catalog_count(c, f, q.CatalogQuery(search="100%")) == 1              # % не работает как подстановка
        assert q.catalog_count(c, f, q.CatalogQuery(search="_данных_")) == 1
        assert q.catalog_count(c, f, q.CatalogQuery(search="%")) == 1
        assert q.catalog_count(c, f, q.CatalogQuery(search="АНАЛИТИК")) == 1          # регистронезависимо, в т.ч. кириллица
        assert q.catalog_count(c, f, q.CatalogQuery(search="python-РАЗРАБОТЧИК")) == 3    # по названию «Python-разработчик …»
        assert q.catalog_count(c, f, q.CatalogQuery(skills=("Python", "SQL"))) == 3
        assert q.catalog_count(c, f, q.CatalogQuery(skills=("Python", "Excel"))) == 0   # нужны ВСЕ навыки
        assert q.catalog_count(c, f, q.CatalogQuery(salary_min_rub=190000)) == 3
        assert q.catalog_count(c, f, q.CatalogQuery(salary_min_rub=250000)) == 0
        assert q.catalog_count(c, f, q.CatalogQuery(search="'; DROP TABLE vacancies; --")) == 0
        page = q.catalog_page(c, f, q.CatalogQuery(sort="Название (А–Я)"), 2, 0)
        assert len(page) == 2 and page["title"].is_monotonic_increasing
        assert q.catalog_page(c, f, q.CatalogQuery(), 10, 100).empty
    assert scalar(loaded, "SELECT count(*) FROM vacancies") == 4                      # таблица на месте


def test_quality_queries(loaded):
    run_etl(loaded, [hh_item(9), {"id": "z"}], origin="import", description="t", params={})
    with loaded.connect() as c:
        hist = q.etl_history(c)
        assert hist.iloc[0]["status"] == "success" and not q.run_issue_summary(c, int(hist.iloc[0]["id"])).empty
        miss = q.table_missing_stats(c).set_index("Поле")
        assert miss.loc["Зарплата не указана", "Пропусков"] == 1 and miss.loc["Регион", "Пропусков"] == 0
        assert q.data_sources(c).iloc[0]["vacancies"] == 5
        opts = q.filter_options(c)
        assert opts["total"] == 5 and "Москва" in opts["regions"] and opts["date_min"] <= opts["date_max"]
