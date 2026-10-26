"""Страница «Прогноз»: прогноз потока публикаций и тренды навыков."""
from __future__ import annotations

import streamlit as st

from src.analytics import metrics as m
from src.dashboard import charts, ui
from src.dashboard.data import get_ctx, synthetic_banner
from src.dashboard.theme import fmt_int


def render() -> None:
    ctx = get_ctx()
    ui.hero("Прогноз и тренды", "Куда движется поток вакансий и какие навыки становятся востребованнее")
    synthetic_banner(ctx.df)
    if ctx.df.empty:
        st.info("По выбранным фильтрам вакансий нет.")
        return

    st.subheader("Прогноз числа публикаций")
    horizon = st.slider("Горизонт прогноза, дней", 7, 28, 14)
    daily = m.dynamics(ctx.df, "D")
    res = m.forecast_counts(daily, horizon=horizon)
    if not res["ok"]:
        st.info(f"Прогноз не строится: {res['reason']}. Данные накапливаются с каждым сбором (`python -m src.pipeline collect`), "
                "а даты публикации в выборке должны охватывать несколько недель.")
    else:
        fc, bt = res["forecast"], res["backtest"]
        last_n = res["history"]["count"].tail(horizon).sum()
        ui.kpi_cards([
            {"label": f"Прогноз на {horizon} дн.", "text": fmt_int(fc["yhat"].sum()), "sub": "публикаций суммарно"},
            {"label": f"Факт за последние {horizon} дн.", "text": fmt_int(last_n)},
            {"label": "Ошибка на проверке", "text": f"{bt['mae']:.1f}", "sub": "MAE, вакансий в день",
             "hint": f"Модель обучена без последних {bt['holdout_days']} дн. и сверена с ними."},
        ])
        st.plotly_chart(charts.forecast_chart(res["history"], fc, "Факт, прогноз и приближённый интервал"))
        if bt["naive_mae"] is not None:
            verdict = "лучше" if bt["better_than_naive"] else "НЕ лучше"
            (st.success if bt["better_than_naive"] else st.warning)(
                f"Проверка на последних {bt['holdout_days']} днях: ошибка модели {bt['mae']:.1f} против {bt['naive_mae']:.1f} "
                f"у наивного прогноза «как неделю назад» — модель {verdict} наивной."
                + ("" if bt["better_than_naive"] else " Прогнозу стоит доверять лишь как ориентиру."))
        st.caption("Модель: недельная сезонность + линейный тренд (включается, если улучшает проверку). Интервал приближённый "
                   "(нормальное приближение остатков). В выборке остаются только актуальные вакансии, поэтому старые дни могут быть "
                   "занижены — это смещает тренд. Прогноз описывает поток публикаций в выборке, а не рынок в целом.")

    st.subheader("Тренды навыков")
    skills = ctx.skills
    trend = m.skill_trend(ctx.df, skills, recent_days=14, top=12)
    if trend.empty:
        st.info("Тренды не строятся: нужно по ≥30 вакансий в каждом из двух последних 14-дневных периодов.")
    else:
        fig = charts.trend_bars(trend, "Как изменилась доля вакансий с навыком: последние 14 дней к предыдущим 14")
        if fig is not None:
            st.plotly_chart(fig)
        st.caption("Сравниваются доли вакансий с навыком в двух соседних периодах (в подсказке — объёмы). "
                   "Небольшие изменения могут быть случайными; это описание выборки, а не предсказание.")
