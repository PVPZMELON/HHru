"""Страница 2. Анализ зарплат."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.analytics import metrics as m
from src.dashboard import charts, ui
from src.dashboard.data import get_ctx, salary_method_note, synthetic_banner
from src.dashboard.theme import fmt_int, fmt_money


def _summary_table(summary: pd.DataFrame, label: str, title: str) -> pd.DataFrame:
    out = summary.rename(columns={label: title, "vacancies": "Вакансий", "n": "Зарплат (n)", "median": "Медиана",
                                  "mean": "Среднее", "p25": "Q1", "p75": "Q3"})
    out["Доля с зарплатой"] = (summary["salary_share"] * 100).round(0)
    out["Надёжно"] = summary["reliable"].map({True: "да", False: "мало данных"})
    return out[[title, "Вакансий", "Доля с зарплатой", "Зарплат (n)", "Медиана", "Среднее", "Q1", "Q3", "Надёжно"]]


def _group_section(ctx, by: str, title: str, label_ru: str) -> None:
    summary = m.group_summary(ctx.df, ctx.pool, by, ctx.min_n)
    currency = ctx.basis.currency
    fig = charts.median_bars(summary, by, currency, f"Медианная зарплата: {label_ru}")
    if fig is None:
        st.info(f"Ни в одной группе нет минимум {ctx.min_n} зарплат — сравнение не строится. "
                "Уменьшите порог в боковой панели или расширьте выборку.")
    else:
        st.plotly_chart(fig)
    small = int((~summary["reliable"]).sum())
    if small:
        st.caption(f"Скрыто групп с числом зарплат меньше {ctx.min_n}: {small}.")
    st.dataframe(_summary_table(summary, by, title), hide_index=True,
                 column_config={"Доля с зарплатой": st.column_config.NumberColumn(format="%d%%"),
                                "Медиана": st.column_config.NumberColumn(format="%d"),
                                "Среднее": st.column_config.NumberColumn(format="%d"),
                                "Q1": st.column_config.NumberColumn(format="%d"),
                                "Q3": st.column_config.NumberColumn(format="%d")})


def render() -> None:
    ctx = get_ctx()
    ui.hero("Анализ зарплат", "Сопоставимые зарплаты по профессиям, регионам, опыту и навыкам — с объёмом выборки")
    synthetic_banner(ctx.df)
    if ctx.df.empty:
        st.info("По выбранным фильтрам вакансий нет.")
        return
    if ctx.basis is None or ctx.pool.empty:
        st.warning("В выборке нет вакансий с вилкой зарплаты «от–до» в одной валюте — сравнивать нечего. "
                   "Односторонние значения («от X», «до Y») не считаются точной зарплатой.")
        return
    st.caption(salary_method_note(ctx))
    currency = ctx.basis.currency

    tabs = st.tabs(["Распределение", "Профессии", "Регионы", "Опыт", "Навыки", "Вакансии и зарплаты"])

    with tabs[0]:
        stats = m.describe_salary(ctx.pool["salary_mid"])
        c = st.columns(6)
        for col, (name, key) in zip(c, [("n", "n"), ("Среднее", "mean"), ("Медиана", "median"),
                                        ("Q1 (25%)", "p25"), ("Q3 (75%)", "p75"), ("Макс.", "max")]):
            col.metric(name, fmt_int(stats[key]) if key == "n" else fmt_money(stats[key], currency))
        st.plotly_chart(charts.salary_histogram(ctx.pool["salary_mid"], currency,
                                                f"Распределение середин вилок (n={stats['n']})", stats["median"]))
        st.caption("Среднее чувствительно к выбросам, поэтому основным показателем служит медиана; "
                   "Q1–Q3 — межквартильный размах (где лежит половина зарплат).")

    with tabs[1]:
        _group_section(ctx, "role_name", "Направление", "профессиональные направления")
    with tabs[2]:
        _group_section(ctx, "region_name", "Регион", "регионы")
    with tabs[3]:
        summary = m.group_summary(ctx.df, ctx.pool, "experience", ctx.min_n)
        order = {name: i for i, name in enumerate(m.EXPERIENCE_ORDER)}
        summary = summary.assign(_o=summary["experience"].map(lambda v: order.get(v, 99))).sort_values("_o").drop(columns="_o")
        fig = charts.median_bars(summary, "experience", currency, "Медианная зарплата по требуемому опыту")
        if fig is None:
            st.info("Недостаточно данных по группам опыта.")
        else:
            st.plotly_chart(fig)
        st.dataframe(_summary_table(summary, "experience", "Опыт"), hide_index=True)

    with tabs[4]:
        sk = m.skill_salary(ctx.pool, ctx.skills, ctx.min_n)
        if sk.empty:
            st.info(f"Нет навыков, по которым и «с навыком», и «без навыка» набирается {ctx.min_n}+ зарплат.")
        else:
            top = sk.head(15)
            st.plotly_chart(charts.skill_diff_bars(top, currency, "Различие медианных зарплат: с навыком − без навыка"))
            st.caption("Это наблюдаемая ассоциация в выборке, а не эффект навыка: на зарплату влияют опыт, регион, "
                       "роль и другое. В подписях указано число вакансий с навыком (n).")
            table = sk.rename(columns={"skill": "Навык", "n": "С навыком (n)", "median": "Медиана с навыком",
                                       "mean": "Среднее с навыком", "n_without": "Без навыка (n)",
                                       "median_without": "Медиана без навыка", "diff": "Разность медиан"})
            st.dataframe(table, hide_index=True)

    with tabs[5]:
        summary = m.group_summary(ctx.df, ctx.pool, "region_name", ctx.min_n)
        fig = charts.scatter_groups(summary, "region_name", currency, "Регионы: число вакансий и медианная зарплата")
        if fig is None:
            st.info("Недостаточно регионов с достаточным числом зарплат.")
        else:
            st.plotly_chart(fig)
            st.caption("Размер точки — число зарплат, на которых основана медиана.")
