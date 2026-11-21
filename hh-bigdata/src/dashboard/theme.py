"""Визуальная система дашборда: палитра NextWave, форматирование чисел и графиков."""
from __future__ import annotations

import math

# Светлая редакционная палитра: графит + лайм, как в выбранном референсе.
ACCENT = "#a9dc43"
ACCENT_2 = "#24363b"
MUTED = "#899596"
BAR_SCALE = [[0.0, "#e5f4c9"], [0.55, "#b8e65c"], [1.0, "#6f9f2d"]]
SEQUENTIAL = [[0.0, "#f4f8ec"], [0.5, "#c8e98b"], [1.0, "#52752a"]]
DONUT_COLORS = ["#b8e65c", "#24363b", "#8fbf45", "#d9edb2", "#718184", "#c5d0c8"]
GRID = "rgba(30,48,52,0.10)"

CURRENCY_SIGNS = {"RUB": "₽", "USD": "$", "EUR": "€", "KZT": "₸", "BYN": "Br"}

ORIGIN_LABELS = {"api": "API hh.ru (реальные данные)", "import": "импортированный датасет",
                 "synthetic": "синтетические демо-данные"}
STATUS_LABELS = {"success": "успешно", "partial": "частично", "failed": "ошибка", "running": "выполняется"}
NBSP = " "


def is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def fmt_int(value) -> str:
    if is_missing(value):
        return "—"
    return f"{int(round(value)):,}".replace(",", NBSP)


def fmt_pct(value, digits: int = 0) -> str:
    if is_missing(value):
        return "—"
    return f"{value * 100:.{digits}f}%".replace(".", ",")


def fmt_money(value, currency: str = "RUB") -> str:
    if is_missing(value):
        return "—"
    return f"{fmt_int(value)}{NBSP}{CURRENCY_SIGNS.get(currency, currency)}"


def salary_text(row) -> str:
    """Человекочитаемая зарплата вакансии с учётом пропусков, односторонних границ и gross/net."""
    kind = row.get("salary_kind")
    if kind == "none" or is_missing(kind):
        return "не указана"
    if kind == "invalid":
        return "некорректна в источнике"
    cur = row.get("salary_currency")
    low, high = row.get("salary_from"), row.get("salary_to")
    sign = CURRENCY_SIGNS.get(cur, cur or "")
    if not is_missing(low) and not is_missing(high):
        text = f"{fmt_int(low)}–{fmt_int(high)} {sign}"
    elif not is_missing(low):
        text = f"от {fmt_int(low)} {sign}"
    else:
        text = f"до {fmt_int(high)} {sign}"
    gross = row.get("salary_gross")
    if gross is True:
        text += " (до налогов)"
    elif gross is False:
        text += " (на руки)"
    return text


def style(fig, height: int = 360, title: str | None = None, legend: bool = False):
    """Единый стиль Plotly: прозрачный фон, нейтральная сетка, лаймовый акцент."""
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=48 if title else 16, b=8),
        transition=dict(duration=500, easing="cubic-in-out"),
        title=dict(text=title, font=dict(size=15, color="#142126"), x=0, xanchor="left") if title else None,
        font=dict(size=13, color="#405054"), showlegend=legend, bargap=0.28,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(font_size=13),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, title_font=dict(size=12), tickfont=dict(color="#68767a"))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, title_font=dict(size=12), tickfont=dict(color="#68767a"))
    return fig
