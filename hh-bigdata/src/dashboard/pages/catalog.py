"""Страница 5. Каталог вакансий: поиск, фильтры, сортировка, пагинация, выгрузка CSV."""
from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from src.dashboard import ui

from src.analytics import queries as q
from src.dashboard.data import cached_facets, get_ctx, synthetic_banner
from src.dashboard.theme import fmt_int, salary_text
from src.db.session import get_engine

EXPORT_LIMIT = 50_000


@st.cache_data(ttl=120, show_spinner=False)
def _count(flt, cq) -> int:
    with get_engine().connect() as conn:
        return q.catalog_count(conn, flt, cq)


@st.cache_data(ttl=120, show_spinner="Загрузка страницы…")
def _page(flt, cq, limit: int, offset: int) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return q.catalog_page(conn, flt, cq, limit, offset)


def _display(df: pd.DataFrame) -> pd.DataFrame:
    """Таблица для показа: зарплата словами, пропуски — «—»."""
    out = pd.DataFrame({
        "Название": df["title"], "Работодатель": df["employer_name"], "Регион": df["region_name"],
        "Направление": df["role_name"], "Опыт": df["experience"], "Занятость": df["employment"],
        "Зарплата": df.apply(salary_text, axis=1),
        "Навыки": df["skills"].replace("", None),
        "Опубликована": pd.to_datetime(df["published_at"], utc=True).dt.strftime("%d.%m.%Y"),
        "Тип данных": df["data_origin"], "Ссылка": df["url"],
    })
    text_cols = [c for c in out.columns if c != "Ссылка"]
    out[text_cols] = out[text_cols].astype("object").where(out[text_cols].notna(), "—")
    return out


def _csv_bytes(flt, cq, total: int) -> bytes:
    """CSV отфильтрованной выборки. Полный текст описаний НЕ выгружается: он принадлежит источнику."""
    with get_engine().connect() as conn:
        df = q.catalog_page(conn, flt, cq, min(total, EXPORT_LIMIT), 0)
    df["Зарплата"] = df.apply(salary_text, axis=1)
    return df.drop(columns=["id"]).to_csv(index=False).encode("utf-8-sig")


def render() -> None:
    ctx = get_ctx()
    ui.hero("Каталог вакансий", "Поиск, фильтры, сортировка и выгрузка")
    synthetic_banner(ctx.df)
    facets = cached_facets()

    c1, c2 = st.columns([2, 3])
    search = c1.text_input("Поиск по названию и описанию", placeholder="например, Python или аналитик")
    skills = c2.multiselect("Навыки (должны быть все выбранные)", facets["skills"], placeholder="Любые")
    c3, c4, c5, c6 = st.columns(4)
    experience = c3.multiselect("Опыт", facets["experience"], placeholder="Любой")
    employment = c4.multiselect("Занятость", facets["employment"], placeholder="Любая")
    salary_min = c5.number_input("Зарплата от, ₽ (верхняя граница не ниже)", min_value=0, value=0, step=10_000,
                                 help="Только вакансии в рублях; учитывается наибольшая известная граница вилки.")
    sort = c6.selectbox("Сортировка", list(q.SORT_OPTIONS))

    cq = q.CatalogQuery(search=search, skills=tuple(skills), experience=tuple(experience), employment=tuple(employment),
                        salary_min_rub=float(salary_min) or None, sort=sort)
    total = _count(ctx.flt, cq)
    if total == 0:
        st.info("Ничего не найдено. Ослабьте фильтры (глобальные — в боковой панели).")
        return

    size = st.selectbox("Строк на странице", [25, 50, 100], index=0)
    pages = max(1, math.ceil(total / size))
    page = st.number_input(f"Страница (из {pages})", min_value=1, max_value=pages, value=1, step=1)
    data = _page(ctx.flt, cq, size, (int(page) - 1) * size)
    st.caption(f"Найдено вакансий: {fmt_int(total)}. Показаны {fmt_int((page - 1) * size + 1)}–{fmt_int((page - 1) * size + len(data))}.")
    st.dataframe(_display(data), hide_index=True,
                 column_config={"Ссылка": st.column_config.LinkColumn("Ссылка", display_text="Открыть")})
    if (data["url"].isna()).any():
        st.caption("«Ссылка» пуста у вакансий без адреса источника (например, синтетических). «—» означает отсутствие значения в данных.")

    with st.expander("Выгрузка в CSV"):
        st.write(f"Будет выгружено до {fmt_int(EXPORT_LIMIT)} вакансий текущей выборки без полного текста описаний "
                 "(описание принадлежит источнику; выгружаются поля для анализа и ссылка на оригинал).")
        if st.checkbox("Подготовить файл"):
            st.download_button("Скачать CSV", data=_csv_bytes(ctx.flt, cq, total), file_name="vacancies_filtered.csv",
                               mime="text/csv")
