"""Загрузка нормализованных вакансий в БД — SQLite или PostgreSQL (идемпотентная, UPSERT).

Алгоритм для пакета записей (всё в одной транзакции):
1. Справочники (регионы, работодатели, роли, навыки) — «найти или создать», с кэшем на запуск.
2. Одним запросом читаются уже существующие вакансии пакета: source_id -> (id, content_hash).
3. Классификация:
   - нет в БД              -> INSERT           (inserted)
   - есть, hash отличается -> UPDATE (UPSERT)  (updated), навыки заменяются
   - есть, hash совпал     -> только last_seen_at (unchanged)
4. INSERT ... ON CONFLICT (source, source_id) защищает от гонок: даже если два процесса
   загрузят одну вакансию одновременно, дубликата не будет (ограничение uq_vacancies_source).

Повторный запуск на тех же данных поэтому не меняет число строк и содержимое — только last_seen_at.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import text

from src.db.sqlutil import chunks, in_clause
from src.etl.transform import Issue

log = logging.getLogger(__name__)

_DICT_TABLES = {"regions", "professional_roles"}  # справочники с уникальным name_norm

_UPSERT_TEMPLATE = """
INSERT INTO vacancies (
    source, source_id, title, employer_id, region_id, role_id,
    published_at, source_updated_at, employment, schedule, experience,
    salary_from, salary_to, salary_currency, salary_gross, salary_kind, salary_mid,
    url, description, data_origin, content_hash, etl_run_id,
    first_seen_at, last_seen_at, updated_at
) VALUES (
    :source, :source_id, :title, :employer_id, :region_id, :role_id,
    :published_at, :source_updated_at, :employment, :schedule, :experience,
    :salary_from, :salary_to, :salary_currency, :salary_gross, :salary_kind, :salary_mid,
    :url, :description, :data_origin, :content_hash, :etl_run_id,
    {now}, {now}, {now}
)
ON CONFLICT (source, source_id) DO UPDATE SET
    title = EXCLUDED.title,
    employer_id = EXCLUDED.employer_id,
    region_id = EXCLUDED.region_id,
    role_id = EXCLUDED.role_id,
    published_at = EXCLUDED.published_at,
    source_updated_at = EXCLUDED.source_updated_at,
    employment = EXCLUDED.employment,
    schedule = EXCLUDED.schedule,
    experience = EXCLUDED.experience,
    salary_from = EXCLUDED.salary_from,
    salary_to = EXCLUDED.salary_to,
    salary_currency = EXCLUDED.salary_currency,
    salary_gross = EXCLUDED.salary_gross,
    salary_kind = EXCLUDED.salary_kind,
    salary_mid = EXCLUDED.salary_mid,
    url = EXCLUDED.url,
    description = EXCLUDED.description,
    data_origin = EXCLUDED.data_origin,
    content_hash = EXCLUDED.content_hash,
    etl_run_id = EXCLUDED.etl_run_id,
    last_seen_at = {now},
    updated_at = {now}
WHERE vacancies.content_hash {differs} EXCLUDED.content_hash
RETURNING id
"""

# «отличается с учётом NULL»: в PostgreSQL IS DISTINCT FROM, в SQLite — IS NOT
PG_NOW = "CURRENT_TIMESTAMP"
# в SQLite CURRENT_TIMESTAMP точен до секунды — берём миллисекунды, чтобы различать быстрые повторные запуски
SQLITE_NOW = "strftime('%Y-%m-%d %H:%M:%f', 'now')"
UPSERT_VACANCY = text(_UPSERT_TEMPLATE.format(differs="IS DISTINCT FROM", now=PG_NOW))
UPSERT_VACANCY_SQLITE = text(_UPSERT_TEMPLATE.format(differs="IS NOT", now=SQLITE_NOW))


@dataclass
class LoadStats:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skill_links: int = 0


class _Dictionaries:
    """Справочники «найти или создать» с кэшем, чтобы не повторять запросы внутри пакета."""

    def __init__(self, conn):
        self.conn = conn
        self._cache: dict[tuple, int] = {}

    def _scalar(self, sql: str, params: dict):
        return self.conn.execute(text(sql), params).scalar()

    def named(self, table: str, source_id: str | None, name: str | None, norm: str | None) -> int | None:
        """regions / professional_roles: name_norm уникален, source_id — если есть."""
        if not name or not norm:
            return None
        assert table in _DICT_TABLES
        key = (table, source_id, norm)
        if key in self._cache:
            return self._cache[key]
        found = None
        if source_id:
            found = self._scalar(f"SELECT id FROM {table} WHERE source_id = :sid", {"sid": source_id})
        if found is None:
            row = self.conn.execute(
                text(f"SELECT id, source_id FROM {table} WHERE name_norm = :n"), {"n": norm}
            ).fetchone()
            if row is not None:
                found = row[0]
                if source_id and row[1] is None:
                    self.conn.execute(text(f"UPDATE {table} SET source_id = :sid WHERE id = :id"),
                                      {"sid": source_id, "id": found})
        if found is None:
            found = self._scalar(
                f"INSERT INTO {table} (source_id, name, name_norm) VALUES (:sid, :name, :n) "
                f"ON CONFLICT (name_norm) DO UPDATE SET name = {table}.name RETURNING id",
                {"sid": source_id, "name": name, "n": norm},
            )
        self._cache[key] = found
        return found

    def employer(self, source_id: str | None, name: str | None, norm: str | None) -> int | None:
        if not name or not norm:
            return None
        key = ("employers", source_id, norm)
        if key in self._cache:
            return self._cache[key]
        if source_id:
            found = self._scalar(
                "INSERT INTO employers (source_id, name, name_norm) VALUES (:sid, :name, :n) "
                "ON CONFLICT (source_id) DO UPDATE SET name = EXCLUDED.name, name_norm = EXCLUDED.name_norm "
                "RETURNING id",
                {"sid": source_id, "name": name, "n": norm},
            )
        else:  # работодатель без id источника различается по нормализованному названию
            found = self._scalar(
                "INSERT INTO employers (source_id, name, name_norm) VALUES (NULL, :name, :n) "
                "ON CONFLICT (name_norm) WHERE source_id IS NULL DO UPDATE SET name = employers.name "
                "RETURNING id",
                {"name": name, "n": norm},
            )
        self._cache[key] = found
        return found

    def skill(self, name: str) -> int:
        norm = name.lower()
        key = ("skills", norm)
        if key not in self._cache:
            self._cache[key] = self._scalar(
                "INSERT INTO skills (name, name_norm) VALUES (:name, :n) "
                "ON CONFLICT (name_norm) DO UPDATE SET name = skills.name RETURNING id",
                {"name": name, "n": norm},
            )
        return self._cache[key]


def _vacancy_params(rec: dict, dicts: _Dictionaries, run_id: int) -> dict:
    return {
        "source": rec["source"], "source_id": rec["source_id"], "title": rec["title"],
        "employer_id": dicts.employer(rec.get("employer_source_id"), rec.get("employer_name"), rec.get("employer_norm")),
        "region_id": dicts.named("regions", rec.get("region_source_id"), rec.get("region_name"), rec.get("region_norm")),
        "role_id": dicts.named("professional_roles", rec.get("role_source_id"), rec.get("role_name"), rec.get("role_norm")),
        "published_at": rec.get("published_at"), "source_updated_at": rec.get("source_updated_at"),
        "employment": rec.get("employment"), "schedule": rec.get("schedule"), "experience": rec.get("experience"),
        "salary_from": rec.get("salary_from"), "salary_to": rec.get("salary_to"),
        "salary_currency": rec.get("salary_currency"), "salary_gross": rec.get("salary_gross"),
        "salary_kind": rec["salary_kind"], "salary_mid": rec.get("salary_mid"),
        "url": rec.get("url"), "description": rec.get("description"),
        "data_origin": rec["data_origin"], "content_hash": rec["content_hash"], "etl_run_id": run_id,
    }


def _replace_skills(conn, dicts: _Dictionaries, vacancy_id: int, skills: list[dict]) -> int:
    conn.execute(text("DELETE FROM vacancy_skills WHERE vacancy_id = :v"), {"v": vacancy_id})
    rows, seen = [], set()
    for s in skills:
        sid = dicts.skill(s["name"])
        if sid in seen:
            continue
        seen.add(sid)
        rows.append({"v": vacancy_id, "s": sid, "o": s["origin"]})
    if rows:
        conn.execute(text("INSERT INTO vacancy_skills (vacancy_id, skill_id, origin) VALUES (:v, :s, :o)"), rows)
    return len(rows)


def load_records(conn, run_id: int, records: list[dict]) -> LoadStats:
    """Загружает записи в рамках переданного соединения (транзакцией управляет вызывающий)."""
    stats = LoadStats()
    if not records:
        return stats
    source = records[0]["source"]
    ids = [r["source_id"] for r in records]
    existing: dict[str, tuple[int, str]] = {}
    for part in chunks(ids):
        params: dict = {"s": source}
        marks = in_clause("id", part, params)
        for row in conn.execute(
            text(f"SELECT source_id, id, content_hash FROM vacancies WHERE source = :s AND source_id IN {marks}"),
            params,
        ).fetchall():
            existing[row[0]] = (row[1], row[2])
    sqlite = conn.dialect.name == "sqlite"
    upsert = UPSERT_VACANCY_SQLITE if sqlite else UPSERT_VACANCY
    now = SQLITE_NOW if sqlite else PG_NOW
    dicts = _Dictionaries(conn)
    unchanged_ids: list[str] = []

    for rec in records:
        prev = existing.get(rec["source_id"])
        if prev is not None and prev[1] == rec["content_hash"]:
            unchanged_ids.append(rec["source_id"])
            stats.unchanged += 1
            continue
        vacancy_id = conn.execute(upsert, _vacancy_params(rec, dicts, run_id)).scalar()
        if vacancy_id is None:  # параллельный процесс уже записал ту же версию
            stats.unchanged += 1
            continue
        stats.skill_links += _replace_skills(conn, dicts, vacancy_id, rec.get("skills", []))
        if prev is None:
            stats.inserted += 1
        else:
            stats.updated += 1

    if unchanged_ids:
        for part in chunks(unchanged_ids):
            params = {"s": source}
            marks = in_clause("id", part, params)
            conn.execute(
                text(f"UPDATE vacancies SET last_seen_at = {now} WHERE source = :s AND source_id IN {marks}"),
                params,
            )
    return stats


# ---------- журнал запусков и качество ----------

def start_run(engine, data_origin: str, source_description: str, params: dict | None = None) -> int:
    """Создаёт запись etl_runs (status='running') в отдельной транзакции — видна даже при сбое загрузки."""
    cast = "" if engine.dialect.name == "sqlite" else "CAST(:p AS jsonb)"
    with engine.begin() as conn:
        return conn.execute(
            text("INSERT INTO etl_runs (data_origin, source_description, params) "
                 f"VALUES (:o, :d, {cast or ':p'}) RETURNING id"),
            {"o": data_origin, "d": source_description, "p": json.dumps(params or {}, ensure_ascii=False, default=str)},
        ).scalar()


def finish_run(engine, run_id: int, status: str, *, fetched: int = 0, valid: int = 0, duplicates: int = 0,
               rejected: int = 0, stats: LoadStats | None = None, raw_path: str | None = None,
               error: str | None = None, extra_params: dict | None = None) -> None:
    stats = stats or LoadStats()
    sqlite = engine.dialect.name == "sqlite"
    values = {"st": status, "f": fetched, "v": valid, "d": duplicates, "r": rejected, "i": stats.inserted,
              "u": stats.updated, "n": stats.unchanged, "raw": raw_path, "err": (error or None) and error[:2000],
              "id": run_id}
    base = (f"UPDATE etl_runs SET finished_at = {SQLITE_NOW if sqlite else PG_NOW}, status = :st, fetched_count = :f, valid_count = :v, "
            "duplicates_removed = :d, rejected_count = :r, inserted_count = :i, updated_count = :u, "
            "unchanged_count = :n, raw_path = :raw, error_message = :err, ")
    extra = extra_params or {}
    with engine.begin() as conn:
        if sqlite:
            # JSON в SQLite — текст: объединяем объекты в Python
            raw = conn.execute(text("SELECT params FROM etl_runs WHERE id = :id"), {"id": run_id}).scalar()
            try:
                current = json.loads(raw) if raw else {}
            except (TypeError, ValueError):
                current = {}
            merged = {**(current if isinstance(current, dict) else {}), **extra}
            conn.execute(text(base + "params = :params WHERE id = :id"),
                         {**values, "params": json.dumps(merged, ensure_ascii=False, default=str)})
        else:
            conn.execute(text(base + "params = COALESCE(params, CAST('{}' AS jsonb)) || CAST(:extra AS jsonb) "
                                     "WHERE id = :id"),
                         {**values, "extra": json.dumps(extra, ensure_ascii=False, default=str)})


def save_issues(conn, run_id: int, issues: Iterable[Issue]) -> int:
    rows = [{"r": run_id, "s": i.source_id, "t": i.issue_type, "f": i.field, "d": i.details} for i in issues]
    if rows:
        conn.execute(
            text("INSERT INTO data_quality_issues (etl_run_id, source_id, issue_type, field, details) "
                 "VALUES (:r, :s, :t, :f, :d)"),
            rows,
        )
    return len(rows)
