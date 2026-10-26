"""SQL-запросы аналитического слоя. Возвращают DataFrame; расчёт показателей — в metrics.py.

Все значения передаются параметрами. Динамически собирается только структура условий из
фиксированных фрагментов; поля сортировки берутся из белого списка.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.analytics.filters import Filters
from src.db.session import is_sqlite, query_df
from src.db.sqlutil import in_clause

VACANCY_COLUMNS = (
    "id, source_id, title, published_at, employment, schedule, experience, "
    "salary_from, salary_to, salary_currency, salary_gross, salary_kind, salary_mid, "
    "url, data_origin, employer_id, employer_name, region_name, role_name"
)


def filter_options(conn) -> dict:
    """Значения для фильтров интерфейса: регионы, роли, границы дат, типы данных."""
    regions = query_df(conn, "SELECT DISTINCT region_name AS v FROM v_vacancy_flat WHERE region_name IS NOT NULL ORDER BY 1")
    roles = query_df(conn, "SELECT DISTINCT role_name AS v FROM v_vacancy_flat WHERE role_name IS NOT NULL ORDER BY 1")
    origins = query_df(conn, "SELECT DISTINCT data_origin AS v FROM v_vacancy_flat ORDER BY 1")
    dates = query_df(conn, "SELECT min(published_at) AS d_min, max(published_at) AS d_max, count(*) AS n FROM v_vacancy_flat")
    d_min, d_max = dates["d_min"].iloc[0], dates["d_max"].iloc[0]
    return {
        "regions": regions["v"].tolist(),
        "roles": roles["v"].tolist(),
        "origins": origins["v"].tolist(),
        "date_min": None if pd.isna(d_min) else d_min.date(),
        "date_max": None if pd.isna(d_max) else d_max.date(),
        "total": int(dates["n"].iloc[0]),
    }


def load_vacancies(conn, flt: Filters) -> pd.DataFrame:
    """Вакансии выборки (без текста описания) для расчёта метрик."""
    where, params = flt.where()
    return query_df(conn, f"SELECT {VACANCY_COLUMNS} FROM v_vacancy_flat WHERE {where}", params)


def load_vacancy_skills(conn, flt: Filters) -> pd.DataFrame:
    """Связи вакансия–навык для той же выборки: vacancy_id, skill, origin."""
    where, params = flt.where("v.")
    return query_df(
        conn,
        "SELECT vs.vacancy_id, s.name AS skill, vs.origin FROM vacancy_skills vs "
        "JOIN skills s ON s.id = vs.skill_id "
        f"JOIN v_vacancy_flat v ON v.id = vs.vacancy_id WHERE {where}",
        params,
    )


# ---------- каталог ----------

SORT_OPTIONS = {
    "Дата публикации (новые)": "v.published_at DESC NULLS LAST, v.id DESC",
    "Дата публикации (старые)": "v.published_at ASC NULLS LAST, v.id ASC",
    "Зарплата (по убыванию)": "v.salary_mid DESC NULLS LAST, v.id DESC",
    "Зарплата (по возрастанию)": "v.salary_mid ASC NULLS LAST, v.id ASC",
    "Название (А–Я)": "v.title ASC, v.id ASC",
}


@dataclass(frozen=True)
class CatalogQuery:
    search: str = ""
    skills: tuple[str, ...] = ()          # вакансия должна содержать ВСЕ перечисленные навыки
    experience: tuple[str, ...] = ()
    employment: tuple[str, ...] = ()
    salary_min_rub: float | None = None   # верхняя известная граница зарплаты (RUB) не меньше значения
    sort: str = "Дата публикации (новые)"


def _escape_like(text_: str) -> str:
    return text_.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _catalog_where(flt: Filters, q: CatalogQuery) -> tuple[str, dict]:
    where, params = flt.where("v.")
    parts = [where]
    if q.search.strip():
        parts.append("(lower(v.title) LIKE lower(:q_pat) ESCAPE '\\' OR lower(v.description) LIKE lower(:q_pat) ESCAPE '\\')")
        params["q_pat"] = f"%{_escape_like(q.search.strip())}%"
    if q.experience:
        parts.append(f"v.experience IN {in_clause('q_exp', q.experience, params)}")
    if q.employment:
        parts.append(f"v.employment IN {in_clause('q_emp', q.employment, params)}")
    if q.salary_min_rub:
        parts.append("v.salary_currency = 'RUB' AND v.salary_kind <> 'invalid' "
                     "AND CASE WHEN COALESCE(v.salary_from, 0) >= COALESCE(v.salary_to, 0) "
                     "THEN COALESCE(v.salary_from, 0) ELSE COALESCE(v.salary_to, 0) END >= :q_sal")
        params["q_sal"] = q.salary_min_rub
    if q.skills:
        marks = in_clause("q_skill", sorted(set(q.skills)), params)
        parts.append(
            "(SELECT count(DISTINCT s.name) FROM vacancy_skills vs JOIN skills s ON s.id = vs.skill_id "
            f"WHERE vs.vacancy_id = v.id AND s.name IN {marks}) = :q_nskills"
        )
        params["q_nskills"] = len(set(q.skills))
    return " AND ".join(parts), params


CATALOG_COLUMNS = (
    "v.id, v.title, v.employer_name, v.region_name, v.role_name, v.experience, v.employment, v.schedule, "
    "v.salary_from, v.salary_to, v.salary_currency, v.salary_gross, v.salary_kind, v.published_at, "
    "v.url, v.data_origin"
)


def catalog_count(conn, flt: Filters, q: CatalogQuery) -> int:
    where, params = _catalog_where(flt, q)
    return int(query_df(conn, f"SELECT count(*) AS n FROM v_vacancy_flat v WHERE {where}", params)["n"].iloc[0])


def _skills_agg(conn) -> str:
    """Подзапрос «навыки вакансии через запятую, по алфавиту» (синтаксис зависит от СУБД)."""
    if is_sqlite(conn):  # group_concat без ORDER BY: порядок задаёт упорядоченный подзапрос
        return ("COALESCE((SELECT group_concat(n, ', ') FROM (SELECT s.name AS n FROM vacancy_skills vs "
                "JOIN skills s ON s.id = vs.skill_id WHERE vs.vacancy_id = v.id ORDER BY s.name)), '')")
    return ("COALESCE((SELECT string_agg(s.name, ', ' ORDER BY s.name) FROM vacancy_skills vs "
            "JOIN skills s ON s.id = vs.skill_id WHERE vs.vacancy_id = v.id), '')")


def catalog_page(conn, flt: Filters, q: CatalogQuery, limit: int, offset: int) -> pd.DataFrame:
    """Страница каталога (пагинация на стороне БД). Описание вакансии не выгружается."""
    where, params = _catalog_where(flt, q)
    order = SORT_OPTIONS.get(q.sort, SORT_OPTIONS["Дата публикации (новые)"])
    params.update({"lim": int(limit), "off": int(offset)})
    return query_df(
        conn,
        f"SELECT {CATALOG_COLUMNS}, "
        f"{_skills_agg(conn)} AS skills "
        f"FROM v_vacancy_flat v WHERE {where} ORDER BY {order} LIMIT :lim OFFSET :off",
        params,
    )


def catalog_facets(conn) -> dict:
    """Значения для фильтров каталога."""
    exp = query_df(conn, "SELECT DISTINCT experience AS v FROM vacancies WHERE experience IS NOT NULL ORDER BY 1")
    emp = query_df(conn, "SELECT DISTINCT employment AS v FROM vacancies WHERE employment IS NOT NULL ORDER BY 1")
    skills = query_df(conn, "SELECT name AS v FROM skills ORDER BY 1")
    return {"experience": exp["v"].tolist(), "employment": emp["v"].tolist(), "skills": skills["v"].tolist()}


# ---------- качество данных и конвейер ----------

def etl_history(conn, limit: int = 50) -> pd.DataFrame:
    return query_df(
        conn,
        "SELECT id, started_at, finished_at, status, data_origin, source_description, fetched_count, valid_count, "
        "rejected_count, duplicates_removed, inserted_count, updated_count, unchanged_count, error_message "
        "FROM etl_runs ORDER BY started_at DESC, id DESC LIMIT :n",
        {"n": limit},
    )


def run_issue_summary(conn, run_id: int) -> pd.DataFrame:
    return query_df(
        conn,
        "SELECT issue_type, count(*) AS n FROM data_quality_issues WHERE etl_run_id = :r "
        "GROUP BY issue_type ORDER BY n DESC",
        {"r": run_id},
    )


def table_missing_stats(conn) -> pd.DataFrame:
    """Доля пропусков по ключевым полям во ВСЕЙ таблице вакансий (не зависит от глобальных фильтров)."""
    df = query_df(
        conn,
        "SELECT count(*) AS total, "
        "count(*) FILTER (WHERE employer_id IS NULL) AS employer, "
        "count(*) FILTER (WHERE region_id IS NULL) AS region, "
        "count(*) FILTER (WHERE role_id IS NULL) AS role, "
        "count(*) FILTER (WHERE published_at IS NULL) AS published_missing, "
        "count(*) FILTER (WHERE experience IS NULL) AS experience, "
        "count(*) FILTER (WHERE employment IS NULL) AS employment, "
        "count(*) FILTER (WHERE schedule IS NULL) AS schedule, "
        "count(*) FILTER (WHERE description IS NULL) AS description, "
        "count(*) FILTER (WHERE url IS NULL) AS url, "
        "count(*) FILTER (WHERE salary_kind = 'none') AS salary_not_given, "
        "count(*) FILTER (WHERE salary_kind = 'invalid') AS salary_invalid, "
        "count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM vacancy_skills vs WHERE vs.vacancy_id = vacancies.id)) AS skills "
        "FROM vacancies",
    )
    total = int(df["total"].iloc[0])
    labels = {
        "employer": "Работодатель", "region": "Регион", "role": "Профессиональная роль",
        "published_missing": "Дата публикации", "experience": "Опыт", "employment": "Тип занятости",
        "schedule": "График", "description": "Описание", "url": "Ссылка на источник",
        "salary_not_given": "Зарплата не указана", "salary_invalid": "Зарплата некорректна",
        "skills": "Навыки (нет ни одного)",
    }
    rows = [{"Поле": label, "Пропусков": int(df[col].iloc[0]),
             "Доля": (int(df[col].iloc[0]) / total) if total else 0.0} for col, label in labels.items()]
    return pd.DataFrame(rows)


def data_sources(conn) -> pd.DataFrame:
    """Состав данных по типам источника: сколько вакансий и когда последний раз обновлялись."""
    return query_df(
        conn,
        "SELECT data_origin, count(*) AS vacancies, min(first_seen_at) AS first_loaded, max(last_seen_at) AS last_seen "
        "FROM vacancies GROUP BY data_origin ORDER BY data_origin",
    )
