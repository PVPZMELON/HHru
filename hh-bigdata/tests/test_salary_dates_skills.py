import math
from datetime import datetime, timezone

import pytest

from src.etl.dates import parse_datetime
from src.etl.salary import normalize_currency, normalize_salary
from src.etl.skills import extract_from_text, extract_structured


# ---- зарплаты ----
@pytest.mark.parametrize("salary, kind, mid", [
    ({"from": 100000, "to": 200000, "currency": "RUR", "gross": True}, "range", 150000),
    ({"from": 100000, "to": None, "currency": "RUR", "gross": False}, "from_only", None),
    ({"from": None, "to": 80000, "currency": "USD", "gross": True}, "to_only", None),
    (None, "none", None),
    ({}, "none", None),
    ({"from": None, "to": None, "currency": "RUR"}, "none", None),
])
def test_salary_kinds(salary, kind, mid):
    r = normalize_salary(salary)
    assert r.kind == kind and r.mid == mid


@pytest.mark.parametrize("salary", [
    {"from": 300000, "to": 100000, "currency": "RUR"},      # from > to
    {"from": -5, "to": 50000, "currency": "RUR"},           # отрицательное
    {"from": 0, "to": 50000, "currency": "RUR"},            # ноль
    {"from": "abc", "to": None, "currency": "RUR"},         # не число
    {"from": 100000, "to": 120000, "currency": None},       # нет валюты
    {"from": 90_000_000, "to": 95_000_000, "currency": "RUR"},  # правдоподобный порог
    {"from": float("nan"), "to": 1000, "currency": "RUR"},
    {"from": 100000, "to": 120000, "currency": "RUR", "frequency": {"id": "YEARLY"}},
])
def test_salary_invalid(salary):
    r = normalize_salary(salary)
    assert r.kind == "invalid" and r.mid is None and r.issue


def test_salary_currency_alias_and_gross_preserved():
    r = normalize_salary({"from": 10, "to": 30, "currency": "rur", "gross": False})
    assert r.currency == "RUB" and r.gross is False and r.mid == 20
    assert normalize_salary({"from": 10, "to": 30, "currency": "RUR"}).gross is None  # источник не сообщил
    assert normalize_currency("BYR") == "BYN" and normalize_currency("??") is None and normalize_currency(None) is None


def test_salary_numeric_strings_and_monthly_frequency():
    assert normalize_salary({"from": "100 000", "to": "200000", "currency": "RUR", "frequency": {"id": "MONTHLY"}}).mid == 150000


# ---- даты ----
@pytest.mark.parametrize("raw, expected", [
    ("2026-10-01T12:30:00+0300", datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)),
    ("2026-10-01T12:30:00+03:00", datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)),
    ("2026-10-01T12:30:00Z", datetime(2026, 10, 1, 12, 30, tzinfo=timezone.utc)),
    ("2026-10-01", datetime(2026, 10, 1, tzinfo=timezone.utc)),
    (datetime(2026, 10, 1, 5, 0), datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc)),
])
def test_parse_datetime(raw, expected):
    assert parse_datetime(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "вчера", "2026-13-45"])
def test_parse_datetime_bad(raw):
    assert parse_datetime(raw) is None


# ---- навыки ----
def test_structured_skills_normalized_and_deduped():
    got = extract_structured([{"name": "python"}, {"name": "Питон"}, {"name": "postgres"}, {"name": " SQL "}, {"name": ""}, "Docker"])
    assert got == ["Python", "PostgreSQL", "SQL", "Docker"]
    assert extract_structured(None) == [] and extract_structured([]) == []


def test_text_skills_word_boundaries():
    found = extract_from_text("Требуется Python, опыт с PostgreSQL и Docker. Знание C++ и .NET приветствуется")
    assert {"Python", "PostgreSQL", "Docker", "C++", ".NET"} <= set(found)
    assert "Java" not in extract_from_text("JavaScript разработчик")   # не путает Java и JavaScript
    assert "Go" not in extract_from_text("go ahead and let's go")      # неоднозначное слово не ищется
    assert extract_from_text(None) == [] and extract_from_text("") == []
