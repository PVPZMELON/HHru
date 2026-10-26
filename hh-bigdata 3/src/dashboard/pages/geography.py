"""Страница 4. География рынка труда.

Карта не строится: в данных нет координат и геометрий регионов, а подставлять сторонние
границы без проверки соответствия названий было бы некорректно. Используются горизонтальные диаграммы.
"""
from __future__ import annotations

import streamlit as st

from src.analytics import metrics as m
from src.dashboard import charts, ui
from src.dashboard.data import get_ctx, salary_method_note, synthetic_banner
from src.dashboard.theme import fmt_pct


def render() -> None:
    ctx = get_ctx()
    ui.hero("География рынка труда", "Где больше вакансий и как различаются зарплаты по регионам")
    synthetic_banner(ctx.df)
    if ctx.df.empty:
        st.info("По выбранным фильтрам вакансий нет.")
        return
    st.caption("Регионы приведены так, как они указаны в вакансиях; карта не строится, так как в данных нет геокоординат.")

    top_n = st.slider("Сколько регионов показать", 5, 30, 15)
    reg = m.distribution(ctx.df, "region_name", top=top_n)
    st.plotly_chart(charts.hbar(reg, "region_name", "count", f"Вакансии по регионам (топ-{top_n})", "Вакансий",
                                text=reg.apply(lambda r: f"{int(r['count'])} ({fmt_pct(r['share'])})", axis=1)))

    st.subheader("Зарплаты по регионам")
    if ctx.basis is None or ctx.pool.empty:
        st.info("Нет сопоставимых зарплат для сравнения регионов.")
    else:
        st.caption(salary_method_note(ctx))
        summary = m.group_summary(ctx.df, ctx.pool, "region_name", ctx.min_n)
        fig = charts.median_bars(summary, "region_name", ctx.basis.currency,
                                 f"Медианная зарплата по регионам (группы от {ctx.min_n} зарплат)")
        if fig is None:
            st.info(f"Ни в одном регионе нет {ctx.min_n}+ зарплат.")
        else:
            st.plotly_chart(fig)
        table = summary.rename(columns={"region_name": "Регион", "vacancies": "Вакансий", "n": "Зарплат (n)",
                                        "median": f"Медиана, {ctx.basis.currency}"})
        table["Доля с зарплатой, %"] = (summary["salary_share"] * 100).round(0)
        table["Надёжно"] = summary["reliable"].map({True: "да", False: "мало данных"})
        st.dataframe(table[["Регион", "Вакансий", "Доля с зарплатой, %", "Зарплат (n)", f"Медиана, {ctx.basis.currency}", "Надёжно"]],
                     hide_index=True)

    st.subheader("Востребованные профессиональные направления")
    roles = m.distribution(ctx.df, "role_name", top=15)
    st.plotly_chart(charts.hbar(roles, "role_name", "count", "Направления по числу вакансий", "Вакансий"))
