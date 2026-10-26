"""Глобальные фильтры аналитики. Преобразуются в параметризованное условие WHERE."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone


@dataclass(frozen=True)
class Filters:
    """Неизменяемый (а значит, хэшируемый для кэша Streamlit) набор глобальных фильтров.

    Пустой кортеж = «без ограничения». Вакансии с NULL в фильтруемом поле (например, без даты
    публикации) при активном фильтре по этому полю в выборку не попадают.
    """
    date_from: date | None = None
    date_to: date | None = None          # включительно
    regions: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    origins: tuple[str, ...] = ()        # api | import | synthetic

    def where(self, prefix: str = "") -> tuple[str, dict]:
        """Возвращает (SQL-условие без слова WHERE, параметры). Имена полей — из v_vacancy_flat."""
        p = prefix
        parts: list[str] = []
        params: dict = {}
        if self.date_from:
            parts.append(f"{p}published_at >= :f_date_from")
            params["f_date_from"] = datetime.combine(self.date_from, time.min, tzinfo=timezone.utc)
        if self.date_to:
            parts.append(f"{p}published_at < :f_date_to")
            params["f_date_to"] = datetime.combine(self.date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        if self.regions:
            parts.append(f"{p}region_name = ANY(:f_regions)")
            params["f_regions"] = list(self.regions)
        if self.roles:
            parts.append(f"{p}role_name = ANY(:f_roles)")
            params["f_roles"] = list(self.roles)
        if self.origins:
            parts.append(f"{p}data_origin = ANY(:f_origins)")
            params["f_origins"] = list(self.origins)
        return (" AND ".join(parts) if parts else "TRUE"), params

    @property
    def is_empty(self) -> bool:
        return not (self.date_from or self.date_to or self.regions or self.roles or self.origins)
