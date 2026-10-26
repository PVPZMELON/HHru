"""Приведение дат к единому формату: timezone-aware UTC."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


def parse_datetime(value: Any) -> datetime | None:
    """Разбирает ISO-8601 (в т.ч. «2026-10-01T12:30:00+0300» из hh.ru), date, datetime.

    Возвращает datetime в UTC или None, если значение пустое/нераспознано.
    Наивные значения считаются UTC.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        text = str(value).strip()
        if not text:
            return None
        # hh.ru отдаёт смещение без двоеточия (+0300) — приводим к виду +03:00
        if len(text) >= 5 and text[-5] in "+-" and text[-4:].isdigit() and ":" not in text[-5:]:
            text = f"{text[:-2]}:{text[-2:]}"
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
