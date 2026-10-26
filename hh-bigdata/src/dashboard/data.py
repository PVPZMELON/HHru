"""Загрузка данных для дашборда (с кэшем) и глобальные фильтры боковой панели."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import streamlit as st

from src.analytics import metrics as m
from src.analytics import queries as q
from src.analytics.filters import Filters
from src.db.session import get_engine
from src.dashboard.theme import ORIGIN_LABELS

CACHE_TTL = 300  # секунд; кнопка «Обновить данные» очищает кэш досрочно


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_options() -> dict:
    with get_engine().connect() as conn:
        return q.filter_options(conn)


@st.cache_data(ttl=CACHE_TTL, show_spinner="Загрузка вакансий из БД…")
def cached_vacancies(flt: Filters) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return q.load_vacancies(conn, flt)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_skills(flt: Filters) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return q.load_vacancy_skills(conn, flt)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_facets() -> dict:
    with get_engine().connect() as conn:
        return q.catalog_facets(conn)


@dataclass
class Context:
    """Всё, что нужно страницам: выборка по глобальным фильтрам и параметры сравнения зарплат."""
    flt: Filters
    options: dict
    df: pd.DataFrame
    skills: pd.DataFrame
    basis: m.SalaryBasis | None
    pool: pd.DataFrame            # сопоставимые зарплаты после (необязательного) исключения выбросов
    outliers_excluded: int
    min_n: int


_FILTER_KEYS = ("f_period", "f_regions", "f_roles", "f_origins", "s_basis", "s_min_n", "s_outliers")


def _reset_filters() -> None:
    for key in _FILTER_KEYS:
        st.session_state.pop(key, None)


def render_sidebar() -> Context:
    """Рисует глобальные фильтры и возвращает контекст. Единый набор фильтров для всех страниц."""
    options = cached_options()
    sb = st.sidebar
    sb.header("Фильтры")

    date_min, date_max = options["date_min"], options["date_max"]
    date_from = date_to = None
    if date_min and date_max:
        period = sb.date_input("Дата публикации", value=(date_min, date_max), min_value=date_min,
                               max_value=date_max, key="f_period", format="DD.MM.YYYY",
                               help="Вакансии без даты публикации при ограничении периода не учитываются.")
        if isinstance(period, (tuple, list)) and len(period) == 2:
            date_from, date_to = period
        # если выбрана только одна дата, диапазон считается незавершённым и не применяется
        if date_from == date_min and date_to == date_max:
            date_from = date_to = None
    regions = sb.multiselect("Регион", options["regions"], key="f_regions", placeholder="Все регионы")
    roles = sb.multiselect("Профессиональное направление", options["roles"], key="f_roles", placeholder="Все направления")
    origins = sb.multiselect("Тип данных", options["origins"], key="f_origins", placeholder="Все типы",
                             format_func=lambda o: ORIGIN_LABELS.get(o, o))
    flt = Filters(date_from=date_from, date_to=date_to, regions=tuple(regions), roles=tuple(roles),
                  origins=tuple(origins))

    df = cached_vacancies(flt)
    skills = cached_skills(flt)

    sb.subheader("Сравнение зарплат")
    bases = m.available_bases(df)
    basis = None
    if not bases.empty:
        labels = {f"{r.currency}, {'gross (до налогов)' if r.gross else 'net (на руки)'} — {r.n} вак.":
                  m.SalaryBasis(str(r.currency), bool(r.gross)) for r in bases.itertuples()}
        choice = sb.selectbox("Валюта и тип зарплаты", list(labels),
                              help="Валюты не конвертируются, gross и net не смешиваются: сравниваются "
                                   "только вакансии с одинаковой основой.")
        basis = labels[choice]
    else:
        sb.caption("В выборке нет вакансий с указанной вилкой «от–до» — сравнение зарплат недоступно.")
    min_n = sb.slider("Минимум наблюдений в группе", 3, 30, m.MIN_GROUP_DEFAULT, key="s_min_n",
                      help="Группы с меньшим числом зарплат не сравниваются.")
    trim = sb.checkbox("Исключить статистические выбросы (3×IQR)", value=False, key="s_outliers",
                       help="Правило Тьюки по середине вилки; по умолчанию выключено.")

    pool = m.salary_pool(df, basis)
    excluded = 0
    if trim:
        pool, excluded = m.exclude_outliers(pool)

    sb.button("Сбросить фильтры", on_click=_reset_filters)
    if sb.button("Обновить данные из БД"):
        st.cache_data.clear()
        st.rerun()
    return Context(flt, options, df, skills, basis, pool, excluded, min_n)


def get_ctx() -> Context:
    return st.session_state["ctx"]


def synthetic_banner(df: pd.DataFrame) -> None:
    """Предупреждение, если в выборке есть синтетические данные."""
    if not df.empty and (df["data_origin"] == "synthetic").any():
        share = (df["data_origin"] == "synthetic").mean()
        st.warning(f"В выборке есть **синтетические демонстрационные данные** ({share:.0%} вакансий). "
                   "Это не реальный рынок труда: закономерности заданы генератором. "
                   "Чтобы работать с реальными данными, загрузите их (см. README) и отфильтруйте «Тип данных».")


def salary_method_note(ctx: Context) -> str:
    if ctx.basis is None:
        return "Сопоставимых зарплат нет."
    extra = f" Исключено выбросов: {ctx.outliers_excluded}." if ctx.outliers_excluded else ""
    return (f"Показатели зарплаты — по вакансиям с вилкой «от–до» ({ctx.basis.label}); значение вакансии = середина "
            f"вилки; в выборке {len(ctx.pool)} таких вакансий.{extra} Вакансии без зарплаты и с «от»/«до» "
            "не входят — выборка может быть смещена.")
