"""Построители графиков Plotly. Каждая функция принимает DataFrame из аналитического слоя
и возвращает Figure (или None, если данных недостаточно); произвольных чисел в коде нет.

Оформление: градиент «светло-голубой → индиго → фиолетовый» кодирует величину столбца, сетка и оси
нейтральные, значения подписаны на графике, в подсказках — объём выборки.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.dashboard.theme import (ACCENT, ACCENT_2, BAR_SCALE, DONUT_COLORS, MUTED, SEQUENTIAL, fmt_int, fmt_money,
                                 style)

NBSP = " "


def hbar(df: pd.DataFrame, label: str, value: str, title: str, value_title: str,
         height: int | None = None, text: pd.Series | None = None, hover: list[str] | None = None):
    """Горизонтальные столбцы с градиентной заливкой по величине; самые большие значения сверху."""
    data = df.iloc[::-1]  # Plotly рисует снизу вверх
    fig = go.Figure(go.Bar(
        x=data[value], y=data[label], orientation="h",
        marker=dict(color=data[value], colorscale=BAR_SCALE, showscale=False, line=dict(width=0)),
        text=(text.iloc[::-1] if text is not None else data[value].map(fmt_int)),
        textposition="outside", cliponaxis=False,
        customdata=data[hover].to_numpy() if hover else None,
        hovertemplate=("%{y}<br>" + value_title + ": %{x:,.0f}"
                       + ("".join(f"<br>{h}: %{{customdata[{i}]}}" for i, h in enumerate(hover)) if hover else "")
                       + "<extra></extra>"),
    ))
    fig.update_xaxes(title=value_title)
    fig.update_yaxes(title=None, automargin=True)
    return style(fig, height or max(260, 30 * len(data) + 90), title)


def column(df: pd.DataFrame, x: str, y: str, title: str, y_title: str, height: int = 320):
    fig = go.Figure(go.Bar(x=df[x], y=df[y], marker=dict(color=df[y], colorscale=BAR_SCALE, showscale=False),
                           text=df[y].map(fmt_int), textposition="outside", cliponaxis=False,
                           hovertemplate="%{x}<br>" + y_title + ": %{y:,.0f}<extra></extra>"))
    fig.update_xaxes(title=None)
    fig.update_yaxes(title=y_title)
    return style(fig, height, title)


def line(df: pd.DataFrame, x: str, y: str, title: str, y_title: str, height: int = 340, trend_window: int = 7):
    """Площадная линия со сглаживанием; пунктир — скользящее среднее за trend_window точек."""
    fig = go.Figure(go.Scatter(
        x=df[x], y=df[y], mode="lines", name=y_title, line=dict(color=ACCENT, width=2.5, shape="spline", smoothing=0.8),
        fill="tozeroy", fillcolor="rgba(99,102,241,0.14)", hovertemplate="%{y:,.0f}<extra>" + y_title + "</extra>"))
    if len(df) >= trend_window * 2:
        fig.add_trace(go.Scatter(x=df[x], y=df[y].rolling(trend_window, min_periods=1).mean(), mode="lines",
                                 name=f"Среднее за {trend_window} точек", line=dict(color=MUTED, width=2, dash="dot"),
                                 hovertemplate="%{y:,.0f}<extra>среднее</extra>"))
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(title=None)
    fig.update_yaxes(title=y_title, rangemode="tozero")
    return style(fig, height, title, legend=len(df) >= trend_window * 2)


def salary_histogram(values: pd.Series, currency: str, title: str, median: float | None, bins: int = 28):
    """Гистограмма с градиентом по высоте, сглаженной кривой плотности и линией медианы."""
    vals = pd.to_numeric(values, errors="coerce").dropna().to_numpy()
    if len(vals) == 0:
        return None
    counts, edges = np.histogram(vals, bins=min(bins, max(5, len(vals) // 2)))
    centers = (edges[:-1] + edges[1:]) / 2
    width = edges[1] - edges[0]
    smooth = np.convolve(counts, np.array([1, 2, 3, 2, 1]) / 9.0, mode="same")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=centers, y=counts, width=width * 0.94, name="Вакансий",
                         marker=dict(color=counts, colorscale=BAR_SCALE, showscale=False),
                         hovertemplate="%{x:,.0f} " + currency + "<br>Вакансий: %{y}<extra></extra>"))
    fig.add_trace(go.Scatter(x=centers, y=smooth, mode="lines", name="Сглаженно",
                             line=dict(color=ACCENT_2, width=2.5, shape="spline", smoothing=1.0), hoverinfo="skip"))
    if median is not None:
        fig.add_vline(x=median, line_dash="dash", line_color=MUTED,
                      annotation_text=f"медиана {fmt_money(median, currency)}", annotation_position="top")
    fig.update_xaxes(title=f"Середина вилки, {currency}")
    fig.update_yaxes(title="Вакансий")
    return style(fig, 340, title)


def median_bars(summary: pd.DataFrame, label: str, currency: str, title: str, height: int | None = None):
    """Медиана по группам; в подписи — объём выборки, в подсказке — квартили и среднее."""
    data = summary[summary["reliable"]].copy()
    if data.empty:
        return None
    text = data.apply(lambda r: f"{fmt_int(r['median'])} (n={int(r['n'])})", axis=1)
    data["Q1–Q3"] = data.apply(lambda r: f"{fmt_int(r['p25'])}–{fmt_int(r['p75'])}", axis=1)
    data["Среднее"] = data["mean"].map(fmt_int)
    return hbar(data, label, "median", title, f"Медиана, {currency}", height, text=text, hover=["Q1–Q3", "Среднее"])


def skill_diff_bars(df: pd.DataFrame, currency: str, title: str):
    """Разность медиан «с навыком − без навыка»; цвет кодирует только знак."""
    data = df.iloc[::-1]
    colors = [ACCENT if d >= 0 else ACCENT_2 for d in data["diff"]]
    fig = go.Figure(go.Bar(
        x=data["diff"], y=data["skill"], orientation="h", marker_color=colors,
        text=data.apply(lambda r: f"{r['diff']:+,.0f}".replace(",", NBSP) + f" (n={int(r['n'])})", axis=1),
        textposition="outside", cliponaxis=False,
        hovertemplate="%{y}<br>Разность медиан: %{x:,.0f}<extra></extra>"))
    fig.update_xaxes(title=f"Медиана с навыком − медиана без навыка, {currency}")
    fig.update_yaxes(title=None, automargin=True)
    return style(fig, max(260, 30 * len(data) + 90), title)


def scatter_groups(summary: pd.DataFrame, label: str, currency: str, title: str):
    """Пузырьковая диаграмма: вакансии (x), медиана зарплаты (y), размер = число зарплат, цвет = медиана."""
    data = summary[summary["reliable"]]
    if data.empty:
        return None
    fig = px.scatter(data, x="vacancies", y="median", size="n", color="median", hover_name=label,
                     hover_data={"vacancies": ":,.0f", "median": ":,.0f", "n": True},
                     labels={"vacancies": "Вакансий (всего)", "median": f"Медиана, {currency}", "n": "Наблюдений с зарплатой"},
                     color_continuous_scale=BAR_SCALE, size_max=42)
    fig.update_traces(marker=dict(opacity=0.85, line=dict(width=2, color="white")))
    fig.update_coloraxes(showscale=False)
    return style(fig, 400, title)


def two_group_box(with_vals: pd.Series, without_vals: pd.Series, skill: str, currency: str):
    """Скрипичные графики с ящиком: форма распределения и квартили двух групп."""
    fig = go.Figure()
    for vals, name, color in ((with_vals, f"С навыком (n={len(with_vals)})", ACCENT),
                              (without_vals, f"Без навыка (n={len(without_vals)})", MUTED)):
        fig.add_trace(go.Violin(y=vals, name=name, box_visible=True, meanline_visible=True, points=False,
                                line_color=color, fillcolor=color, opacity=0.55))
    fig.update_yaxes(title=f"Середина вилки, {currency}")
    return style(fig, 380, f"Зарплаты вакансий с навыком «{skill}» и без него")


def heatmap(matrix: pd.DataFrame, title: str):
    fig = go.Figure(go.Heatmap(z=matrix.to_numpy(), x=matrix.columns, y=matrix.index, colorscale=SEQUENTIAL,
                               zmin=0, zmax=1, xgap=2, ygap=2, colorbar=dict(title="Жаккар"),
                               hovertemplate="%{y} + %{x}<br>Жаккар: %{z:.2f}<extra></extra>"))
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_xaxes(title=None, tickangle=-45)
    return style(fig, 540, title)


def donut(df: pd.DataFrame, label: str, value: str, title: str, keep: int = 5):
    """Кольцевая диаграмма долей; категории сверх `keep` объединяются в «Другое»."""
    if df.empty:
        return None
    data = df[[label, value]].copy()
    data[label] = data[label].astype(str)
    if len(data) > keep + 1:
        data = pd.concat([data.head(keep), pd.DataFrame({label: ["Другое"], value: [data[value].iloc[keep:].sum()]})])
    fig = go.Figure(go.Pie(labels=data[label], values=data[value], hole=0.6, sort=False,
                           marker=dict(colors=DONUT_COLORS[:len(data)], line=dict(color="white", width=2)),
                           textinfo="percent", textposition="inside",
                           hovertemplate="%{label}<br>%{value} вакансий (%{percent})<extra></extra>"))
    total = int(data[value].sum())
    fig.add_annotation(text=f"<b>{fmt_int(total)}</b><br>вакансий", showarrow=False, font=dict(size=15))
    return style(fig, 340, title, legend=True)


def treemap(df: pd.DataFrame, label: str, value: str, title: str, height: int = 360):
    """Плитки: площадь = число вакансий, цвет — та же шкала."""
    if df.empty:
        return None
    fig = px.treemap(df, path=[px.Constant("Все"), label], values=value, color=value, color_continuous_scale=BAR_SCALE)
    fig.update_traces(root_color="rgba(0,0,0,0)", texttemplate="%{label}<br>%{value}", textfont=dict(size=14),
                      marker=dict(line=dict(width=2, color="white")),
                      hovertemplate="%{label}<br>Вакансий: %{value}<extra></extra>")
    fig.update_coloraxes(showscale=False)
    return style(fig, height, title)


def gauge(value_pct: float | None, title: str):
    """Спидометр для доли (0–100 %)."""
    if value_pct is None:
        return None
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value_pct, number=dict(suffix="%", valueformat=".0f"),
        gauge=dict(axis=dict(range=[0, 100]), bar=dict(color=ACCENT), bgcolor="rgba(128,128,128,0.12)", borderwidth=0)))
    return style(fig, 260, title)


def forecast_chart(history: pd.DataFrame, forecast: pd.DataFrame, title: str, tail: int = 42):
    """История (сплошная линия), прогноз (пунктир) и приближённая полоса неопределённости."""
    hist = history.tail(tail)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=forecast["period"], y=forecast["hi"], mode="lines", line=dict(width=0), hoverinfo="skip",
                             showlegend=False))
    fig.add_trace(go.Scatter(x=forecast["period"], y=forecast["lo"], mode="lines", line=dict(width=0), fill="tonexty",
                             fillcolor="rgba(249,115,22,0.18)", name="Интервал ≈95%", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=hist["period"], y=hist["count"], mode="lines+markers", name="Факт",
                             line=dict(color=ACCENT, width=2.5, shape="spline", smoothing=0.6),
                             marker=dict(size=5, color=ACCENT), hovertemplate="%{x|%d.%m}: %{y:,.0f}<extra>факт</extra>"))
    fig.add_trace(go.Scatter(x=forecast["period"], y=forecast["yhat"], mode="lines+markers", name="Прогноз",
                             line=dict(color=ACCENT_2, width=2.5, dash="dash"), marker=dict(size=5, color=ACCENT_2),
                             hovertemplate="%{x|%d.%m}: %{y:,.0f}<extra>прогноз</extra>"))
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(title="Вакансий в день", rangemode="tozero")
    fig.update_xaxes(title=None)
    return style(fig, 380, title, legend=True)


def trend_bars(df: pd.DataFrame, title: str):
    """Изменение доли вакансий с навыком, п.п.: синий — рост, оранжевый — снижение."""
    if df.empty:
        return None
    data = df.sort_values("delta_pp").reset_index(drop=True)
    colors = [ACCENT if d >= 0 else ACCENT_2 for d in data["delta_pp"]]
    fig = go.Figure(go.Bar(
        x=data["delta_pp"], y=data["skill"], orientation="h", marker_color=colors,
        text=data["delta_pp"].map(lambda v: f"{v:+.1f} п.п."), textposition="outside", cliponaxis=False,
        customdata=data[["share_prior", "share_recent", "n_prior", "n_recent"]].to_numpy(),
        hovertemplate=("%{y}<br>Было: %{customdata[0]:.1%} (n=%{customdata[2]})<br>Стало: %{customdata[1]:.1%} "
                       "(n=%{customdata[3]})<extra></extra>")))
    fig.update_xaxes(title="Изменение доли вакансий с навыком, п.п.")
    fig.update_yaxes(title=None, automargin=True)
    return style(fig, max(260, 32 * len(data) + 90), title)
