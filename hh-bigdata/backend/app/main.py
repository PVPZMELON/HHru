"""FastAPI backend; аналитика использует существующие SQL- и metrics-модули проекта."""
from __future__ import annotations

import os
from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="HHru Vacancy Analytics API",
    description="Серверное API агрегатора и аналитики рынка вакансий hh.ru",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

_origins = [item.strip() for item in os.getenv("FRONTEND_ORIGINS", "").split(",") if item.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    )


@app.get("/api/v1/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness check: процесс API запущен."""
    return {"status": "ok", "service": "hhru-api", "version": app.version}


@app.get("/api/v1/ready", tags=["system"])
def ready() -> dict[str, str]:
    """Проверяет доступность настроенной БД без раскрытия секретов."""
    try:
        from src.db.session import check_connection

        ok, _message = check_connection()
    except Exception:  # noqa: BLE001
        ok = False
    if not ok:
        raise HTTPException(
            status_code=503,
            detail={"code": "DEPENDENCY_UNAVAILABLE", "message": "База данных временно недоступна"},
        )
    return {"status": "ready", "database": "available"}


def _filters(
    date_from: date | None,
    date_to: date | None,
    region: list[str],
    role: list[str],
    origin: list[str],
):
    from src.analytics.filters import Filters

    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from не может быть позже date_to")
    return Filters(
        date_from=date_from,
        date_to=date_to,
        regions=tuple(region),
        roles=tuple(role),
        origins=tuple(origin),
    )


def _analytics_data(flt):
    from src.analytics import queries
    from src.db.session import get_engine

    try:
        with get_engine().connect() as conn:
            options = queries.filter_options(conn)
            vacancies = queries.load_vacancies(conn, flt)
            skills = queries.load_vacancy_skills(conn, flt)
    except Exception as exc:  # noqa: BLE001 — не раскрываем клиенту SQL и инфраструктурные детали
        raise HTTPException(
            status_code=503,
            detail={"code": "DEPENDENCY_UNAVAILABLE", "message": "Не удалось получить данные из БД"},
        ) from exc
    return options, vacancies, skills


def _filter_params(
    date_from: date | None,
    date_to: date | None,
    region: list[str],
    role: list[str],
    origin: list[str],
) -> dict:
    return {
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "region": region,
        "role": role,
        "origin": origin,
    }


@app.get("/api/v1/filters/options", tags=["analytics"])
def filter_options():
    """Справочники и границы дат для фильтров frontend."""
    from src.db.session import get_engine
    from src.analytics.queries import filter_options as load_options

    try:
        with get_engine().connect() as conn:
            data = load_options(conn)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "DEPENDENCY_UNAVAILABLE", "message": "Не удалось получить справочники"},
        ) from exc
    return {
        "regions": data["regions"],
        "roles": data["roles"],
        "origins": data["origins"],
        "date_min": data["date_min"].isoformat() if data["date_min"] else None,
        "date_max": data["date_max"].isoformat() if data["date_max"] else None,
        "total": data["total"],
    }


@app.get("/api/v1/overview", tags=["analytics"])
def overview(
    date_from: date | None = None,
    date_to: date | None = None,
    region: list[str] = Query(default=[]),
    role: list[str] = Query(default=[]),
    origin: list[str] = Query(default=[]),
):
    """KPI рынка труда с теми же правилами фильтрации и зарплат, что и Streamlit."""
    from src.analytics import metrics

    flt = _filters(date_from, date_to, region, role, origin)
    _options, vacancies, skills = _analytics_data(flt)
    basis = metrics.default_basis(vacancies)
    values = metrics.overview(vacancies, skills, basis)
    return {
        "filters": _filter_params(date_from, date_to, region, role, origin),
        "sample": {
            "vacancies": values["vacancies"],
            "employers": values["employers"],
        },
        "salary": {
            "currency": basis.currency if basis else None,
            "gross": basis.gross if basis else None,
            "comparable_count": values["comparable"],
            "median": values["median"],
            "mean": values["mean"],
        },
        "salary_disclosure": {
            "count": values["with_salary"],
            "share": values["with_salary_share"],
        },
        "invalid_salary": values["invalid_salary"],
        "top_skill": {
            "name": values["top_skill"],
            "vacancies": values["top_skill_count"],
        },
    }


_SORT_ALIASES = {
    "published_desc": "Дата публикации (новые)",
    "published_asc": "Дата публикации (старые)",
    "salary_desc": "Зарплата (по убыванию)",
    "salary_asc": "Зарплата (по возрастанию)",
    "title_asc": "Название (А–Я)",
}


def _json_value(value):
    """Преобразует значения pandas/numpy/datetime в типы, сериализуемые JSON."""
    import math
    import pandas as pd

    if value is None or pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _catalog_item(row: dict) -> dict:
    return {
        "id": int(row["id"]),
        "title": row["title"],
        "employer_name": _json_value(row.get("employer_name")),
        "region_name": _json_value(row.get("region_name")),
        "role_name": _json_value(row.get("role_name")),
        "experience": _json_value(row.get("experience")),
        "employment": _json_value(row.get("employment")),
        "schedule": _json_value(row.get("schedule")),
        "salary": {
            "from": _json_value(row.get("salary_from")),
            "to": _json_value(row.get("salary_to")),
            "currency": _json_value(row.get("salary_currency")),
            "gross": _json_value(row.get("salary_gross")),
            "kind": _json_value(row.get("salary_kind")),
        },
        "published_at": _json_value(row.get("published_at")),
        "url": _json_value(row.get("url")),
        "data_origin": row["data_origin"],
        "skills": [name for name in str(row.get("skills") or "").split(", ") if name],
    }


@app.get("/api/v1/vacancies", tags=["vacancies"])
def vacancies(
    date_from: date | None = None,
    date_to: date | None = None,
    region: list[str] = Query(default=[]),
    role: list[str] = Query(default=[]),
    origin: list[str] = Query(default=[]),
    q: str = Query(default="", max_length=200),
    skills: list[str] = Query(default=[]),
    experience: list[str] = Query(default=[]),
    employment: list[str] = Query(default=[]),
    salary_min_rub: float | None = Query(default=None, ge=0, le=100000000),
    sort: str = "published_desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    """Поиск и постраничный каталог вакансий на стороне БД."""
    from src.analytics import queries

    flt = _filters(date_from, date_to, region, role, origin)
    sort_label = _SORT_ALIASES.get(sort, sort)
    if sort_label not in queries.SORT_OPTIONS:
        raise HTTPException(status_code=400, detail="Неизвестный параметр sort")
    catalog_query = queries.CatalogQuery(
        search=q,
        skills=tuple(skills),
        experience=tuple(experience),
        employment=tuple(employment),
        salary_min_rub=salary_min_rub,
        sort=sort_label,
    )
    offset = (page - 1) * page_size
    try:
        from src.db.session import get_engine

        with get_engine().connect() as conn:
            total = queries.catalog_count(conn, flt, catalog_query)
            rows = queries.catalog_page(conn, flt, catalog_query, page_size, offset)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "DEPENDENCY_UNAVAILABLE", "message": "Не удалось получить каталог вакансий"},
        ) from exc
    items = [_catalog_item(row) for row in rows.to_dict(orient="records")]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/api/v1/vacancies/facets", tags=["vacancies"])
def vacancy_facets():
    """Справочники для фильтров каталога: опыт, занятость и навыки."""
    from src.analytics.queries import catalog_facets
    from src.db.session import get_engine

    try:
        with get_engine().connect() as conn:
            return catalog_facets(conn)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "DEPENDENCY_UNAVAILABLE", "message": "Не удалось получить фильтры каталога"},
        ) from exc
