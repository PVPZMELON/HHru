"""Точка входа дашборда: `streamlit run src/dashboard/app.py`."""
from __future__ import annotations

import sys
from pathlib import Path

# Streamlit добавляет в sys.path каталог скрипта; нужен корень проекта для импортов `src.*`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Рынок вакансий hh.ru", page_icon=":material/insights:", layout="wide")

from src.dashboard.data import cached_options, render_sidebar  # noqa: E402
from src.dashboard import ui  # noqa: E402
from src.dashboard.pages import career, catalog, forecast, geography, overview, quality, salaries, skills  # noqa: E402
from src.db.migrate import migrate  # noqa: E402
from src.db.session import check_connection, get_engine, is_sqlite  # noqa: E402
from src.utils.logging_setup import setup_logging  # noqa: E402
from src.config import get_settings  # noqa: E402

setup_logging(get_settings().log_level)

PAGES = [
    st.Page(overview.render, title="Обзор", icon=":material/dashboard:", url_path="overview", default=True),
    st.Page(salaries.render, title="Зарплаты", icon=":material/payments:", url_path="salaries"),
    st.Page(skills.render, title="Навыки", icon=":material/psychology:", url_path="skills"),
    st.Page(geography.render, title="География", icon=":material/location_on:", url_path="geography"),
    st.Page(career.render, title="Что выучить", icon=":material/rocket_launch:", url_path="career"),
    st.Page(forecast.render, title="Прогноз", icon=":material/trending_up:", url_path="forecast"),
    st.Page(catalog.render, title="Каталог вакансий", icon=":material/list_alt:", url_path="catalog"),
    st.Page(quality.render, title="Качество данных", icon=":material/verified:", url_path="quality"),
]


@st.cache_resource(show_spinner=False)
def _ensure_sqlite_schema() -> str:
    """SQLite-файл создаётся автоматически: если схемы нет — применяем миграции (идемпотентно)."""
    try:
        migrate(get_engine())
        return ""
    except Exception as exc:  # noqa: BLE001 — например, файл только для чтения
        return f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"


def _empty_database_page() -> None:
    st.title("Данных пока нет")
    st.info("База пуста. Загрузите данные одной из команд: `python -m src.pipeline demo` (синтетический набор), "
            "`python -m src.pipeline import --file <файл>` или `python -m src.pipeline collect` (нужен доступ к API hh.ru).")
    if is_sqlite(get_engine()):
        st.write("Либо загрузите **синтетический демонстрационный набор** прямо отсюда. Он помечен как «синтетические» "
                 "во всём интерфейсе и не является реальными вакансиями.")
        if st.button("Загрузить синтетический демо-набор (600 записей)"):
            from src.pipeline import load_demo
            with st.spinner("Генерация и загрузка…"):
                summary = load_demo(get_engine(), save_raw=False)
            cached_options.clear()
            st.success(f"Готово: запуск #{summary.run_id}, статус {summary.status}, новых вакансий {summary.inserted}.")
            st.rerun()


def main() -> None:
    ui.inject_css()
    ok, message = check_connection()
    if not ok:
        st.error(f"Нет соединения с БД: {message}")
        st.markdown("Проверьте `.env` (для SQLite — `DB_PATH`; для PostgreSQL — DB_HOST, DB_PORT, DB_NAME, DB_USER, "
                    "DB_PASSWORD, запущена ли база) и применены ли миграции (`python -m src.pipeline migrate`).")
        st.stop()
    if is_sqlite(get_engine()):
        problem = _ensure_sqlite_schema()
        if problem:
            st.error(f"Не удалось подготовить файл SQLite: {problem}")
            st.stop()

    page = st.navigation(PAGES)
    try:
        options = cached_options()
    except Exception as exc:  # таблицы не созданы и т.п.
        st.error(f"База доступна, но схема не готова: {type(exc).__name__}. Выполните `python -m src.pipeline migrate`.")
        st.stop()

    # Страница «Качество данных» полезна и при пустой БД (показывает, что запусков не было)
    if options["total"] == 0 and page.url_path != "quality":
        _empty_database_page()
        st.stop()

    if options["total"] > 0:
        st.session_state["ctx"] = render_sidebar()
    page.run()


main()
