"""CLI конвейера: `python -m src.pipeline <команда>`.

Команды:
  migrate                     создать/обновить схему БД (migrations/*.sql)
  collect [--raw-only]        собрать вакансии через API hh.ru -> data/raw/*.jsonl -> очистка -> БД
  import --file F [--origin]  импорт JSONL/JSON/CSV (origin: import | api | synthetic)
  demo [--n N --seed S]       сгенерировать СИНТЕТИЧЕСКИЙ набор и загрузить (data_origin=synthetic)
  status                      состояние БД и последний запуск

Каждый запуск пишется в таблицу etl_runs; итоговый статус отражает реальный результат.
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.collectors import demo_data
from src.collectors.file_import import SourceFileError, read_records
from src.collectors.hh_client import HhClient
from src.collectors.raw_store import save_jsonl
from src.config import get_settings
from src.db.loader import finish_run, load_records, save_issues, start_run
from src.db.migrate import migrate
from src.db.session import get_engine, query_df
from src.etl.transform import quality_summary, transform_batch
from src.utils.logging_setup import setup_logging

log = logging.getLogger("pipeline")


@dataclass
class RunSummary:
    run_id: int
    status: str
    fetched: int
    valid: int
    rejected: int
    duplicates_removed: int
    inserted: int
    updated: int
    unchanged: int
    errors: list[str]

    def __str__(self) -> str:
        lines = [
            f"Запуск #{self.run_id}: {self.status}",
            f"  получено: {self.fetched}, валидных: {self.valid}, отклонено: {self.rejected}, "
            f"дублей удалено: {self.duplicates_removed}",
            f"  в БД: новых {self.inserted}, обновлено {self.updated}, без изменений {self.unchanged}",
        ]
        lines += [f"  ! {e}" for e in self.errors[:5]]
        if len(self.errors) > 5:
            lines.append(f"  ... и ещё {len(self.errors) - 5} сообщений об ошибках (см. журнал и etl_runs)")
        return "\n".join(lines)


def run_etl(engine, raw_items: list[dict], *, origin: str, description: str, params: dict,
            raw_path: str | None = None, source_errors: list[str] | None = None) -> RunSummary:
    """Очистка + загрузка одного пакета с записью в etl_runs."""
    source_errors = source_errors or []
    run_id = start_run(engine, origin, description, params)
    try:
        result = transform_batch(raw_items, origin)
        quality = quality_summary(result.records)
        with engine.begin() as conn:  # загрузка и журнал качества — атомарно
            stats = load_records(conn, run_id, result.records)
            save_issues(conn, run_id, result.issues)
        if source_errors and not raw_items:
            status = "failed"
        elif source_errors:
            status = "partial"
        else:
            status = "success"
        finish_run(engine, run_id, status, fetched=result.fetched, valid=len(result.records),
                   duplicates=result.duplicates_removed, rejected=result.rejected, stats=stats,
                   raw_path=raw_path, error="; ".join(source_errors) or None,
                   extra_params={"quality": quality})
        return RunSummary(run_id, status, result.fetched, len(result.records), result.rejected,
                          result.duplicates_removed, stats.inserted, stats.updated, stats.unchanged, source_errors)
    except Exception as exc:
        log.exception("Ошибка загрузки")
        finish_run(engine, run_id, "failed", error=f"{type(exc).__name__}: {exc}")
        raise


# ---------- команды ----------

def cmd_migrate(args) -> int:
    applied = migrate(get_engine())
    print(f"Применено миграций: {len(applied)}" + (f" ({', '.join(applied)})" if applied else ""))
    return 0


def cmd_collect(args) -> int:
    settings = get_settings()
    cfg = settings.collector.model_copy(update={"max_vacancies": args.max} if args.max else {})
    client = HhClient(cfg)
    result = client.collect()
    raw_path = save_jsonl(result.items, settings.raw_dir, "hh") if result.items else None
    print(f"Собрано вакансий: {len(result.items)}, запросов к API: {result.requests_made}, "
          f"деталей получено: {result.details_fetched}")
    for err in result.errors[:5]:
        print(f"  ! {err}")
    if args.raw_only:
        return 0 if result.items else 1
    description = f"hh.ru API; запросы: {'; '.join(cfg.queries)}; регионы: {', '.join(cfg.areas)}"
    params = {"queries": cfg.queries, "areas": cfg.areas, "max_vacancies": cfg.max_vacancies,
              "per_page": cfg.per_page, "max_pages": cfg.max_pages, "fetch_details": cfg.fetch_details,
              "requests_made": result.requests_made, "stopped_reason": result.stopped_reason,
              "found_by_query": result.found_by_query}
    summary = run_etl(get_engine(), result.items, origin="api", description=description, params=params,
                      raw_path=str(raw_path) if raw_path else None, source_errors=result.errors)
    print(summary)
    return 1 if summary.status == "failed" else 0


def cmd_import(args) -> int:
    path = Path(args.file)
    try:
        items, read_errors = read_records(path)
    except SourceFileError as exc:
        print(f"Ошибка импорта: {exc}")
        return 2
    description = f"импорт файла {path.name}"
    summary = run_etl(get_engine(), items, origin=args.origin, description=description,
                      params={"file": path.name, "read_errors": len(read_errors)},
                      raw_path=str(path), source_errors=read_errors[:50])
    print(summary)
    return 1 if summary.status == "failed" else 0


def cmd_demo(args) -> int:
    settings = get_settings()
    # «Сейчас» округляется до начала суток UTC: повторный запуск в тот же день даёт тот же набор,
    # поэтому повторная загрузка не меняет данные (идемпотентность).
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    items = demo_data.generate(n=args.n, seed=args.seed, now=today)
    path = save_jsonl(items, settings.raw_dir, "demo")
    print(f"Сгенерирован СИНТЕТИЧЕСКИЙ набор: {len(items)} записей -> {path}")
    summary = run_etl(get_engine(), items, origin="synthetic",
                      description=f"синтетический демо-набор (seed={args.seed}, n={args.n})",
                      params={"seed": args.seed, "n": args.n}, raw_path=str(path))
    print(summary)
    return 1 if summary.status == "failed" else 0


def cmd_status(args) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        total = query_df(conn, "SELECT count(*) AS n FROM vacancies")["n"].iloc[0]
        by_origin = query_df(conn, "SELECT data_origin, count(*) AS n FROM vacancies GROUP BY 1 ORDER BY 1")
        last = query_df(conn, "SELECT id, status, data_origin, started_at, finished_at FROM etl_runs "
                              "ORDER BY started_at DESC, id DESC LIMIT 1")
    print(f"Вакансий в БД: {total}")
    for _, row in by_origin.iterrows():
        print(f"  {row['data_origin']}: {row['n']}")
    if last.empty:
        print("Запусков ETL ещё не было")
    else:
        r = last.iloc[0]
        print(f"Последний запуск #{r['id']}: {r['status']} ({r['data_origin']}), начат {r['started_at']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.pipeline", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="создать/обновить схему БД").set_defaults(func=cmd_migrate)
    p = sub.add_parser("collect", help="собрать вакансии через API hh.ru")
    p.add_argument("--raw-only", action="store_true", help="только сохранить сырой JSONL, без загрузки в БД")
    p.add_argument("--max", type=int, default=None, help="ограничить число вакансий (перекрывает COLLECT_MAX_VACANCIES)")
    p.set_defaults(func=cmd_collect)
    p = sub.add_parser("import", help="импорт файла JSONL/JSON/CSV")
    p.add_argument("--file", required=True)
    p.add_argument("--origin", choices=["import", "api", "synthetic"], default="import",
                   help="тип данных: import — внешний датасет, api — сохранённый ответ API, synthetic — синтетика")
    p.set_defaults(func=cmd_import)
    p = sub.add_parser("demo", help="сгенерировать и загрузить СИНТЕТИЧЕСКИЙ набор")
    p.add_argument("--n", type=int, default=600)
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=cmd_demo)
    sub.add_parser("status", help="состояние БД").set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    setup_logging(settings.log_level)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001
        log.error("Команда завершилась ошибкой: %s: %s", type(exc).__name__, str(exc).splitlines()[0][:300])
        return 1


if __name__ == "__main__":
    sys.exit(main())
