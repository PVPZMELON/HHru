import numpy as np
import pandas as pd
import pytest

from src.analytics import metrics as m


def make_df(rows):
    """rows: (id, kind, mid, currency, gross, region, role, skills-set) — минимальная таблица вакансий."""
    recs = []
    for i, (kind, mid, cur, gross, region, role) in enumerate(rows, start=1):
        recs.append({"id": i, "salary_kind": kind, "salary_mid": mid, "salary_currency": cur, "salary_gross": gross,
                     "region_name": region, "role_name": role, "employer_id": i % 3 or None, "experience": "Нет опыта",
                     "published_at": pd.Timestamp("2026-10-01", tz="UTC") + pd.Timedelta(days=i % 4 * 2)})
    return pd.DataFrame(recs)


def skills_df(pairs):
    return pd.DataFrame(pairs, columns=["vacancy_id", "skill", "origin"]) if pairs else pd.DataFrame(columns=["vacancy_id", "skill", "origin"])


MIXED = make_df([
    ("range", 100.0, "RUB", True, "М", "A"), ("range", 200.0, "RUB", True, "М", "A"), ("range", 300.0, "RUB", True, "С", "B"),
    ("range", 90.0, "RUB", False, "М", "A"),            # net — другая основа
    ("range", 10.0, "USD", True, "М", "A"),             # другая валюта
    ("from_only", None, "RUB", True, "М", "A"),         # одна граница — не точная зарплата
    ("none", None, None, None, "С", "B"), ("invalid", None, "RUB", True, "С", "B"),
    ("range", 500.0, "RUB", None, "М", "A"),            # gross неизвестен
])


def test_pool_compares_only_same_currency_and_gross():
    basis = m.SalaryBasis("RUB", True)
    assert sorted(m.salary_pool(MIXED, basis)["salary_mid"]) == [100.0, 200.0, 300.0]
    assert sorted(m.salary_pool(MIXED, m.SalaryBasis("RUB", False))["salary_mid"]) == [90.0]
    assert m.default_basis(MIXED) == basis
    bases = m.available_bases(MIXED)
    assert set(zip(bases.currency, bases.gross)) == {("RUB", True), ("RUB", False), ("USD", True)}   # без gross=None


def test_empty_and_no_salaries():
    empty = MIXED.iloc[0:0]
    assert m.default_basis(empty) is None and m.available_bases(empty).empty
    assert m.salary_pool(empty, m.SalaryBasis()).empty and m.salary_pool(MIXED, None).empty
    none_only = make_df([("none", None, None, None, "М", "A")] * 3)
    assert m.default_basis(none_only) is None
    k = m.overview(empty, skills_df([]), None)
    assert k["vacancies"] == 0 and k["median"] is None and k["with_salary_share"] is None and k["top_skill"] is None
    assert m.dynamics(empty).empty and m.distribution(empty, "region_name").empty and m.missing_report(empty).empty


def test_describe_salary():
    d = m.describe_salary(pd.Series([100, 200, 300, 400]))
    assert d["n"] == 4 and d["mean"] == 250 and d["median"] == 250 and d["min"] == 100 and d["max"] == 400
    assert d["p25"] == 175 and d["p75"] == 325
    assert m.describe_salary(pd.Series([], dtype=float))["median"] is None
    assert m.describe_salary(pd.Series([1, None, "x"]))["n"] == 1


def test_overview_values():
    basis = m.SalaryBasis("RUB", True)
    sk = skills_df([(1, "Python", "structured"), (2, "Python", "structured"), (3, "SQL", "structured")])
    k = m.overview(MIXED, sk, basis)
    assert k["vacancies"] == 9 and k["with_salary"] == 8          # все, кроме kind="none" (invalid тоже «указана»)
    assert k["comparable"] == 3 and k["median"] == 200 and k["mean"] == 200
    assert k["invalid_salary"] == 1 and k["top_skill"] == "Python" and k["top_skill_count"] == 2
    assert k["employers"] == 2


def test_group_summary_min_n():
    pool = m.salary_pool(MIXED, m.SalaryBasis("RUB", True))
    g = m.group_summary(MIXED, pool, "region_name", min_n=2).set_index("region_name")
    assert g.loc["М", "n"] == 2 and bool(g.loc["М", "reliable"]) and g.loc["М", "median"] == 150
    assert g.loc["С", "n"] == 1 and not g.loc["С", "reliable"] and np.isnan(g.loc["С", "median"])   # мало данных — не показываем
    assert g.loc["М", "vacancies"] == 6 and g.loc["С", "vacancies"] == 3
    assert m.group_summary(MIXED, MIXED.iloc[0:0], "region_name").n.sum() == 0


def test_group_summary_missing_label():
    df = make_df([("range", 100.0, "RUB", True, None, "A")] * 3)
    g = m.group_summary(df, m.salary_pool(df, m.SalaryBasis()), "region_name", 2)
    assert list(g["region_name"]) == [m.NOT_SPECIFIED]


def test_top_skills_counts_unique_vacancies():
    sk = skills_df([(1, "Python", "structured"), (1, "Python", "text"), (2, "Python", "text"), (2, "SQL", "text")])
    t = m.top_skills(sk, 5, total_vacancies=4)
    assert t.iloc[0].to_dict() == {"skill": "Python", "vacancies": 2, "share": 0.5}
    assert m.top_skills(skills_df([])).empty


def _salary_world(n_with=6, n_without=6, gap=100.0):
    rows = [("range", 100.0 + i, "RUB", True, "М", "A") for i in range(n_without)]
    rows += [("range", 100.0 + gap + i, "RUB", True, "М", "A") for i in range(n_with)]
    df = make_df(rows)
    sk = skills_df([(n_without + 1 + i, "Spark", "structured") for i in range(n_with)])
    return df, sk


def test_skill_salary_and_difference():
    df, sk = _salary_world()
    out = m.skill_salary(m.salary_pool(df, m.SalaryBasis()), sk, min_n=5)
    r = out.iloc[0]
    assert r["skill"] == "Spark" and r["n"] == 6 and r["n_without"] == 6 and r["diff"] == 100.0


def test_skill_salary_requires_both_groups():
    df, sk = _salary_world(n_with=6, n_without=3)
    assert m.skill_salary(m.salary_pool(df, m.SalaryBasis()), sk, min_n=5).empty
    df, sk = _salary_world(n_with=3, n_without=6)
    assert m.skill_salary(m.salary_pool(df, m.SalaryBasis()), sk, min_n=5).empty


def test_with_without_bootstrap_ci_reproducible():
    df, sk = _salary_world(gap=100.0)
    pool = m.salary_pool(df, m.SalaryBasis())
    a = m.with_without(pool, sk, "Spark", min_n=5, n_boot=500, seed=1)
    b = m.with_without(pool, sk, "Spark", min_n=5, n_boot=500, seed=1)
    assert a == b and a["enough"] and a["diff_median"] == 100.0 and a["ci_low"] <= 100.0 <= a["ci_high"] and a["ci_low"] > 0
    small = m.with_without(pool, sk, "Spark", min_n=7)
    assert not small["enough"] and small["diff_median"] is None


def test_cooccurrence_jaccard():
    sk = skills_df([(1, "A", "s"), (1, "B", "s"), (2, "A", "s"), (2, "B", "s"), (3, "A", "s"), (4, "B", "s"), (5, "C", "s")])
    j = m.cooccurrence(sk, top_k=3)
    assert j.loc["A", "B"] == pytest.approx(2 / 4) and j.loc["A", "A"] == 1.0 and j.loc["A", "C"] == 0.0
    assert (j.to_numpy() == j.to_numpy().T).all()
    assert m.cooccurrence(skills_df([(1, "A", "s")])).empty


def test_dynamics_fills_gaps_and_weeks():
    df = pd.DataFrame({"published_at": pd.to_datetime(["2026-10-01", "2026-10-01", "2026-10-04"], utc=True)})
    d = m.dynamics(df, "D")
    assert list(d["count"]) == [2, 0, 0, 1] and len(d) == 4
    w = m.dynamics(df, "W")
    assert w["count"].sum() == 3 and w["period"].iloc[0].weekday() == 0     # неделя начинается с понедельника
    assert m.dynamics(pd.DataFrame({"published_at": [pd.NaT]})).empty


def test_distribution_and_experience_order():
    df = pd.DataFrame({"experience": ["Более 6 лет", "Нет опыта", None, "От 3 до 6 лет", "Нет опыта"]})
    d = m.distribution(df, "experience")
    assert d.iloc[0]["experience"] == "Нет опыта" and m.NOT_SPECIFIED in set(d["experience"]) and d["share"].sum() == pytest.approx(1)
    assert list(m.experience_distribution(df)["experience"]) == ["Нет опыта", "От 3 до 6 лет", "Более 6 лет", m.NOT_SPECIFIED]


def test_exclude_outliers():
    df = make_df([("range", float(v), "RUB", True, "М", "A") for v in [100, 102, 98, 101, 99, 103, 97, 100, 5000]])
    kept, n = m.exclude_outliers(df)
    assert n == 1 and 5000 not in set(kept["salary_mid"])
    small = df.head(5)
    assert m.exclude_outliers(small) == (small, 0) or m.exclude_outliers(small)[1] == 0   # слишком мало данных — не трогаем


def test_missing_report():
    r = m.missing_report(MIXED).set_index("field")
    assert r.loc["Зарплата не указана", "missing"] == 1 and r.loc["Зарплата некорректна", "missing"] == 1


# ---- подбор навыков ----
def _sk(spec):
    return skills_df([(vid, s, "structured") for vid, ss in spec.items() for s in ss])


def test_coverage_and_matches():
    sk = _sk({1: ["A", "B", "C"], 2: ["A", "B"], 3: ["B", "C", "D"], 4: ["A"]})
    cov = m.vacancy_coverage(sk, {"a"}).set_index("vacancy_id")        # регистр навыков не важен, вакансия 4 (1 навык) исключена
    assert list(cov.index) == [1, 2, 3] and cov.loc[2, "coverage"] == 0.5 and cov.loc[3, "n_have"] == 0
    df = make_df([("none", None, None, None, "М", "A")] * 4)
    s = m.match_summary(df, sk, {"A"}, min_cover=0.5)
    assert s["eligible"] == 3 and s["matched"] == 1 and s["share"] == pytest.approx(1 / 3)


def test_skill_gaps_gain():
    sk = _sk({1: ["A", "B", "C"], 2: ["A", "B"], 3: ["B", "C", "D"]})
    gaps = m.skill_gaps(sk, {"A"}, min_cover=0.5).set_index("skill")
    # вакансия 1 (1/3) станет подходящей с B или C (2/3); вакансия 3 (0/3) даже с одним навыком не дотянет до 0,5
    assert gaps.loc["B", "gain"] == 1 and gaps.loc["C", "gain"] == 1 and "D" not in gaps.index
    assert m.skill_gaps(sk, {"A", "B", "C", "D"}).empty and m.skill_gaps(skills_df([]), {"A"}).empty


def test_top_matches_lists_missing_skills():
    df = make_df([("none", None, None, None, "М", "A")] * 3).assign(title=["t1", "t2", "t3"], employer_name="E", url=None)
    sk = _sk({1: ["A", "B", "C"], 2: ["A", "B"], 3: ["A", "B", "C", "D"]})
    top = m.top_matches(df, sk, {"A", "B"}, min_cover=0.5)
    assert list(top["id"]) == [2, 1, 3] and top.loc[top["id"] == 3, "missing"].iloc[0] == "C, D"
    assert m.top_matches(df, sk, {"Z"}).empty


# ---- тренды и прогноз ----
def _daily(n, f):
    start = pd.Timestamp("2026-08-03")        # понедельник
    return pd.DataFrame({"period": [start + pd.Timedelta(days=i) for i in range(n)], "count": [f(i, (i % 7)) for i in range(n)]})


def test_forecast_follows_weekly_pattern_and_beats_naive():
    daily = _daily(50, lambda i, d: 100 + 2 * i + (30 if d >= 5 else 0))
    res = m.forecast_counts(daily, horizon=14, drop_last=False)
    assert res["ok"] and len(res["forecast"]) == 14
    fc = res["forecast"].set_index("period")["yhat"]
    sat = fc[fc.index.dayofweek == 5].iloc[0]
    tue = fc[fc.index.dayofweek == 1].iloc[0]
    assert sat > tue + 20                                           # выходные выше будней
    assert (res["forecast"]["lo"] <= res["forecast"]["yhat"]).all() and (res["forecast"]["yhat"] <= res["forecast"]["hi"]).all()
    assert res["backtest"]["better_than_naive"] and res["backtest"]["trend"] and res["backtest"]["mae"] < 5


def test_forecast_guards():
    assert not m.forecast_counts(_daily(10, lambda i, d: 5))["ok"]
    assert not m.forecast_counts(pd.DataFrame(columns=["period", "count"]))["ok"]
    flat = m.forecast_counts(_daily(40, lambda i, d: 0), drop_last=False)
    assert flat["ok"] and (flat["forecast"]["yhat"] == 0).all()     # нули не дают ни NaN, ни отрицательных значений


def test_skill_trend():
    base = pd.Timestamp("2026-10-01", tz="UTC")
    rows = [{"id": i + 1, "published_at": base + pd.Timedelta(hours=i % 20)} for i in range(40)]                 # прежний период
    rows += [{"id": i + 41, "published_at": base + pd.Timedelta(days=20, hours=i % 20)} for i in range(40)]      # недавний период
    df = pd.DataFrame(rows)
    sk = skills_df([(i, "Rising", "s") for i in range(41, 71)] + [(i, "Falling", "s") for i in range(1, 31)])
    t = m.skill_trend(df, sk, recent_days=14, min_period=10, min_count=3).set_index("skill")
    assert t.loc["Rising", "delta_pp"] == pytest.approx(75.0) and t.loc["Falling", "delta_pp"] == pytest.approx(-75.0)
    assert t.loc["Rising", "n_recent"] == 30 and t.loc["Rising", "n_prior"] == 0
    assert m.skill_trend(df.head(5), sk).empty and m.skill_trend(df.iloc[0:0], sk).empty
