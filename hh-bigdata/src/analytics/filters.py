"""Глобальные фильтры аналитики. Преобразуются в параметризованное условие WHERE."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from src.db.sqlutil import in_clause


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
            parts.append(f"{p}region_name IN {in_clause('f_regions', self.regions, params)}")
        if self.roles:
            parts.append(f"{p}role_name IN {in_clause('f_roles', self.roles, params)}")
        if self.origins:
            parts.append(f"{p}data_origin IN {in_clause('f_origins', self.origins, params)}")
        return (" AND ".join(parts) if parts else "TRUE"), params

    @property
    def is_empty(self) -> bool:
        return not (self.date_from or self.date_to or self.regions or self.roles or self.origins)
