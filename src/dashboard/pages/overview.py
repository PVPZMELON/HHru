"""Страница 1. Главная аналитическая панель."""
from __future__ import annotations

import streamlit as st

from src.analytics import metrics as m
from src.dashboard import charts, ui
from src.dashboard.data import get_ctx, salary_method_note, synthetic_banner
from src.dashboard.theme import fmt_int, fmt_money, fmt_pct


def render() -> None:
    ctx = get_ctx()
    ui.hero("Обзор рынка вакансий", "Ключевые показатели выбранной выборки: спрос, зарплаты, навыки и динамика публикаций")
    synthetic_banner(ctx.df)
    if ctx.df.empty:
        st.info("По выбранным фильтрам вакансий нет. Измените фильтры или нажмите «Сбросить фильтры».")
        return

    k = m.overview(ctx.df, ctx.skills, ctx.basis)
    currency = ctx.basis.currency if ctx.basis else "RUB"
    ui.kpi_cards([
        {"label": "Вакансии", "text": fmt_int(k["vacancies"]), "count": k["vacancies"], "sub": "в выбранной выборке"},
        {"label": "Работодатели", "text": fmt_int(k["employers"]), "count": k["employers"],
         "sub": "уникальные, без пропусков", "hint": "Уникальные работодатели в выборке (без пропусков)."},
        {"label": "Медианная зарплата", "text": fmt_money(k["median"], currency),
         "sub": f"по {fmt_int(k['comparable'])} вилкам «от–до»", "hint": salary_method_note(ctx)},
        {"label": "Зарплата указана", "text": fmt_pct(k["with_salary_share"]),
         "sub": f"{fmt_int(k['with_salary'])} из {fmt_int(k['vacancies'])}",
         "hint": f"Вилка, «от» или «до». Некорректных значений: {k['invalid_salary']}."},
        {"label": "Топ-навык", "text": k["top_skill"] or "—",
         "sub": f"в {fmt_int(k['top_skill_count'])} вакансиях" if k["top_skill"] else None},
    ])
    st.caption(salary_method_note(ctx))

    freq_label = st.radio("Динамика публикаций", ["По дням", "По неделям"], horizontal=True, label_visibility="collapsed")
    dyn = m.dynamics(ctx.df, "W" if freq_label == "По неделям" else "D")
    if dyn.empty:
        st.info("Нет вакансий с датой публикации — динамика не строится.")
    else:
        st.plotly_chart(charts.line(dyn, "period", "count", f"Опубликовано вакансий ({freq_label.lower()})", "Вакансий"))

    left, right = st.columns(2)
    with left:
        reg = m.distribution(ctx.df, "region_name", top=10)
        st.plotly_chart(charts.hbar(reg, "region_name", "count", "Регионы (топ-10)", "Вакансий"))
    with right:
        roles = m.distribution(ctx.df, "role_name", top=14)
        fig = charts.treemap(roles, "role_name", "count", "Профессиональные направления: площадь = число вакансий",
                             height=max(300, 30 * min(len(reg), 10) + 90))
        if fig is not None:
            st.plotly_chart(fig)

    left, right = st.columns(2)
    with left:
        if ctx.pool.empty:
            st.info("Нет сопоставимых зарплат для гистограммы.")
        else:
            st.plotly_chart(charts.salary_histogram(ctx.pool["salary_mid"], currency,
                                                    f"Распределение зарплат (n={len(ctx.pool)})", k["median"]))
    with right:
        emp = m.distribution(ctx.df, "employment")
        fig = charts.donut(emp, "employment", "count", "Тип занятости")
        if fig is not None:
            st.plotly_chart(fig)

    left, right = st.columns(2)
    with left:
        exp = m.experience_distribution(ctx.df)
        st.plotly_chart(charts.column(exp, "experience", "count", "Требуемый опыт", "Вакансий"))
    with right:
        share = None if k["with_salary_share"] is None else k["with_salary_share"] * 100
        fig = charts.gauge(share, "Прозрачность зарплат: доля вакансий с указанной зарплатой")
        if fig is not None:
            st.plotly_chart(fig)
