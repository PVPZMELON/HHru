"""Хранение «сырых» данных в JSONL: по одному JSON-объекту вакансии в строке.

Сырой файл позволяет повторить очистку и загрузку без обращения к источнику
(`python -m src.pipeline import --file data/raw/<файл> --origin api`).
Запись атомарна: сначала временный файл, затем переименование.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

log = logging.getLogger(__name__)


def save_jsonl(items: Iterable[dict], raw_dir: Path, prefix: str = "hh") -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = raw_dir / f"{prefix}_{stamp}.jsonl"
    tmp = path.with_suffix(".jsonl.tmp")
    count = 0
    with tmp.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
            count += 1
    os.replace(tmp, path)
    log.info("Сырые данные сохранены: %s (%d записей)", path, count)
    return path


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict | None, str | None]]:
    """(номер строки, объект, ошибка). Некорректные строки не прерывают чтение."""
    with Path(path).open("r", encoding="utf-8-sig") as fh:
        for number, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                yield number, None, f"строка {number}: некорректный JSON ({exc.msg})"
                continue
            if not isinstance(obj, dict):
                yield number, None, f"строка {number}: ожидался JSON-объект"
                continue
            yield number, obj, None
