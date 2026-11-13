"""Конфигурация проекта: читается из переменных окружения / файла .env.

Секреты (пароль БД, токен hh.ru) хранятся только в окружении и не попадают в логи.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _split(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [p.strip() for p in value.split(";") if p.strip()]


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "да"}


class DbSettings(BaseModel):
    """Параметры БД. backend: sqlite (файл, без сервера) или postgres."""
    backend: str = "sqlite"
    path: Path = PROJECT_ROOT / "data" / "hh_market.sqlite"   # только для sqlite
    host: str = "localhost"
    port: int = 5432
    name: str = "hh_market"
    user: str = "hh_user"
    password: str = Field(default="", repr=False)
    sslmode: str = ""  # для облачных PostgreSQL (Neon, Supabase): "require"

    @field_validator("backend")
    @classmethod
    def _backend(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"sqlite", "postgres"}:
            raise ValueError("DB_BACKEND должен быть sqlite или postgres")
        return v

    @property
    def url(self) -> str:
        """SQLAlchemy URL: sqlite:///путь или postgresql+psycopg://..."""
        if self.backend == "sqlite":
            return f"sqlite:///{self.path.as_posix()}"
        url = (
            f"postgresql+psycopg://{quote_plus(self.user)}:{quote_plus(self.password)}"
            f"@{self.host}:{self.port}/{self.name}"
        )
        return f"{url}?sslmode={quote_plus(self.sslmode)}" if self.sslmode else url

    @property
    def safe_url(self) -> str:
        """URL без пароля — для логов."""
        if self.backend == "sqlite":
            return self.url
        return f"postgresql+psycopg://{self.user}:***@{self.host}:{self.port}/{self.name}"


def _db_settings(env) -> DbSettings:
    """Выбор БД: DB_BACKEND, а если не задан — postgres при заданном DB_HOST, иначе sqlite."""
    backend = (env("DB_BACKEND") or ("postgres" if env("DB_HOST") else "sqlite")).strip().lower()
    path = Path(env("DB_PATH") or "data/hh_market.sqlite")
    return DbSettings(
        backend=backend,
        path=path if path.is_absolute() else PROJECT_ROOT / path,
        host=env("DB_HOST", "localhost"),
        port=int(env("DB_PORT", "5432")),
        name=env("DB_NAME", "hh_market"),
        user=env("DB_USER", "hh_user"),
        password=env("DB_PASSWORD", ""),
        sslmode=env("DB_SSLMODE", ""),
    )


class CollectorSettings(BaseModel):
    api_base: str = "https://api.hh.ru"
    token: str = Field(default="", repr=False)
    user_agent: str = "BigDataStudyProject/1.0 (contact@example.invalid)"
    queries: list[str] = ["Python разработчик"]
    areas: list[str] = ["1"]
    per_page: int = 50
    max_pages: int = 5
    max_vacancies: int = 500
    fetch_details: bool = True
    delay_sec: float = 0.5
    timeout_sec: float = 20.0
    max_retries: int = 4
    max_requests: int = 1500
    period_days: int | None = None  # только вакансии за последние N дней (hh.ru: 1..30)

    @field_validator("per_page")
    @classmethod
    def _per_page(cls, v: int) -> int:
        if not 1 <= v <= 100:
            raise ValueError("per_page должен быть от 1 до 100")
        return v

    @field_validator("max_retries")
    @classmethod
    def _retries(cls, v: int) -> int:
        if not 0 <= v <= 10:
            raise ValueError("max_retries должен быть от 0 до 10")
        return v


class Settings(BaseModel):
    db: DbSettings
    collector: CollectorSettings
    raw_dir: Path
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env = os.environ.get
    return Settings(
        db=_db_settings(env),
        collector=CollectorSettings(
            api_base=env("HH_API_BASE", "https://api.hh.ru"),
            token=env("HH_API_TOKEN", ""),
            user_agent=env("HH_USER_AGENT", "BigDataStudyProject/1.0 (contact@example.invalid)"),
            queries=_split(env("COLLECT_QUERIES"), ["Python разработчик"]),
            areas=_split(env("COLLECT_AREAS"), ["1"]),
            per_page=int(env("COLLECT_PER_PAGE", "50")),
            max_pages=int(env("COLLECT_MAX_PAGES", "5")),
            max_vacancies=int(env("COLLECT_MAX_VACANCIES", "500")),
            fetch_details=_bool(env("COLLECT_FETCH_DETAILS"), True),
            delay_sec=float(env("COLLECT_DELAY_SEC", "0.5")),
            timeout_sec=float(env("COLLECT_TIMEOUT_SEC", "20")),
            max_retries=int(env("COLLECT_MAX_RETRIES", "4")),
            max_requests=int(env("COLLECT_MAX_REQUESTS", "1500")),
            period_days=int(env("COLLECT_PERIOD_DAYS")) if env("COLLECT_PERIOD_DAYS") else None,
        ),
        raw_dir=PROJECT_ROOT / env("RAW_DIR", "data/raw"),
        log_level=env("LOG_LEVEL", "INFO"),
    )
