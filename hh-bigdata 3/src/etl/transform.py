"""Очистка и нормализация сырых вакансий.

Вход — словари в формате ответа hh.ru (список вакансий или полное описание).
Модуль терпим к отсутствующим полям: схема не предполагает, что они есть у каждой вакансии.
Ничего не «додумывается»: пропуски остаются None.

Преобразования и их назначение:
- validate_required     : вакансия без id/названия не может быть загружена -> отклоняется, фиксируется проблема
- clean_text            : единый формат строк (пробелы, HTML-сущности)
- html_to_text          : описание вакансии -> простой текст
- norm_key              : ключ сопоставления сущностей (регистр, кавычки, правовая форма)
- normalize_salary      : см. src/etl/salary.py
- parse_datetime        : даты -> UTC
- skills                : структурированные + аккуратно извлечённые из текста
- content_hash          : обнаружение изменений между запусками (идемпотентная загрузка)
- deduplicate           : точные дубли по source_id; конфликтующие версии; «возможные» дубли только помечаются
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.etl.dates import parse_datetime
from src.etl.salary import normalize_salary
from src.etl.skills import extract_from_text, extract_structured

MAX_DESCRIPTION_CHARS = 8000
_LEGAL_FORMS = {"ооо", "оао", "зао", "пао", "ао", "ип", "нко", "llc", "ltd", "inc", "gmbh"}


@dataclass
class Issue:
    source_id: str | None
    issue_type: str
    field: str | None = None
    details: str | None = None


@dataclass
class TransformResult:
    records: list[dict] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    fetched: int = 0
    rejected: int = 0
    duplicates_removed: int = 0


# ---------- базовые функции ----------

def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def html_to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>", "\n", str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n") if line.strip())
    if not text:
        return None
    return text[:MAX_DESCRIPTION_CHARS]


def norm_key(value: Any, strip_legal_form: bool = False) -> str:
    text = clean_text(value) or ""
    text = text.replace("«", "").replace("»", "").replace('"', "").replace("'", "")
    text = text.casefold().replace("ё", "е")
    if strip_legal_form:
        parts = [p for p in re.split(r"[\s,]+", text) if p]
        while parts and parts[0].strip(".") in _LEGAL_FORMS:
            parts.pop(0)
        text = " ".join(parts)
    return re.sub(r"\s+", " ", text).strip()


def _named(obj: Any) -> tuple[str | None, str | None]:
    """{'id': '1', 'name': 'Москва'} -> ('1', 'Москва'). Допускает строку или None."""
    if isinstance(obj, dict):
        oid = obj.get("id")
        return (str(oid) if oid not in (None, "") else None, clean_text(obj.get("name")))
    if isinstance(obj, str):
        return None, clean_text(obj)
    return None, None


def _first_named(items: Any) -> tuple[str | None, str | None]:
    if isinstance(items, list) and items:
        return _named(items[0])
    return None, None


def _schedule(raw: dict) -> str | None:
    _, name = _named(raw.get("schedule"))
    if name:
        return name
    days = raw.get("work_schedule_by_days")
    if isinstance(days, list):
        names = [n for _, n in (_named(d) for d in days) if n]
        if names:
            return ", ".join(names)
    return None


def _employment(raw: dict) -> str | None:
    _, name = _named(raw.get("employment"))
    if name:
        return name
    _, name = _named(raw.get("employment_form"))
    return name


def compute_hash(rec: dict) -> str:
    payload = {
        k: rec.get(k)
        for k in (
            "title", "employer_name", "employer_source_id", "region_name", "role_name",
            "published_at", "source_updated_at", "employment", "schedule", "experience",
            "salary_from", "salary_to", "salary_currency", "salary_gross", "url", "description",
        )
    }
    payload["skills"] = sorted(s["name"] for s in rec.get("skills", []))
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------- нормализация одной записи ----------

def normalize_record(raw: dict, data_origin: str, source: str = "hh.ru") -> tuple[dict | None, list[Issue]]:
    issues: list[Issue] = []
    if not isinstance(raw, dict):
        return None, [Issue(None, "invalid_record", None, "запись не является объектом")]

    sid = raw.get("id")
    sid = str(sid).strip() if sid not in (None, "") else None
    if not sid:
        return None, [Issue(None, "missing_id", "id", "нет идентификатора вакансии")]

    title = clean_text(raw.get("name") or raw.get("title"))
    if not title:
        return None, [Issue(sid, "missing_title", "name", "нет названия вакансии")]

    area_id, area_name = _named(raw.get("area"))
    emp_id, emp_name = _named(raw.get("employer"))
    role_id, role_name = _first_named(raw.get("professional_roles"))
    if not area_name:
        issues.append(Issue(sid, "missing_region", "area"))
    if not emp_name:
        issues.append(Issue(sid, "missing_employer", "employer"))
    if not role_name:
        issues.append(Issue(sid, "missing_role", "professional_roles"))

    published = parse_datetime(raw.get("published_at") or raw.get("created_at"))
    if raw.get("published_at") and published is None:
        issues.append(Issue(sid, "bad_date", "published_at", str(raw.get("published_at"))[:60]))
    updated = parse_datetime(raw.get("updated_at") or raw.get("source_updated_at"))

    sal = normalize_salary(raw.get("salary"))
    salary_from, salary_to = sal.salary_from, sal.salary_to
    if sal.kind == "invalid":
        # Некорректные границы в вакансию не сохраняются (их отвергнет CHECK в БД и они исказили бы
        # аналитику), но исходное значение остаётся в журнале качества — информация не теряется.
        original = json.dumps(raw.get("salary"), ensure_ascii=False, default=str)[:300]
        issues.append(Issue(sid, "invalid_salary", "salary", f"{sal.issue}; исходное значение: {original}"))
        salary_from = salary_to = None

    description = html_to_text(raw.get("description"))
    structured = extract_structured(raw.get("key_skills"))
    skills = [{"name": n, "origin": "structured"} for n in structured]
    seen = {n.lower() for n in structured}
    # В текст смотрим только описание: сниппеты списка слишком короткие и неполные
    for name in extract_from_text(description):
        if name.lower() not in seen:
            skills.append({"name": name, "origin": "text"})
            seen.add(name.lower())

    rec = {
        "source": source,
        "source_id": sid,
        "title": title,
        "employer_source_id": emp_id,
        "employer_name": emp_name,
        "employer_norm": norm_key(emp_name, strip_legal_form=True) if emp_name else None,
        "region_source_id": area_id,
        "region_name": area_name,
        "region_norm": norm_key(area_name) if area_name else None,
        "role_source_id": role_id,
        "role_name": role_name,
        "role_norm": norm_key(role_name) if role_name else None,
        "published_at": published,
        "source_updated_at": updated,
        "employment": _employment(raw),
        "schedule": _schedule(raw),
        "experience": _named(raw.get("experience"))[1],
        "salary_from": salary_from,
        "salary_to": salary_to,
        "salary_currency": sal.currency,
        "salary_gross": sal.gross,
        "salary_kind": sal.kind,
        "salary_mid": sal.mid,
        "url": clean_text(raw.get("alternate_url") or raw.get("url")),
        "description": description,
        "skills": skills,
        "data_origin": data_origin,
    }
    rec["content_hash"] = compute_hash(rec)
    return rec, issues


# ---------- пакетная обработка ----------

def deduplicate(records: list[dict]) -> tuple[list[dict], list[Issue], int]:
    """Удаляет повторы по (source, source_id).

    - Точный дубль (тот же content_hash) — просто отбрасывается.
    - Конфликтующий дубль (другое содержимое) — остаётся версия с более поздним
      source_updated_at (при равенстве — более поздняя во входном файле); факт фиксируется в issues.
    - «Возможные» дубли (тот же работодатель + название + регион + дата публикации, но разные id)
      НЕ удаляются — только помечаются: независимые публикации возможны.
    """
    issues: list[Issue] = []
    if not records:
        return [], issues, 0

    df = pd.DataFrame(
        {"pos": range(len(records)), "source": [r["source"] for r in records],
         "sid": [r["source_id"] for r in records], "hash": [r["content_hash"] for r in records],
         "upd": [r["source_updated_at"].timestamp() if r["source_updated_at"] else float("-inf") for r in records]}
    )
    removed = 0
    keep: list[int] = []
    for (_, sid), group in df.groupby(["source", "sid"], sort=False):
        if len(group) == 1:
            keep.append(int(group["pos"].iloc[0]))
            continue
        removed += len(group) - 1
        if group["hash"].nunique() > 1:
            issues.append(Issue(str(sid), "conflicting_duplicate", None,
                                f"{len(group)} версии с разным содержимым; оставлена самая свежая"))
        best = group.sort_values(["upd", "pos"]).iloc[-1]
        keep.append(int(best["pos"]))
    keep.sort()
    unique = [records[i] for i in keep]

    # возможные дубли — только пометка
    soft = pd.DataFrame(
        {"sid": [r["source_id"] for r in unique],
         "k": [(r["employer_norm"], norm_key(r["title"]), r["region_norm"],
                r["published_at"].date().isoformat() if r["published_at"] else None) for r in unique]}
    )
    soft = soft[soft["k"].map(lambda k: all(x is not None for x in k))]
    for _, grp in soft.groupby("k", sort=False):
        if len(grp) > 1:
            for sid in grp["sid"]:
                issues.append(Issue(str(sid), "possible_duplicate", None,
                                    "совпадают работодатель, название, регион и дата публикации"))
    return unique, issues, removed


def transform_batch(raw_items: list[dict], data_origin: str, source: str = "hh.ru") -> TransformResult:
    result = TransformResult(fetched=len(raw_items))
    good: list[dict] = []
    for raw in raw_items:
        rec, issues = normalize_record(raw, data_origin, source)
        result.issues.extend(issues)
        if rec is None:
            result.rejected += 1
        else:
            good.append(rec)
    unique, dup_issues, removed = deduplicate(good)
    result.records = unique
    result.issues.extend(dup_issues)
    result.duplicates_removed = removed
    return result


def quality_summary(records: list[dict]) -> dict[str, float]:
    """Доли пропусков по ключевым полям (для отчёта о качестве)."""
    if not records:
        return {}
    df = pd.DataFrame(records)
    cols = ["employer_name", "region_name", "role_name", "published_at", "experience",
            "employment", "schedule", "description", "url"]
    out = {c: round(float(df[c].isna().mean()), 4) for c in cols if c in df}
    out["salary_none"] = round(float((df["salary_kind"] == "none").mean()), 4)
    out["salary_invalid"] = round(float((df["salary_kind"] == "invalid").mean()), 4)
    out["no_skills"] = round(float(df["skills"].map(len).eq(0).mean()), 4)
    return out
