"""Нормализация зарплаты.

Правила (см. также docs/METRICS.md):

1. Валюта приводится к ISO-коду в верхнем регистре; известные алиасы (RUR -> RUB, BYR -> BYN).
   Валюты НЕ конвертируются между собой: курсы не являются частью данных, а выдуманные
   курсы исказили бы результат. Сравнения зарплат делаются внутри одной валюты.
2. Границы должны быть положительными числами; from <= to. Иначе kind = 'invalid'.
3. kind:
   - 'range'     — обе границы заданы: salary_mid = (from + to) / 2;
   - 'from_only' — задана только нижняя граница, salary_mid = NULL;
   - 'to_only'   — задана только верхняя граница, salary_mid = NULL;
   - 'none'      — зарплата не указана;
   - 'invalid'   — значения некорректны (отрицательные, нулевые, from > to, нет валюты).
4. gross/net хранится как есть (None = источник не сообщил). Аналитика не смешивает
   gross и net: фильтр по признаку есть в аналитическом слое.
5. Периодичность: источник hh.ru по умолчанию отдаёт месячную зарплату. Если в данных есть
   поле периодичности и оно не «месяц», зарплата помечается 'invalid' — пересчёт без
   достоверной информации о периоде не выполняется.
6. Явно нереалистичные значения (выше верхнего порога для месячной зарплаты) помечаются
   'invalid' и попадают в журнал качества, а не молча исправляются.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CURRENCY_ALIASES = {
    "RUR": "RUB", "RUB": "RUB", "BYR": "BYN", "BYN": "BYN", "USD": "USD", "EUR": "EUR",
    "KZT": "KZT", "UAH": "UAH", "AZN": "AZN", "UZS": "UZS", "GEL": "GEL", "KGS": "KGS",
}

# Верхний порог правдоподобия месячной зарплаты в «единицах валюты». Грубая защита от опечаток
# вида лишних нулей; значения выше порога не удаляются, а получают kind = 'invalid'.
MAX_PLAUSIBLE_MONTHLY = {
    "RUB": 5_000_000, "BYN": 200_000, "KZT": 20_000_000, "UAH": 1_000_000,
    "USD": 100_000, "EUR": 100_000, "AZN": 200_000, "UZS": 500_000_000, "GEL": 200_000, "KGS": 5_000_000,
}
DEFAULT_MAX = 10_000_000

MONTHLY_FREQUENCIES = {None, "", "MONTHLY", "MONTH", "month", "monthly"}


@dataclass(frozen=True)
class SalaryResult:
    salary_from: float | None
    salary_to: float | None
    currency: str | None
    gross: bool | None
    kind: str
    mid: float | None
    issue: str | None = None  # описание проблемы для data_quality_issues


def normalize_currency(code: Any) -> str | None:
    if code is None:
        return None
    key = str(code).strip().upper()
    if not key:
        return None
    return CURRENCY_ALIASES.get(key, key if len(key) == 3 and key.isalpha() else None)


def _to_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, bool):
            return None
        number = float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError(f"не число: {value!r}")
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"недопустимое число: {value!r}")
    return number


def normalize_salary(salary: dict | None) -> SalaryResult:
    """Принимает объект salary из ответа hh.ru (или None) и возвращает нормализованный результат."""
    if not salary:
        return SalaryResult(None, None, None, None, "none", None)

    gross = salary.get("gross")
    gross = gross if isinstance(gross, bool) else None
    currency = normalize_currency(salary.get("currency"))

    try:
        low = _to_number(salary.get("from"))
        high = _to_number(salary.get("to"))
    except ValueError as exc:
        return SalaryResult(None, None, currency, gross, "invalid", None, f"некорректные границы: {exc}")

    if low is None and high is None:
        return SalaryResult(None, None, currency, gross, "none", None)

    frequency = salary.get("frequency")
    if isinstance(frequency, dict):
        frequency = frequency.get("id")
    if frequency not in MONTHLY_FREQUENCIES:
        return SalaryResult(low, high, currency, gross, "invalid", None,
                            f"периодичность {frequency!r} не месячная — пересчёт не выполняется")

    if currency is None:
        return SalaryResult(low, high, None, gross, "invalid", None, "не указана или неизвестна валюта")

    if (low is not None and low <= 0) or (high is not None and high <= 0):
        return SalaryResult(low, high, currency, gross, "invalid", None, "неположительная граница")

    if low is not None and high is not None and low > high:
        return SalaryResult(low, high, currency, gross, "invalid", None, "нижняя граница больше верхней")

    limit = MAX_PLAUSIBLE_MONTHLY.get(currency, DEFAULT_MAX)
    if (low is not None and low > limit) or (high is not None and high > limit):
        return SalaryResult(low, high, currency, gross, "invalid", None,
                            f"значение выше правдоподобного порога {limit} {currency}")

    if low is not None and high is not None:
        return SalaryResult(low, high, currency, gross, "range", (low + high) / 2)
    if low is not None:
        return SalaryResult(low, None, currency, gross, "from_only", None)
    return SalaryResult(None, high, currency, gross, "to_only", None)
