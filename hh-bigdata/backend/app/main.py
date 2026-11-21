"""Минимальный FastAPI backend; бизнес-логика остаётся в существующем src/."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="HHru Vacancy Analytics API",
    description="Серверное API агрегатора и аналитики рынка вакансий hh.ru",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# Origins задаются серверным окружением. По умолчанию CORS закрыт.
# Для локального frontend можно задать FRONTEND_ORIGINS=http://localhost:5173
import os

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
    """Liveness check: процесс API запущен. Не проверяет внешние зависимости."""
    return {"status": "ok", "service": "hhru-api", "version": app.version}


@app.get("/api/v1/ready", tags=["system"])
def ready() -> dict[str, str]:
    """Readiness check: проверяет доступность настроенной БД без раскрытия секретов."""
    try:
        # Импортируем src только при запросе, чтобы документация API открывалась
        # даже в окружении, где БД ещё не настроена.
        from src.db.session import check_connection

        ok, _message = check_connection()
    except Exception:  # noqa: BLE001 — клиенту не раскрываем детали конфигурации
        ok = False
    if not ok:
        raise HTTPException(status_code=503, detail={"code": "DEPENDENCY_UNAVAILABLE",
                                                     "message": "База данных временно недоступна"})
    return {"status": "ready", "database": "available"}
