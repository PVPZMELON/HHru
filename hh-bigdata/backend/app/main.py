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
