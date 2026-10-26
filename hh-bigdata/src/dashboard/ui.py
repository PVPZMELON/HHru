"""Оформление: CSS (плавное появление, анимации, карточки), заголовок-баннер, KPI-карточки.

Все динамические строки экранируются (`html.escape`): названия навыков и работодателей приходят из
внешних данных и не должны попадать в HTML как разметка. Анимации отключаются при
`prefers-reduced-motion`.
"""
from __future__ import annotations

import html

import streamlit as st

CSS = """
<style>
:root { --c1:#38bdf8; --c2:#6366f1; --c3:#8b5cf6; --edge:rgba(128,128,128,.20); }
html { scroll-behavior: smooth; }
.block-container { padding-top: 2rem; max-width: 1400px; }

@keyframes fadeUp { from { opacity:0; transform: translateY(16px); } to { opacity:1; transform:none; } }
@keyframes wipe   { from { clip-path: inset(0 100% 0 0 round 16px); } to { clip-path: inset(0 0 0 0 round 16px); } }
@keyframes flow   { 0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; } }
@property --num { syntax: "<integer>"; initial-value: 0; inherits: false; }
@keyframes count { from { --num: 0; } to { --num: var(--v); } }

/* баннер страницы */
.hh-hero { background: linear-gradient(120deg,#0ea5e9,#6366f1,#8b5cf6,#0ea5e9); background-size: 300% 300%;
  animation: flow 16s ease infinite, fadeUp .7s ease both; color:#fff; border-radius:20px;
  padding: 1.5rem 1.8rem; margin-bottom: 1.2rem; box-shadow: 0 12px 32px rgba(99,102,241,.28); }
.hh-hero h1 { margin:0; padding:0; font-size:1.9rem; line-height:1.2; color:#fff; letter-spacing:-.01em; }
.hh-hero p  { margin:.4rem 0 0; opacity:.92; font-size:1rem; }

/* KPI-карточки */
.hh-kpis { display:grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap:14px; margin:.2rem 0 1rem; }
.hh-kpi { position:relative; overflow:hidden; border:1px solid var(--edge); border-radius:16px; padding:1rem 1.1rem;
  background: linear-gradient(160deg, rgba(99,102,241,.10), rgba(56,189,248,.05)); animation: fadeUp .7s ease both;
  transition: transform .25s ease, box-shadow .25s ease, border-color .25s ease; }
.hh-kpi::before { content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background: linear-gradient(180deg,var(--c1),var(--c3)); }
.hh-kpi:hover { transform: translateY(-4px); box-shadow: 0 14px 28px rgba(99,102,241,.22); border-color: rgba(99,102,241,.55); }
.hh-kpi .lbl { font-size:.82rem; opacity:.72; text-transform:uppercase; letter-spacing:.06em; }
.hh-kpi .val { font-size:2rem; font-weight:700; line-height:1.25; margin-top:.15rem;
  background: linear-gradient(90deg,var(--c2),var(--c3)); -webkit-background-clip:text; background-clip:text; color:transparent; }
.hh-kpi .sub { font-size:.8rem; opacity:.65; margin-top:.1rem; }
.hh-kpi .cnt { counter-reset: num var(--num); animation: count 1.4s cubic-bezier(.2,.7,.2,1) both; }
.hh-kpi .cnt::after { content: counter(num); }

/* графики и таблицы появляются плавно; графики «прорисовываются» слева направо */
[data-testid="stPlotlyChart"] { animation: fadeUp .7s ease both, wipe 1.2s cubic-bezier(.2,.7,.2,1) both;
  border:1px solid var(--edge); border-radius:16px; padding:.5rem .6rem; transition: box-shadow .25s ease, transform .25s ease; }
[data-testid="stPlotlyChart"]:hover { box-shadow: 0 10px 26px rgba(99,102,241,.16); transform: translateY(-2px); }
[data-testid="stDataFrame"] { animation: fadeUp .8s ease both; border-radius:14px; }
[data-testid="stMetric"] { border:1px solid var(--edge); border-radius:14px; padding:.7rem .9rem; animation: fadeUp .6s ease both;
  background: linear-gradient(160deg, rgba(99,102,241,.07), rgba(56,189,248,.03)); transition: transform .25s ease, box-shadow .25s ease; }
[data-testid="stMetric"]:hover { transform: translateY(-3px); box-shadow: 0 10px 22px rgba(99,102,241,.16); }
[data-testid="stHorizontalBlock"] > div:nth-child(2) [data-testid="stPlotlyChart"] { animation-delay: .12s; }
[data-testid="stHorizontalBlock"] > div:nth-child(3) [data-testid="stPlotlyChart"] { animation-delay: .24s; }
[data-testid="stAlert"] { border-radius:14px; animation: fadeUp .5s ease both; }

/* боковая панель и кнопки */
section[data-testid="stSidebar"] { background: linear-gradient(180deg, rgba(99,102,241,.10), rgba(56,189,248,.05)); }
.stButton > button, .stDownloadButton > button { border-radius: 12px; transition: transform .2s ease, box-shadow .2s ease; }
.stButton > button:hover, .stDownloadButton > button:hover { transform: translateY(-2px); box-shadow: 0 8px 18px rgba(99,102,241,.25); }
button[data-baseweb="tab"] { transition: color .2s ease, background .2s ease; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str = "") -> None:
    sub = f"<p>{html.escape(subtitle)}</p>" if subtitle else ""
    st.markdown(f'<div class="hh-hero"><h1>{html.escape(title)}</h1>{sub}</div>', unsafe_allow_html=True)


def kpi_cards(items: list[dict]) -> None:
    """Ряд KPI-карточек. Элемент: label, text (готовая строка), count (целое для анимированного счётчика,
    необязательно), sub (подпись), hint (подсказка при наведении)."""
    cards = []
    for i, it in enumerate(items):
        count = it.get("count")
        if isinstance(count, int) and 0 <= count < 10_000:
            value = f'<div class="val cnt" style="--v:{count}"></div>'
        else:
            value = f'<div class="val">{html.escape(str(it["text"]))}</div>'
        sub = f'<div class="sub">{html.escape(str(it["sub"]))}</div>' if it.get("sub") else ""
        title = f' title="{html.escape(str(it["hint"]), quote=True)}"' if it.get("hint") else ""
        cards.append(f'<div class="hh-kpi" style="animation-delay:{0.06 * i:.2f}s"{title}>'
                     f'<div class="lbl">{html.escape(str(it["label"]))}</div>{value}{sub}</div>')
    st.markdown(f'<div class="hh-kpis">{"".join(cards)}</div>', unsafe_allow_html=True)
