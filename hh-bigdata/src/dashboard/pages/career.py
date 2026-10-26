"""Страница «Что выучить»: сопоставление ваших навыков с вакансиями и поиск следующего шага."""
from __future__ import annotations

import streamlit as st

from src.analytics import metrics as m
from src.dashboard import charts, ui
from src.dashboard.data import get_ctx, synthetic_banner
from src.dashboard.theme import fmt_int, fmt_money, fmt_pct

MIN_SKILLS_PER_VACANCY = 2


def render() -> None:
    ctx = get_ctx()
    ui.hero("Что выучить", "Отметьте свои навыки — и увидите, сколько вакансий вам уже подходит и какой навык расширит выбор сильнее всего")
    synthetic_banner(ctx.df)
    if ctx.df.empty or ctx.skills.empty:
        st.info("По выбранным фильтрам нет вакансий с навыками. Регион и направление можно уточнить в боковой панели.")
        return

    source = st.radio("Источник навыков вакансий", ["Ключевые навыки + упоминания в описании", "Только ключевые навыки"],
                      horizontal=True, help="Упоминания в описании находятся словарным поиском и менее надёжны.")
    skills = ctx.skills[ctx.skills["origin"] == "structured"] if source.startswith("Только") else ctx.skills
    options = m.top_skills(skills, 80, len(ctx.df))["skill"].tolist()
    if not options:
        st.info("В выбранном источнике навыков нет.")
        return

    c1, c2 = st.columns([3, 2])
    mine = c1.multiselect("Мои навыки", options, placeholder="Выберите навыки, которыми вы владеете")
    cover = c2.slider("Вакансия подходит, если у меня есть не менее … её навыков, %", 40, 100, 60, step=10) / 100
    if not mine:
        st.info("Выберите хотя бы один навык. Подсказка: самые частые — " + ", ".join(options[:6]) + ".")
        return

    summary = m.match_summary(ctx.df, skills, mine, cover, MIN_SKILLS_PER_VACANCY, ctx.pool)
    sal = summary["salary"]
    cur = ctx.basis.currency if ctx.basis else "RUB"
    ui.kpi_cards([
        {"label": "Подходит вакансий", "text": fmt_int(summary["matched"]), "count": summary["matched"],
         "sub": f"из {fmt_int(summary['eligible'])} с ≥{MIN_SKILLS_PER_VACANCY} навыками"},
        {"label": "Доля подходящих", "text": fmt_pct(summary["share"])},
        {"label": "Медиана зарплаты подходящих", "text": fmt_money(sal["median"], cur),
         "sub": f"n={fmt_int(sal['n'])} вилок" if sal["n"] else "нет вилок в этой группе",
         "hint": "Только вакансии с вилкой «от–до» в выбранной основе сравнения (боковая панель)."},
    ])
    if 0 < sal["n"] < ctx.min_n:
        st.caption(f"Зарплат меньше {ctx.min_n} — медиана ненадёжна.")

    st.subheader("Какой навык добавит больше всего вакансий")
    gaps = m.skill_gaps(skills, mine, cover, MIN_SKILLS_PER_VACANCY, top=12)
    if gaps.empty:
        st.success("Дальше сильных «одношаговых» улучшений нет: либо подходит почти всё, либо нужно сразу несколько навыков.")
    else:
        view = gaps.assign(label=gaps["skill"])
        st.plotly_chart(charts.hbar(view, "label", "gain", f"+ вакансий, которые станут подходящими (порог {cover:.0%})",
                                    "Новых подходящих вакансий",
                                    text=view.apply(lambda r: f"+{int(r['gain'])}  (всего вакансий с навыком: {int(r['demand'])})", axis=1)))
        st.caption("Считается для каждого навыка отдельно: сколько сейчас неподходящих вакансий пройдёт порог после добавления "
                   "только этого навыка. Это оценка по выборке, а не гарантия найма.")

    st.subheader("Лучшие подходящие вакансии")
    top = m.top_matches(ctx.df, skills, mine, cover, MIN_SKILLS_PER_VACANCY, top=25)
    if top.empty:
        st.info("Подходящих вакансий нет — снизьте порог или добавьте навыки.")
        return
    table = top.assign(coverage=(top["coverage"] * 100).round(0)).rename(columns={
        "title": "Вакансия", "employer_name": "Работодатель", "region_name": "Регион", "coverage": "Совпадение, %",
        "missing": "Чего не хватает", "url": "Ссылка"}).drop(columns="id")
    table[["Работодатель", "Регион"]] = table[["Работодатель", "Регион"]].astype("object").fillna("—")
    st.dataframe(table, hide_index=True,
                 column_config={"Ссылка": st.column_config.LinkColumn("Ссылка", display_text="Открыть"),
                                "Совпадение, %": st.column_config.NumberColumn(format="%d")})
