"""Воспроизводимый эксперимент: пакетная обработка вакансий в Pandas и (если установлен) PySpark.

Задача (одна и та же для обоих движков, один и тот же входной CSV):
  1. очистка текстовых описаний (удаление HTML, сжатие пробелов, нижний регистр);
  2. аналитическая зарплата (середина вилки «от–до», RUR, gross);
  3. агрегат регион × роль: число вакансий, число зарплат, среднее и медиана;
  4. частоты навыков (разворот списка навыков и подсчёт).

Входные данные — СИНТЕТИЧЕСКИЕ (генератор src/collectors/demo_data.py), масштабируемые параметром --rows:
реальных вакансий в нужном объёме без доступа к API нет. Результаты характеризуют скорость движков
на этой задаче и этой машине, а не рынок труда.

Запуск:
    python scripts/benchmark_spark.py --rows 100000 500000 --repeats 3 --out docs/benchmark_results.json
PySpark (необязательно): pip install pyspark  (нужна Java 11/17/21). Без него измеряется только Pandas,
о чём явно сообщается в результате (поле "spark": null).

Честность измерений: время — wall-clock всего задания, включая чтение CSV и получение итоговых чисел;
повторы выполняются в одном процессе; первый запуск Spark (прогрев JVM) учитывается отдельно и в
медиану не входит. Медиана в Spark — percentile_approx (приближённая), в Pandas — точная; различие
фиксируется в контрольных суммах.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src.collectors import demo_data  # noqa: E402

HTML_RE = r"<[^>]+>"
FIELDS = ["id", "region", "role", "salary_from", "salary_to", "currency", "gross", "skills", "description"]


def build_csv(path: Path, rows: int, seed: int) -> None:
    """Пишет плоский CSV из синтетических вакансий (генерация в замер не входит)."""
    items = demo_data.generate(rows, seed, now=datetime(2026, 10, 1, tzinfo=timezone.utc), with_defects=False)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for it in items:
            sal = it.get("salary") or {}
            writer.writerow({
                "id": it["id"], "region": it["area"]["name"],
                "role": (it.get("professional_roles") or [{}])[0].get("name", ""),
                "salary_from": sal.get("from") if sal.get("from") is not None else "",
                "salary_to": sal.get("to") if sal.get("to") is not None else "",
                "currency": sal.get("currency") or "", "gross": sal.get("gross") if "gross" in sal else "",
                "skills": ";".join(s["name"] for s in it.get("key_skills", [])),
                "description": it.get("description", ""),
            })


# ---------------- Pandas ----------------

def run_pandas(path: Path) -> dict:
    df = pd.read_csv(path, dtype={"id": "string"})
    cleaned = (df["description"].fillna("").str.replace(HTML_RE, " ", regex=True)
               .str.replace(r"\s+", " ", regex=True).str.strip().str.lower())
    ok = (df["salary_from"].notna() & df["salary_to"].notna() & (df["currency"] == "RUR") & (df["gross"].astype(str) == "True"))
    df["mid"] = ((df["salary_from"] + df["salary_to"]) / 2).where(ok)
    agg = df.groupby(["region", "role"], dropna=False).agg(
        n=("id", "size"), n_sal=("mid", "count"), mean=("mid", "mean"), median=("mid", "median"))
    skills = df["skills"].fillna("").str.split(";").explode()
    skills = skills[skills != ""]
    top = skills.value_counts().head(20)
    return {"rows": int(len(df)), "clean_chars": int(cleaned.str.len().sum()), "salary_rows": int(df["mid"].notna().sum()),
            "mean_mid": round(float(df["mid"].mean()), 4), "groups": int(len(agg)),
            "skill_rows": int(len(skills)), "top_skill": str(top.index[0]), "median_of_medians": round(float(agg["median"].median()), 2)}


# ---------------- PySpark ----------------

def spark_session(cores: int):
    from pyspark.sql import SparkSession
    return (SparkSession.builder.master(f"local[{cores}]").appName("hh-benchmark")
            .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", str(cores * 2))
            .config("spark.driver.memory", os.environ.get("SPARK_DRIVER_MEMORY", "3g")).getOrCreate())


def run_spark(spark, path: Path) -> dict:
    from pyspark.sql import functions as F
    sdf = spark.read.csv(str(path), header=True, inferSchema=False, multiLine=False)
    sdf = (sdf.withColumn("salary_from", F.col("salary_from").cast("double"))
           .withColumn("salary_to", F.col("salary_to").cast("double")))
    cleaned = F.lower(F.trim(F.regexp_replace(F.regexp_replace(F.coalesce(F.col("description"), F.lit("")), HTML_RE, " "), r"\s+", " ")))
    ok = (F.col("salary_from").isNotNull() & F.col("salary_to").isNotNull() & (F.col("currency") == "RUR") & (F.col("gross") == "True"))
    sdf = sdf.withColumn("mid", F.when(ok, (F.col("salary_from") + F.col("salary_to")) / 2)).withColumn("clean_len", F.length(cleaned))
    sdf = sdf.cache()
    totals = sdf.agg(F.count("*").alias("rows"), F.sum("clean_len").alias("clean_chars"),
                     F.count("mid").alias("salary_rows"), F.avg("mid").alias("mean_mid")).first()
    agg = (sdf.groupBy("region", "role").agg(F.count("*").alias("n"), F.count("mid").alias("n_sal"), F.avg("mid").alias("mean"),
                                             F.expr("percentile_approx(mid, 0.5)").alias("median")))
    groups = agg.count()
    med = agg.agg(F.expr("percentile(median, 0.5)").alias("m")).first()["m"]
    sk = (sdf.select(F.explode(F.split(F.coalesce(F.col("skills"), F.lit("")), ";")).alias("skill")).filter(F.col("skill") != ""))
    skill_rows = sk.count()
    top = sk.groupBy("skill").count().orderBy(F.desc("count"), F.asc("skill")).limit(1).first()["skill"]
    sdf.unpersist()
    return {"rows": int(totals["rows"]), "clean_chars": int(totals["clean_chars"]), "salary_rows": int(totals["salary_rows"]),
            "mean_mid": round(float(totals["mean_mid"]), 4), "groups": int(groups), "skill_rows": int(skill_rows),
            "top_skill": top, "median_of_medians": round(float(med), 2)}


# ---------------- измерение ----------------

def timed(fn, repeats: int) -> tuple[list[float], dict]:
    times, result = [], {}
    for _ in range(repeats):
        t0 = time.perf_counter()
        result = fn()
        times.append(time.perf_counter() - t0)
    return times, result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=int, nargs="+", default=[100_000])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workdir", default=str(ROOT / "data" / "bench"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "benchmark_results.json"))
    ap.add_argument("--no-spark", action="store_true", help="не запускать Spark, даже если он установлен")
    args = ap.parse_args()

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    cores = os.cpu_count() or 1

    spark = None
    spark_version = None
    if not args.no_spark:
        try:
            import pyspark
            spark = spark_session(cores)
            spark_version = pyspark.__version__
        except Exception as exc:  # noqa: BLE001 — нет pyspark / Java: измеряем только Pandas
            print(f"Spark недоступен ({type(exc).__name__}: {str(exc).splitlines()[0][:120]}) — измеряется только Pandas")

    report = {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "data_origin": "synthetic", "task": "очистка текста + зарплата + агрегат регион×роль + частоты навыков",
              "environment": {"python": platform.python_version(), "pandas": pd.__version__, "pyspark": spark_version,
                              "cpu_cores": cores, "platform": platform.platform()},
              "repeats": args.repeats, "runs": []}

    for rows in args.rows:
        path = workdir / f"bench_{rows}.csv"
        if not path.exists():
            print(f"Генерация {rows} строк…")
            build_csv(path, rows, args.seed)
        size_mb = round(path.stat().st_size / 1024 / 1024, 2)
        p_times, p_res = timed(lambda: run_pandas(path), args.repeats)
        entry = {"rows": rows, "file_mb": size_mb,
                 "pandas": {"times_sec": [round(t, 3) for t in p_times], "median_sec": round(statistics.median(p_times), 3), "result": p_res},
                 "spark": None, "results_match": None}
        if spark is not None:
            t0 = time.perf_counter()
            first = run_spark(spark, path)           # первый запуск: прогрев JVM, отдельно
            warmup = time.perf_counter() - t0
            s_times, s_res = timed(lambda: run_spark(spark, path), args.repeats)
            entry["spark"] = {"warmup_run_sec": round(warmup, 3), "times_sec": [round(t, 3) for t in s_times],
                              "median_sec": round(statistics.median(s_times), 3), "result": s_res}
            exact = ("rows", "clean_chars", "salary_rows", "groups", "skill_rows", "top_skill")
            entry["results_match"] = all(p_res[k] == s_res[k] for k in exact) and abs(p_res["mean_mid"] - s_res["mean_mid"]) < 1e-3
        report["runs"].append(entry)
        line = f"{rows:>9} строк, {size_mb:>7} МБ | Pandas: {entry['pandas']['median_sec']:>7} с"
        if entry["spark"]:
            line += f" | Spark: {entry['spark']['median_sec']:>7} с (прогрев {entry['spark']['warmup_run_sec']} с) | совпадение: {entry['results_match']}"
        else:
            line += " | Spark: не запускался"
        print(line)

    if spark is not None:
        spark.stop()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Результаты: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
