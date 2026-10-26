"""Страница 3. Анализ навыков."""
from __future__ import annotations

import streamlit as st

from src.analytics import metrics as m
from src.dashboard import charts, ui
from src.dashboard.data import get_ctx, salary_method_note, synthetic_banner
from src.dashboard.theme import fmt_money, fmt_pct


def render() -> None:
    ctx = get_ctx()
    ui.hero("Анализ навыков", "Что востребовано, как навыки связаны с зарплатой и друг с другом")
    synthetic_banner(ctx.df)
    if ctx.df.empty or ctx.skills.empty:
        st.info("По выбранным фильтрам нет вакансий с навыками.")
        return
    st.caption("Фильтры по региону и профессиональному направлению — в боковой панели, они применяются ко всем показателям.")

    only_structured = st.radio("Источник навыков", ["Поле «Ключевые навыки» + упоминания в описании", "Только поле «Ключевые навыки»"],
                               horizontal=True, help="Упоминания в описании находятся словарным поиском по списку технологий "
                                                    "и менее надёжны, чем структурированное поле.") .startswith("Только")
    skills = ctx.skills[ctx.skills["origin"] == "structured"] if only_structured else ctx.skills
    if skills.empty:
        st.info("В выбранном источнике навыков нет.")
        return
    total = len(ctx.df)
    top_n = st.slider("Сколько навыков показать", 5, 40, 20)
    top = m.top_skills(skills, top_n, total)
    st.plotly_chart(charts.hbar(top, "skill", "vacancies", f"Самые востребованные навыки (доля — от {total} вакансий выборки)",
                                "Вакансий", text=top.apply(lambda r: f"{int(r['vacancies'])} ({fmt_pct(r['share'])})", axis=1)))

    st.subheader("Зарплаты с навыком и без него")
    if ctx.basis is None or ctx.pool.empty:
        st.info("Нет сопоставимых зарплат — сравнение недоступно.")
    else:
        st.caption(salary_method_note(ctx))
        choices = top["skill"].tolist()
        skill = st.selectbox("Навык", choices)
        res = m.with_without(ctx.pool, skills, skill, ctx.min_n)
        w, wo = res["with"], res["without"]
        c = st.columns(4)
        c[0].metric("С навыком (n)", w["n"])
        c[1].metric("Медиана с навыком", fmt_money(w["median"], ctx.basis.currency))
        c[2].metric("Без навыка (n)", wo["n"])
        c[3].metric("Медиана без навыка", fmt_money(wo["median"], ctx.basis.currency))
        if not res["enough"]:
            st.warning(f"Недостаточно данных для сравнения: нужно минимум {ctx.min_n} зарплат в каждой группе.")
        else:
            st.write(f"Разность медиан: **{fmt_money(res['diff_median'], ctx.basis.currency)}** "
                     f"(95% бутстреп-интервал: {fmt_money(res['ci_low'], ctx.basis.currency)} … "
                     f"{fmt_money(res['ci_high'], ctx.basis.currency)}).")
            st.caption("Описание различия в выборках, а не доказательство влияния навыка на зарплату.")
            has = set(skills.loc[skills["skill"] == skill, "vacancy_id"])
            mask = ctx.pool["id"].isin(has)
            st.plotly_chart(charts.two_group_box(ctx.pool.loc[mask, "salary_mid"], ctx.pool.loc[~mask, "salary_mid"],
                                                 skill, ctx.basis.currency))

    st.subheader("Таблица навыков")
    table = m.top_skills(skills, 200, total)
    table["share"] = table["share"] * 100
    table = table.rename(columns={"skill": "Навык", "vacancies": "Вакансий", "share": "Доля вакансий, %"})
    if ctx.basis is not None and not ctx.pool.empty:
        ss = m.skill_salary(ctx.pool, skills, ctx.min_n)[["skill", "n", "median"]].rename(
            columns={"skill": "Навык", "n": "Зарплат (n)", "median": f"Медиана, {ctx.basis.currency}"})
        table = table.merge(ss, on="Навык", how="left")
    st.dataframe(table, hide_index=True,
                 column_config={"Доля вакансий, %": st.column_config.NumberColumn(format="%.1f")})
    st.caption("Медиана показана, только если и «с навыком», и «без навыка» набирается минимум нужное число зарплат.")

    st.subheader("Связи навыков")
    k = st.slider("Число навыков в матрице", 5, 25, 15)
    matrix = m.cooccurrence(skills, k)
    if matrix.empty:
        st.info("Недостаточно навыков для матрицы связей.")
    else:
        st.plotly_chart(charts.heatmap(matrix, "Как часто навыки встречаются вместе (коэффициент Жаккара)"))
        st.caption("Жаккар = доля вакансий с обоими навыками среди вакансий, где есть хотя бы один из них. "
                   "Это совместная встречаемость, а не причинная связь.")
