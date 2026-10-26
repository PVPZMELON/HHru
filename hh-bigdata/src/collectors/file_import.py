"""Импорт вакансий из файла: JSONL, JSON или CSV.

Это допустимый альтернативный источник, когда официальный API недоступен или требует токен:
файл может быть выгрузкой, сделанной вами через официальный API, открытым датасетом или
сохранённым сырым файлом из data/raw (повторная обработка без нового обращения к hh.ru).

Форматы:
* .jsonl / .ndjson — по объекту на строку, формат как у ответа hh.ru (id, name, area, employer,
  salary{from,to,currency,gross}, key_skills, ...);
* .json — массив объектов или объект с ключом "items";
* .csv — столбцы (достаточно части из них): id, name|title, employer, employer_id, area|region,
  role, published_at, experience, employment, schedule, salary_from, salary_to, currency, gross,
  skills (через «;» или «,»), description, url.
"""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

from src.collectors.raw_store import iter_jsonl

log = logging.getLogger(__name__)

MAX_FILE_BYTES = 500 * 1024 * 1024
MAX_RECORDS_DEFAULT = 1_000_000


class SourceFileError(Exception):
    """Файл невозможно прочитать (формат, размер, кодировка)."""


def _csv_value(row: dict, *names: str) -> str | None:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


def _csv_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    low = value.lower()
    if low in {"1", "true", "yes", "да", "gross"}:
        return True
    if low in {"0", "false", "no", "нет", "net"}:
        return False
    return None


def _csv_row_to_hh(row: dict) -> dict:
    """Приводит строку CSV к структуре ответа hh.ru, чтобы дальше работал единый transform."""
    item: dict[str, Any] = {
        "id": _csv_value(row, "id", "vacancy_id"),
        "name": _csv_value(row, "name", "title"),
        "published_at": _csv_value(row, "published_at", "date"),
        "description": _csv_value(row, "description"),
        "alternate_url": _csv_value(row, "url", "alternate_url"),
    }
    employer = _csv_value(row, "employer", "employer_name", "company")
    if employer:
        item["employer"] = {"id": _csv_value(row, "employer_id"), "name": employer}
    area = _csv_value(row, "area", "region", "city")
    if area:
        item["area"] = {"id": _csv_value(row, "area_id"), "name": area}
    role = _csv_value(row, "role", "professional_role")
    if role:
        item["professional_roles"] = [{"id": _csv_value(row, "role_id"), "name": role}]
    for src, dst in (("experience", "experience"), ("employment", "employment"), ("schedule", "schedule")):
        value = _csv_value(row, src)
        if value:
            item[dst] = {"name": value}
    low, high = _csv_value(row, "salary_from"), _csv_value(row, "salary_to")
    if low or high:
        item["salary"] = {"from": low, "to": high, "currency": _csv_value(row, "currency", "salary_currency"),
                          "gross": _csv_bool(_csv_value(row, "gross", "salary_gross"))}
    skills = _csv_value(row, "skills", "key_skills")
    if skills:
        sep = ";" if ";" in skills else ","
        item["key_skills"] = [{"name": s.strip()} for s in skills.split(sep) if s.strip()]
    return item


def read_records(path: str | Path, max_records: int = MAX_RECORDS_DEFAULT) -> tuple[list[dict], list[str]]:
    """Читает файл; возвращает (записи, ошибки чтения). Битые строки не останавливают импорт."""
    path = Path(path)
    if not path.is_file():
        raise SourceFileError(f"файл не найден: {path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise SourceFileError(f"файл больше {MAX_FILE_BYTES // 1024 // 1024} МБ: разбейте его на части")

    suffix = path.suffix.lower()
    items: list[dict] = []
    errors: list[str] = []

    try:
        if suffix in {".jsonl", ".ndjson"}:
            for _, obj, err in iter_jsonl(path):
                if err:
                    errors.append(err)
                elif obj is not None:
                    items.append(obj)
        elif suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                data = data["items"]
            if not isinstance(data, list):
                raise SourceFileError("JSON должен быть массивом объектов или содержать ключ items")
            for i, obj in enumerate(data):
                if isinstance(obj, dict):
                    items.append(obj)
                else:
                    errors.append(f"элемент {i}: ожидался объект")
        elif suffix == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                sample = fh.read(4096)
                fh.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
                except csv.Error:
                    dialect = csv.excel
                reader = csv.DictReader(fh, dialect=dialect)
                if not reader.fieldnames:
                    raise SourceFileError("CSV без заголовка")
                for row in reader:
                    items.append(_csv_row_to_hh(row))
        else:
            raise SourceFileError(f"неподдерживаемый формат {suffix!r}: используйте .jsonl, .json или .csv")
    except UnicodeDecodeError as exc:
        raise SourceFileError(f"файл не в кодировке UTF-8: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise SourceFileError(f"некорректный JSON: {exc.msg}") from exc

    if len(items) > max_records:
        errors.append(f"файл содержит {len(items)} записей; импортированы первые {max_records}")
        items = items[:max_records]
    log.info("Прочитано из %s: %d записей, %d ошибок чтения", path.name, len(items), len(errors))
    return items, errors
