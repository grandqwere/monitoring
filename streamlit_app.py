from __future__ import annotations

import pandas as pd
import streamlit as st

from core import state
from core.config import GROUPS, HIDE_ALWAYS, TIME_COL
from core.data_io import read_csv_local
from core.prepare import normalize
from core.plotting import main_chart, group_panel
from core.ui import height_controls, series_selector, axis_selector, group_series_selector

st.set_page_config(page_title="Power Monitoring Viewer — Часовые", layout="wide")
state.init_once()

st.title("Просмотр графиков — часовые данные")

# ---- Боковая панель: навигация + загрузка + настройки ----
with st.sidebar:
    st.markdown("### Навигация")
    # Надёжные ссылки на страницы (Streamlit 1.22+)
    st.page_link("streamlit_app.py", label="Часовые данные", icon="📈")
    st.page_link("pages/20_Usrednenie.py", label="Усреднение", icon="📊")
    st.markdown("---")

    st.markdown("### 1) Загрузите CSV")
    uploaded = st.file_uploader("Файл CSV (1 час = 3600 строк)", type=["csv"])

    st.markdown("### 2) Настройки")
    main_height, group_height = height_controls()

# ---- Чтение и нормализация данных ----
if not uploaded and st.session_state.get("df_current") is None:
    st.info("Загрузите CSV в боковой панели.")
    st.stop()

if uploaded:
    df_raw = read_csv_local(uploaded)
    df = normalize(df_raw)
    st.session_state["df_current"] = df
else:
    df = st.session_state["df_current"]

# ---- Доступные числовые колонки ----
num_cols = [c for c in df.columns if c not in HIDE_ALWAYS and pd.api.types.is_numeric_dtype(df[c])]
if not num_cols:
    st.error("Не нашёл числовых колонок для графика.")
    st.stop()

# =================== ВЕРХНИЙ ГРАФИК ===================
st.subheader("Главный график (настраиваемые оси Y)")
left, right = st.columns([0.55, 0.45], vertical_alignment="top")

with left:
    selected = series_selector(num_cols)  # multiselect серий

with right:
    axis_map = axis_selector(selected)    # назначение A1/A2

fig_main = main_chart(df, selected, axis_map, height=main_height)
st.plotly_chart(fig_main, use_container_width=True)

# Таблица (по запросу) — первые 50 строк
with st.expander("Первые 50 строк таблицы (по запросу)"):
    tbl = df.copy()
    if TIME_COL in tbl.columns:
        tbl = tbl.drop(columns=[TIME_COL])
    tbl = tbl.reset_index(names=TIME_COL)
    st.dataframe(tbl.head(50), use_container_width=True)

# =================== НИЖНИЕ ПАНЕЛИ (ГРУППЫ) ===================
st.subheader("Групповые графики (стеком)")

# Мощности — с двумя осями (Q на правую)
present_power = [c for c in GROUPS["Мощности (общие)"] if c in num_cols]
chosen_power = group_series_selector("Мощности (общие)", present_power)
fig_power = group_panel(df, chosen_power, height=group_height, two_axes=True)
st.plotly_chart(fig_power, use_container_width=True)

# Остальные группы — одна ось
for gname in ["Токи L1–L3", "Напряжения фазы", "Линейные U", "PF", "Углы"]:
    present = [c for c in GROUPS[gname] if c in num_cols]
    if not present:
        continue
    chosen = group_series_selector(gname, present)
    fig = group_panel(df, chosen, height=group_height, two_axes=False)
    st.plotly_chart(fig, use_container_width=True)
