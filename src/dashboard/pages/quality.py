"""Страница 6. Качество данных и состояние конвейера (не зависит от глобальных фильтров)."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from src.analytics import queries as q
from src.dashboard import charts, ui
from src.dashboard.theme import ORIGIN_LABELS, STATUS_LABELS, fmt_int
from src.db.session import get_engine


@st.cache_data(ttl=60, show_spinner=False)
def _load() -> dict:
    with get_engine().connect() as conn:
        history = q.etl_history(conn, 50)
        issues = q.run_issue_summary(conn, int(history["id"].iloc[0])) if not history.empty else pd.DataFrame()
        return {"history": history, "issues": issues, "missing": q.table_missing_stats(conn),
                "sources": q.data_sources(conn)}


def render() -> None:
    ui.hero("Качество данных и конвейер", "История запусков ETL, пропуски и ошибки — только фактическое состояние")
    st.caption("Страница показывает всю таблицу вакансий и фактическую историю запусков ETL; глобальные фильтры не применяются.")
    d = _load()
    history, missing, sources = d["history"], d["missing"], d["sources"]

    if history.empty:
        st.warning("Запусков ETL ещё не было: данные не загружались. Выполните `python -m src.pipeline demo` "
                   "или `python -m src.pipeline collect` / `import` (см. README).")
    else:
        last = history.iloc[0]
        successes = history[history["status"].isin(["success", "partial"])]
        c = st.columns(4)
        c[0].metric("Вакансий в БД", fmt_int(int(sources["vacancies"].sum()) if not sources.empty else 0))
        c[1].metric("Последний запуск", STATUS_LABELS.get(last["status"], last["status"]))
        if successes.empty:
            c[2].metric("Последний успешный сбор", "нет")
        else:
            finished = successes.iloc[0]["finished_at"]
            age = datetime.now(timezone.utc) - pd.Timestamp(finished).to_pydatetime()
            hours = age.total_seconds() / 3600
            c[2].metric("Последний успешный сбор", pd.Timestamp(finished).strftime("%d.%m.%Y %H:%M"),
                        help=f"Прошло {hours:.1f} ч." if hours < 72 else f"Прошло {hours / 24:.1f} сут. — данные могли устареть.")
        c[3].metric("Тип данных последнего запуска", ORIGIN_LABELS.get(last["data_origin"], last["data_origin"]))

        st.subheader(f"Последний запуск #{int(last['id'])}")
        c = st.columns(6)
        for col, (name, key) in zip(c, [("Получено", "fetched_count"), ("Валидных", "valid_count"),
                                        ("Новых", "inserted_count"), ("Обновлено", "updated_count"),
                                        ("Без изменений", "unchanged_count"), ("Дублей удалено", "duplicates_removed")]):
            col.metric(name, fmt_int(last[key]))
        st.write(f"Отклонено записей (нет id/названия): **{fmt_int(last['rejected_count'])}**. Источник: {last['source_description']}.")
        if last["status"] == "running":
            st.info("Запуск ещё выполняется или был прерван до записи итога.")
        if isinstance(last["error_message"], str) and last["error_message"]:
            st.error(f"Сообщения об ошибках последнего запуска: {last['error_message']}")
        issues = d["issues"]
        if not issues.empty:
            st.dataframe(issues.rename(columns={"issue_type": "Тип проблемы", "n": "Записей"}), hide_index=True)
        else:
            st.caption("Проблем качества в последнем запуске не зафиксировано.")

    st.subheader("Пропуски в таблице вакансий")
    if missing.empty or missing["Пропусков"].sum() == 0 and sources.empty:
        st.info("В таблице вакансий пока нет данных.")
    else:
        view = missing.sort_values("Доля", ascending=False)
        st.plotly_chart(charts.hbar(view.assign(**{"Доля, %": (view["Доля"] * 100).round(1)}), "Поле", "Доля, %",
                                    "Доля записей с пропуском или проблемой, %", "Доля, %"))
        st.caption("«Зарплата не указана» — обычная ситуация для hh.ru, а не ошибка данных; "
                   "«некорректна» — значения, отвергнутые правилами нормализации.")

    st.subheader("Источники данных")
    if sources.empty:
        st.info("Данных нет.")
    else:
        view = sources.assign(data_origin=sources["data_origin"].map(lambda o: ORIGIN_LABELS.get(o, o)))
        st.dataframe(view.rename(columns={"data_origin": "Тип данных", "vacancies": "Вакансий",
                                          "first_loaded": "Впервые загружены", "last_seen": "Последний раз видели"}),
                     hide_index=True)

    st.subheader("История запусков ETL")
    if history.empty:
        st.caption("История пуста.")
    else:
        view = history.assign(status=history["status"].map(lambda s: STATUS_LABELS.get(s, s)),
                              data_origin=history["data_origin"].map(lambda o: ORIGIN_LABELS.get(o, o)))
        st.dataframe(view.rename(columns={
            "id": "№", "started_at": "Начат", "finished_at": "Завершён", "status": "Статус", "data_origin": "Тип данных",
            "source_description": "Источник", "fetched_count": "Получено", "valid_count": "Валидных",
            "rejected_count": "Отклонено", "duplicates_removed": "Дублей", "inserted_count": "Новых",
            "updated_count": "Обновлено", "unchanged_count": "Без изменений", "error_message": "Ошибки"}),
            hide_index=True)
