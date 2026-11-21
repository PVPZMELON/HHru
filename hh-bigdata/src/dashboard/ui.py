"""Оформление интерфейса HHru: светлая редакционная сетка, графитовый текст и лаймовый акцент.

Динамические строки экранируются через html.escape перед вставкой в HTML.
Анимации отключаются при prefers-reduced-motion.
"""
from __future__ import annotations

import html

import streamlit as st

CSS = """
<style>
:root {
  --hh-ink:#142126; --hh-muted:#68767a; --hh-lime:#c8f169;
  --hh-lime-strong:#a9dc43; --hh-paper:#f5f7f3; --hh-card:#ffffff;
  --hh-edge:#e4e9e2; --hh-dark:#102126;
}
html { scroll-behavior:smooth; }
.stApp { background:var(--hh-paper); color:var(--hh-ink); }
.block-container { max-width:1480px; padding-top:1.45rem; padding-bottom:3rem; }
h1,h2,h3 { color:var(--hh-ink); letter-spacing:-.045em; }
h1 { font-weight:800; } h2 { font-weight:750; }
p,label,[data-testid="stMarkdownContainer"] { color:inherit; }
@keyframes fadeUp { from { opacity:0; transform:translateY(12px); } to { opacity:1; transform:none; } }
.hh-hero {
  position:relative; overflow:hidden; isolation:isolate; color:var(--hh-ink);
  background:var(--hh-card); border:1px solid var(--hh-edge); border-radius:28px;
  padding:clamp(1.5rem,3vw,2.8rem); margin:0 0 1.35rem;
  box-shadow:0 12px 34px rgba(20,33,38,.045); animation:fadeUp .55s ease both;
}
.hh-hero:after {
  content:""; position:absolute; z-index:-1; width:300px; height:300px;
  right:-90px; top:-150px; border-radius:50%;
  background:radial-gradient(circle,rgba(200,241,105,.55),rgba(200,241,105,0) 70%);
}
.hh-hero h1 { margin:0; padding:0; max-width:950px; font-size:clamp(2rem,4vw,3.55rem);
  line-height:1.02; font-weight:850; color:var(--hh-ink); letter-spacing:-.065em; }
.hh-hero p { margin:.85rem 0 0; max-width:760px; color:var(--hh-muted); font-size:1rem; line-height:1.55; }
.hh-kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(185px,1fr)); gap:13px; margin:.35rem 0 1.35rem; }
.hh-kpi { position:relative; overflow:hidden; min-height:118px; padding:1.05rem 1.15rem;
  border:1px solid var(--hh-edge); border-radius:20px; background:var(--hh-card);
  animation:fadeUp .55s ease both; transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease; }
.hh-kpi:before { content:""; position:absolute; left:0; top:0; width:100%; height:4px; background:var(--hh-lime); }
.hh-kpi:hover { transform:translateY(-3px); border-color:#c7d9a5; box-shadow:0 12px 26px rgba(20,33,38,.07); }
.hh-kpi .lbl { color:var(--hh-muted); font-size:.76rem; font-weight:700; letter-spacing:.075em; text-transform:uppercase; }
.hh-kpi .val { margin-top:.5rem; color:var(--hh-ink); font-size:clamp(1.55rem,2.5vw,2.15rem); font-weight:850; line-height:1.1; letter-spacing:-.055em; }
.hh-kpi .sub { margin-top:.4rem; color:var(--hh-muted); font-size:.82rem; }
[data-testid="stPlotlyChart"] { background:var(--hh-card); border:1px solid var(--hh-edge); border-radius:20px;
  padding:.55rem .65rem; animation:fadeUp .55s ease both; transition:box-shadow .2s ease,transform .2s ease; }
[data-testid="stPlotlyChart"]:hover { box-shadow:0 10px 24px rgba(20,33,38,.06); transform:translateY(-2px); }
[data-testid="stDataFrame"],[data-testid="stTable"] { border:1px solid var(--hh-edge); border-radius:16px; overflow:hidden; }
[data-testid="stMetric"] { background:var(--hh-card); border:1px solid var(--hh-edge); border-radius:16px; padding:.8rem 1rem; }
[data-testid="stMetricLabel"] { color:var(--hh-muted); }
[data-testid="stMetricValue"] { color:var(--hh-ink); font-weight:800; letter-spacing:-.04em; }
[data-testid="stAlert"] { border-radius:15px; } hr { border-color:var(--hh-edge); }
section[data-testid="stSidebar"] { background:#eef2eb; border-right:1px solid var(--hh-edge); }
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color:var(--hh-muted); }
section[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] { border-radius:12px; margin:.12rem 0; }
section[data-testid="stSidebar"] [aria-current="page"] { background:var(--hh-lime) !important; color:var(--hh-ink) !important; font-weight:750; }
.stButton > button,.stDownloadButton > button { border-radius:999px; border:1px solid var(--hh-ink); min-height:2.65rem;
  font-weight:700; transition:transform .18s ease,box-shadow .18s ease,background .18s ease; }
.stButton > button[kind="primary"] { background:var(--hh-lime); color:var(--hh-ink); border-color:var(--hh-lime); }
.stButton > button:hover,.stDownloadButton > button:hover { transform:translateY(-2px); box-shadow:0 8px 18px rgba(20,33,38,.12); }
button[data-baseweb="tab"] { border-radius:999px; }
[data-baseweb="tab"][aria-selected="true"] { background:var(--hh-lime); }
input,textarea,[data-baseweb="select"] > div { border-radius:12px !important; }
@media (max-width:700px) {
 .block-container { padding-left:1rem; padding-right:1rem; }
 .hh-hero { border-radius:20px; }
 .hh-kpis { grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px; }
 .hh-kpi { min-height:105px; padding:.85rem; border-radius:16px; }
}
@media (prefers-reduced-motion:reduce) {
 *,*::before,*::after { animation:none !important; transition:none !important; scroll-behavior:auto !important; }
}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str = "") -> None:
    sub = f"<p>{html.escape(subtitle)}</p>" if subtitle else ""
    st.markdown(f'<div class="hh-hero"><h1>{html.escape(title)}</h1>{sub}</div>', unsafe_allow_html=True)


def kpi_cards(items: list[dict]) -> None:
    """Ряд KPI-карточек. Элемент: label, text, необязательные count, sub и hint."""
    cards = []
    for i, it in enumerate(items):
        value = f'<div class="val">{html.escape(str(it.get("text", "—")))}</div>'
        sub = f'<div class="sub">{html.escape(str(it["sub"]))}</div>' if it.get("sub") else ""
        title = f' title="{html.escape(str(it["hint"]), quote=True)}"' if it.get("hint") else ""
        cards.append(f'<div class="hh-kpi" style="animation-delay:{0.05 * i:.2f}s"{title}>'
                     f'<div class="lbl">{html.escape(str(it["label"]))}</div>{value}{sub}</div>')
    st.markdown(f'<div class="hh-kpis">{"".join(cards)}</div>', unsafe_allow_html=True)
