"""Показатели рынка труда. Чистые функции над DataFrame — легко тестируются без БД.

Правила сопоставимости зарплат (подробно: docs/METRICS.md):
* «Сопоставимая» зарплата — вакансия с ОБЕИМИ границами (salary_kind = 'range'); аналитическое
  значение salary_mid = (от + до) / 2.
* Сравниваются только вакансии в ОДНОЙ валюте и с ОДНИМ признаком gross/net (SalaryBasis).
  Валюты не конвертируются; gross и net не смешиваются; вакансии с неизвестным gross/net
  в сопоставимую выборку не входят.
* Односторонние значения («от X», «до Y») и некорректные зарплаты в среднее/медиану не входят.
* Группы меньше min_n наблюдений не показываются как сравнимые.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MIN_GROUP_DEFAULT = 5
NOT_SPECIFIED = "Не указано"
EXPERIENCE_ORDER = ["Нет опыта", "От 1 года до 3 лет", "От 3 до 6 лет", "Более 6 лет"]


@dataclass(frozen=True)
class SalaryBasis:
    """Основа сопоставимости: валюта и тип зарплаты (True — gross, до вычета налогов; False — net)."""
    currency: str = "RUB"
    gross: bool = True

    @property
    def label(self) -> str:
        return f"{self.currency}, {'до вычета налогов (gross)' if self.gross else 'на руки (net)'}"


# ---------- сопоставимая выборка ----------

def available_bases(df: pd.DataFrame) -> pd.DataFrame:
    """Группы (валюта, gross/net) с числом сопоставимых вакансий — для выбора основы в интерфейсе."""
    cols = ["currency", "gross", "n"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    ranged = df[(df["salary_kind"] == "range") & df["salary_mid"].notna()
                & df["salary_currency"].notna() & df["salary_gross"].notna()]
    if ranged.empty:
        return pd.DataFrame(columns=cols)
    grouped = (ranged.groupby(["salary_currency", "salary_gross"]).size().reset_index(name="n")
               .rename(columns={"salary_currency": "currency", "salary_gross": "gross"})
               .sort_values("n", ascending=False).reset_index(drop=True))
    grouped["gross"] = grouped["gross"].astype(bool)
    return grouped[cols]


def default_basis(df: pd.DataFrame) -> SalaryBasis | None:
    """Самая многочисленная основа сопоставимости или None, если сопоставимых зарплат нет."""
    bases = available_bases(df)
    if bases.empty:
        return None
    top = bases.iloc[0]
    return SalaryBasis(str(top["currency"]), bool(top["gross"]))


def salary_pool(df: pd.DataFrame, basis: SalaryBasis | None) -> pd.DataFrame:
    """Вакансии с сопоставимой зарплатой для выбранной основы."""
    if basis is None or df.empty:
        return df.iloc[0:0]
    mask = ((df["salary_kind"] == "range") & df["salary_mid"].notna()
            & (df["salary_currency"] == basis.currency) & (df["salary_gross"] == basis.gross))
    return df[mask]


def exclude_outliers(pool: pd.DataFrame, k: float = 3.0) -> tuple[pd.DataFrame, int]:
    """Исключает статистические выбросы по правилу Тьюки: вне [Q1 − k·IQR; Q3 + k·IQR].

    k = 3 — «далёкие» выбросы (консервативно). Возвращает (выборка, число исключённых).
    """
    if len(pool) < 8:
        return pool, 0
    q1, q3 = pool["salary_mid"].quantile([0.25, 0.75])
    iqr = q3 - q1
    low, high = q1 - k * iqr, q3 + k * iqr
    kept = pool[(pool["salary_mid"] >= low) & (pool["salary_mid"] <= high)]
    return kept, len(pool) - len(kept)


def describe_salary(values: pd.Series) -> dict:
    """Описательные статистики: n, среднее, медиана, квартили, мин, макс (None, если данных нет)."""
    s = pd.to_numeric(values, errors="coerce").dropna()
    if s.empty:
        return {"n": 0, "mean": None, "median": None, "p25": None, "p75": None, "min": None, "max": None}
    return {"n": int(len(s)), "mean": float(s.mean()), "median": float(s.median()),
            "p25": float(s.quantile(0.25)), "p75": float(s.quantile(0.75)),
            "min": float(s.min()), "max": float(s.max())}


# ---------- общие показатели ----------

def overview(df: pd.DataFrame, skills: pd.DataFrame, basis: SalaryBasis | None) -> dict:
    """KPI главной панели."""
    total = len(df)
    pool = salary_pool(df, basis)
    stats = describe_salary(pool["salary_mid"]) if not pool.empty else describe_salary(pd.Series(dtype=float))
    with_salary = int((df["salary_kind"] != "none").sum()) if total else 0
    top = top_skills(skills, 1, total)
    return {
        "vacancies": total,
        "employers": int(df["employer_id"].nunique()) if total else 0,
        "with_salary": with_salary,                       # указана зарплата в любом виде (в т.ч. «от»/«до»)
        "with_salary_share": (with_salary / total) if total else None,
        "comparable": stats["n"],                         # вилка «от–до» в выбранной основе
        "median": stats["median"], "mean": stats["mean"],
        "invalid_salary": int((df["salary_kind"] == "invalid").sum()) if total else 0,
        "top_skill": top.iloc[0]["skill"] if not top.empty else None,
        "top_skill_count": int(top.iloc[0]["vacancies"]) if not top.empty else 0,
    }


def distribution(df: pd.DataFrame, column: str, top: int | None = None, label: str = NOT_SPECIFIED) -> pd.DataFrame:
    """Распределение вакансий по категориальному полю; пропуски выводятся отдельной категорией."""
    if df.empty or column not in df:
        return pd.DataFrame(columns=[column, "count", "share"])
    counts = df[column].fillna(label).value_counts()
    out = counts.rename_axis(column).reset_index(name="count")
    out["share"] = out["count"] / len(df)
    return out.head(top) if top else out


def experience_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """Распределение по опыту в естественном порядке (а не по убыванию)."""
    out = distribution(df, "experience")
    if out.empty:
        return out
    order = {name: i for i, name in enumerate(EXPERIENCE_ORDER)}
    out["_o"] = out["experience"].map(lambda v: order.get(v, 99 if v != NOT_SPECIFIED else 100))
    return out.sort_values("_o").drop(columns="_o").reset_index(drop=True)


def dynamics(df: pd.DataFrame, freq: str = "D") -> pd.DataFrame:
    """Число опубликованных вакансий по дням ('D') или неделям ('W'); пустые периоды = 0."""
    if df.empty or "published_at" not in df:
        return pd.DataFrame(columns=["period", "count"])
    s = pd.to_datetime(df["published_at"], utc=True, errors="coerce").dropna()
    if s.empty:
        return pd.DataFrame(columns=["period", "count"])
    s = s.dt.tz_convert(None)
    if freq == "W":
        periods = s.dt.to_period("W").dt.start_time
    else:
        periods = s.dt.normalize()
    counts = periods.value_counts().sort_index()
    full = pd.date_range(counts.index.min(), counts.index.max(), freq="W-MON" if freq == "W" else "D")
    counts = counts.reindex(full, fill_value=0)
    return pd.DataFrame({"period": counts.index, "count": counts.values})


def missing_report(df: pd.DataFrame) -> pd.DataFrame:
    """Доля пропусков и некорректных значений в выбранной выборке."""
    if df.empty:
        return pd.DataFrame(columns=["field", "missing", "share"])
    fields = {
        "employer_name": "Работодатель", "region_name": "Регион", "role_name": "Профессиональная роль",
        "published_at": "Дата публикации", "experience": "Опыт", "employment": "Тип занятости",
        "schedule": "График", "url": "Ссылка на источник",
    }
    rows = [{"field": label, "missing": int(df[col].isna().sum()), "share": float(df[col].isna().mean())}
            for col, label in fields.items() if col in df]
    rows.append({"field": "Зарплата не указана", "missing": int((df["salary_kind"] == "none").sum()),
                 "share": float((df["salary_kind"] == "none").mean())})
    rows.append({"field": "Зарплата некорректна", "missing": int((df["salary_kind"] == "invalid").sum()),
                 "share": float((df["salary_kind"] == "invalid").mean())})
    return pd.DataFrame(rows)


# ---------- группы и сравнения зарплат ----------

def group_summary(df: pd.DataFrame, pool: pd.DataFrame, by: str, min_n: int = MIN_GROUP_DEFAULT) -> pd.DataFrame:
    """Сводка по группам (регион, роль, опыт…): все вакансии группы и сопоставимая зарплата.

    Колонки: vacancies — все вакансии группы; salary_share — доля с указанной зарплатой;
    n — число сопоставимых зарплат; median/mean/p25/p75 — только если n ≥ min_n, иначе NaN.
    """
    cols = [by, "vacancies", "salary_share", "n", "median", "mean", "p25", "p75", "reliable"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    key = df[by].fillna(NOT_SPECIFIED)
    base = (df.assign(_k=key).groupby("_k")
            .agg(vacancies=("id", "size"), salary_share=("salary_kind", lambda s: float((s != "none").mean())))
            .rename_axis(by).reset_index())
    if pool.empty:
        stats = pd.DataFrame(columns=[by, "n", "median", "mean", "p25", "p75"])
    else:
        grouped = pool.assign(_k=pool[by].fillna(NOT_SPECIFIED)).groupby("_k")["salary_mid"]
        stats = pd.DataFrame({
            "n": grouped.size(), "median": grouped.median(), "mean": grouped.mean(),
            "p25": grouped.quantile(0.25), "p75": grouped.quantile(0.75),
        }).rename_axis(by).reset_index()
    out = base.merge(stats, on=by, how="left")
    out["n"] = out["n"].fillna(0).astype(int)
    out["reliable"] = out["n"] >= min_n
    for col in ("median", "mean", "p25", "p75"):
        out.loc[~out["reliable"], col] = np.nan
    return out[cols].sort_values(["reliable", "median", "vacancies"], ascending=[False, False, False]).reset_index(drop=True)


# ---------- навыки ----------

def top_skills(skills: pd.DataFrame, n: int = 20, total_vacancies: int | None = None) -> pd.DataFrame:
    """Рейтинг навыков: число вакансий с навыком и его доля в выборке."""
    cols = ["skill", "vacancies", "share"]
    if skills.empty:
        return pd.DataFrame(columns=cols)
    counts = (skills.drop_duplicates(["vacancy_id", "skill"]).groupby("skill")["vacancy_id"].nunique()
              .sort_values(ascending=False, kind="stable"))
    out = counts.rename("vacancies").reset_index()
    denominator = total_vacancies or skills["vacancy_id"].nunique()
    out["share"] = out["vacancies"] / denominator if denominator else np.nan
    # стабильный порядок: по числу вакансий, затем по названию
    out = out.sort_values(["vacancies", "skill"], ascending=[False, True]).head(n).reset_index(drop=True)
    return out[cols]


def skill_salary(pool: pd.DataFrame, skills: pd.DataFrame, min_n: int = MIN_GROUP_DEFAULT) -> pd.DataFrame:
    """Зарплаты вакансий с навыком и без него (ассоциация, не причинность).

    Для каждого навыка: n (с навыком, в сопоставимой выборке), median/mean «с навыком»,
    median_without — медиана остальных сопоставимых вакансий, diff — разность медиан.
    Показываются только навыки, у которых n ≥ min_n И «без навыка» тоже ≥ min_n.
    """
    cols = ["skill", "n", "median", "mean", "n_without", "median_without", "diff"]
    if pool.empty or skills.empty:
        return pd.DataFrame(columns=cols)
    links = skills.drop_duplicates(["vacancy_id", "skill"])
    links = links[links["vacancy_id"].isin(pool["id"])]
    if links.empty:
        return pd.DataFrame(columns=cols)
    mids = pool.set_index("id")["salary_mid"]
    rows = []
    total = len(pool)
    for skill, group in links.groupby("skill"):
        ids = group["vacancy_id"]
        n = len(ids)
        n_without = total - n
        if n < min_n or n_without < min_n:
            continue
        with_vals = mids.loc[ids]
        without_vals = mids.drop(index=ids)
        rows.append({"skill": skill, "n": n, "median": float(with_vals.median()), "mean": float(with_vals.mean()),
                     "n_without": n_without, "median_without": float(without_vals.median()),
                     "diff": float(with_vals.median() - without_vals.median())})
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows, columns=cols).sort_values("n", ascending=False).reset_index(drop=True)


def with_without(pool: pd.DataFrame, skills: pd.DataFrame, skill: str, min_n: int = MIN_GROUP_DEFAULT,
                 n_boot: int = 1000, seed: int = 0) -> dict:
    """Сравнение зарплат вакансий с навыком и без него + бутстреп-интервал разности медиан (95 %).

    Это описание различия в выборках, а не оценка влияния навыка на зарплату: на зарплату влияют
    опыт, регион, роль и другое, чего здесь не учитывается.
    """
    has = set(skills.loc[skills["skill"] == skill, "vacancy_id"])
    with_vals = pool.loc[pool["id"].isin(has), "salary_mid"].to_numpy(dtype=float)
    without_vals = pool.loc[~pool["id"].isin(has), "salary_mid"].to_numpy(dtype=float)
    result = {
        "skill": skill, "with": describe_salary(pd.Series(with_vals)), "without": describe_salary(pd.Series(without_vals)),
        "enough": len(with_vals) >= min_n and len(without_vals) >= min_n,
        "diff_median": None, "ci_low": None, "ci_high": None,
    }
    if not result["enough"]:
        return result
    rng = np.random.default_rng(seed)
    a = rng.choice(with_vals, size=(n_boot, len(with_vals)), replace=True)
    b = rng.choice(without_vals, size=(n_boot, len(without_vals)), replace=True)
    diffs = np.median(a, axis=1) - np.median(b, axis=1)
    result["diff_median"] = float(np.median(with_vals) - np.median(without_vals))
    result["ci_low"], result["ci_high"] = (float(x) for x in np.percentile(diffs, [2.5, 97.5]))
    return result


def cooccurrence(skills: pd.DataFrame, top_k: int = 15, min_pair: int = 1) -> pd.DataFrame:
    """Матрица связей навыков для top_k самых частых: коэффициент Жаккара J = |A∩B| / |A∪B| (0..1).

    Диагональ = 1. Пары, встретившиеся реже min_pair вакансий, обнуляются.
    """
    top = top_skills(skills, top_k)
    if len(top) < 2:
        return pd.DataFrame()
    names = top["skill"].tolist()
    sub = skills[skills["skill"].isin(names)].drop_duplicates(["vacancy_id", "skill"])
    matrix = pd.crosstab(sub["vacancy_id"], sub["skill"]).reindex(columns=names, fill_value=0).astype(int)
    x = matrix.to_numpy()
    inter = x.T @ x
    sizes = np.diag(inter)
    union = sizes[:, None] + sizes[None, :] - inter
    jaccard = np.divide(inter, union, out=np.zeros_like(inter, dtype=float), where=union > 0)
    jaccard[inter < min_pair] = 0.0
    np.fill_diagonal(jaccard, 1.0)
    return pd.DataFrame(jaccard, index=names, columns=names)


# ---------- подбор навыков («что выучить») ----------

_EPS = 1e-9


def _mine(my_skills) -> set[str]:
    return {str(s).strip().lower() for s in my_skills if str(s).strip()}


def vacancy_coverage(skills: pd.DataFrame, my_skills, min_skills: int = 2) -> pd.DataFrame:
    """Покрытие вакансий навыками пользователя: n_total, n_have, coverage = n_have / n_total.

    Вакансии, где указано меньше min_skills навыков, исключаются: по ним нельзя судить о требованиях.
    """
    cols = ["vacancy_id", "n_total", "n_have", "coverage"]
    if skills.empty:
        return pd.DataFrame(columns=cols)
    links = skills.drop_duplicates(["vacancy_id", "skill"])
    links = links.assign(have=links["skill"].str.lower().isin(_mine(my_skills)))
    grouped = links.groupby("vacancy_id")["have"].agg(n_total="size", n_have="sum").reset_index()
    grouped = grouped[grouped["n_total"] >= min_skills].copy()
    grouped["n_have"] = grouped["n_have"].astype(int)
    grouped["coverage"] = grouped["n_have"] / grouped["n_total"]
    return grouped[cols].reset_index(drop=True)


def match_summary(df: pd.DataFrame, skills: pd.DataFrame, my_skills, min_cover: float = 0.6,
                  min_skills: int = 2, pool: pd.DataFrame | None = None) -> dict:
    """Сколько вакансий «подходит» (у пользователя ≥ min_cover навыков вакансии) и какая у них зарплата."""
    cov = vacancy_coverage(skills, my_skills, min_skills)
    cov = cov[cov["vacancy_id"].isin(df["id"])] if not df.empty else cov.iloc[0:0]
    matched = cov[cov["coverage"] >= min_cover - _EPS]
    salaries = pd.Series(dtype=float)
    if pool is not None and not pool.empty and not matched.empty:
        salaries = pool.loc[pool["id"].isin(matched["vacancy_id"]), "salary_mid"]
    return {"eligible": int(len(cov)), "matched": int(len(matched)),
            "share": (len(matched) / len(cov)) if len(cov) else None,
            "salary": describe_salary(salaries)}


def skill_gaps(skills: pd.DataFrame, my_skills, min_cover: float = 0.6, min_skills: int = 2, top: int = 10) -> pd.DataFrame:
    """Какие навыки сильнее всего расширят выбор.

    gain — число вакансий, которые сейчас НЕ подходят, но станут подходящими (покрытие ≥ min_cover),
    если добавить этот навык. Считается для каждого навыка отдельно (жадная оценка «следующего шага»).
    """
    cols = ["skill", "gain", "demand"]
    cov = vacancy_coverage(skills, my_skills, min_skills)
    if cov.empty:
        return pd.DataFrame(columns=cols)
    unmatched = cov[cov["coverage"] < min_cover - _EPS]
    reachable = unmatched[(unmatched["n_have"] + 1) / unmatched["n_total"] >= min_cover - _EPS]
    if reachable.empty:
        return pd.DataFrame(columns=cols)
    links = skills.drop_duplicates(["vacancy_id", "skill"])
    missing = links[links["vacancy_id"].isin(reachable["vacancy_id"]) & ~links["skill"].str.lower().isin(_mine(my_skills))]
    gain = missing.groupby("skill").size().rename("gain").reset_index()
    demand = links.groupby("skill")["vacancy_id"].nunique().rename("demand").reset_index()
    out = gain.merge(demand, on="skill", how="left")
    return out.sort_values(["gain", "demand", "skill"], ascending=[False, False, True]).head(top).reset_index(drop=True)[cols]


def top_matches(df: pd.DataFrame, skills: pd.DataFrame, my_skills, min_cover: float = 0.6,
                min_skills: int = 2, top: int = 20) -> pd.DataFrame:
    """Лучшие подходящие вакансии: покрытие и список недостающих навыков."""
    cols = ["id", "title", "employer_name", "region_name", "coverage", "missing", "url"]
    cov = vacancy_coverage(skills, my_skills, min_skills)
    cov = cov[cov["coverage"] >= min_cover - _EPS]
    if cov.empty or df.empty:
        return pd.DataFrame(columns=cols)
    links = skills.drop_duplicates(["vacancy_id", "skill"])
    lack = links[~links["skill"].str.lower().isin(_mine(my_skills))]
    missing = lack.groupby("vacancy_id")["skill"].agg(lambda s: ", ".join(sorted(s))).rename("missing")
    merged = cov.merge(df, left_on="vacancy_id", right_on="id").merge(missing, left_on="vacancy_id", right_index=True, how="left")
    merged["missing"] = merged["missing"].fillna("")
    merged = merged.sort_values(["coverage", "n_have", "n_total"], ascending=[False, False, False])
    return merged.head(top).reset_index(drop=True)[cols]


# ---------- тренды и прогноз ----------

def skill_trend(df: pd.DataFrame, skills: pd.DataFrame, recent_days: int = 14, min_period: int = 30,
                min_count: int = 5, top: int = 10) -> pd.DataFrame:
    """Изменение доли вакансий с навыком: последние recent_days против предыдущих recent_days.

    delta_pp — разность долей в процентных пунктах. Строится, только если в каждом периоде не меньше
    min_period вакансий; навык берётся, если он встретился ≥ min_count раз хотя бы в одном периоде.
    """
    cols = ["skill", "share_prior", "share_recent", "delta_pp", "n_prior", "n_recent"]
    if df.empty or skills.empty or "published_at" not in df:
        return pd.DataFrame(columns=cols)
    dates = pd.to_datetime(df.set_index("id")["published_at"], utc=True, errors="coerce").dropna()
    if dates.empty:
        return pd.DataFrame(columns=cols)
    end = dates.max()
    recent_ids = dates[dates > end - pd.Timedelta(days=recent_days)].index
    prior_ids = dates[(dates > end - pd.Timedelta(days=2 * recent_days)) & (dates <= end - pd.Timedelta(days=recent_days))].index
    if len(recent_ids) < min_period or len(prior_ids) < min_period:
        return pd.DataFrame(columns=cols)
    links = skills.drop_duplicates(["vacancy_id", "skill"])
    n_recent = links[links["vacancy_id"].isin(recent_ids)].groupby("skill").size()
    n_prior = links[links["vacancy_id"].isin(prior_ids)].groupby("skill").size()
    table = pd.concat([n_prior.rename("n_prior"), n_recent.rename("n_recent")], axis=1).fillna(0).astype(int)
    table = table[(table["n_prior"] >= min_count) | (table["n_recent"] >= min_count)]
    table["share_prior"] = table["n_prior"] / len(prior_ids)
    table["share_recent"] = table["n_recent"] / len(recent_ids)
    table["delta_pp"] = (table["share_recent"] - table["share_prior"]) * 100
    out = table.reset_index().rename(columns={"index": "skill"})
    out = out.reindex(out["delta_pp"].abs().sort_values(ascending=False).index).head(top)
    return out[cols].reset_index(drop=True)


def _fit_forecast(y: np.ndarray, dow: np.ndarray, future_dow: np.ndarray, trend: bool) -> tuple[np.ndarray, float]:
    """Аддитивная регрессия: y = эффект дня недели (+ b·t при trend). Параметры подбираются совместно
    методом наименьших квадратов, поэтому тренд не искажает недельную сезонность и наоборот."""
    def design(days: np.ndarray, t: np.ndarray) -> np.ndarray:
        cols = [(days == d).astype(float) for d in range(7)]
        if trend:
            cols.append(t)
        return np.column_stack(cols)

    t = np.arange(len(y), dtype=float)
    x = design(dow, t)
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ coef
    dof = max(len(y) - x.shape[1], 1)
    sigma = float(np.sqrt(np.sum(resid ** 2) / dof))
    tf = len(y) + np.arange(len(future_dow), dtype=float)
    return np.maximum(0.0, design(future_dow, tf) @ coef), sigma


def forecast_counts(daily: pd.DataFrame, horizon: int = 14, holdout: int = 7, min_days: int = 28,
                    fit_days: int = 56, drop_last: bool = True) -> dict:
    """Прогноз числа публикаций по дням: недельная сезонность + (необязательно) линейный тренд.

    Из двух вариантов (с трендом и без) выбирается тот, у которого меньше средняя абсолютная ошибка на
    отложенных последних `holdout` днях; ошибка сравнивается с наивным прогнозом «как неделю назад».
    Интервал — приближённый: ±1,96·σ остатков (нормальное приближение), не меньше нуля.
    Последний день может быть неполным (сбор шёл в течение дня), поэтому по умолчанию отбрасывается.
    """
    if daily.empty:
        return {"ok": False, "reason": "нет данных о датах публикации"}
    series = daily.sort_values("period").reset_index(drop=True)
    if drop_last and len(series) > 1:
        series = series.iloc[:-1]
    if len(series) < min_days:
        return {"ok": False, "reason": f"для прогноза нужно не менее {min_days} дней истории, есть {len(series)}"}
    series = series.tail(fit_days).reset_index(drop=True)
    y = series["count"].to_numpy(dtype=float)
    dates = pd.to_datetime(series["period"])
    dow = dates.dt.dayofweek.to_numpy()

    # проверка на отложенном участке
    h = min(holdout, 7, len(y) // 4)
    scores = {}
    for use_trend in (True, False):
        pred, _ = _fit_forecast(y[:-h], dow[:-h], dow[-h:], use_trend)
        scores[use_trend] = float(np.mean(np.abs(pred - y[-h:])))
    use_trend = scores[True] <= scores[False]
    naive = float(np.mean(np.abs(y[-h - 7:-7] - y[-h:]))) if len(y) >= h + 7 else None
    backtest = {"holdout_days": int(h), "mae": scores[use_trend], "naive_mae": naive,
                "trend": bool(use_trend), "better_than_naive": (naive is None) or scores[use_trend] <= naive}

    future_dates = pd.date_range(dates.iloc[-1] + pd.Timedelta(days=1), periods=horizon, freq="D")
    yhat, sigma = _fit_forecast(y, dow, future_dates.dayofweek.to_numpy(), use_trend)
    forecast = pd.DataFrame({"period": future_dates, "yhat": yhat,
                             "lo": np.maximum(0.0, yhat - 1.96 * sigma), "hi": yhat + 1.96 * sigma})
    return {"ok": True, "history": series, "forecast": forecast, "backtest": backtest, "sigma": sigma}
