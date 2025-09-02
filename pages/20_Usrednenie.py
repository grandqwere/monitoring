from __future__ import annotations

import pandas as pd
import streamlit as st

from core import state
from core.config import GROUPS, HIDE_ALWAYS, TIME_COL
from core.ui import height_controls, series_selector, axis_selector, group_series_selector
from core.plotting import main_chart, group_panel
from core.downsample import resample

st.set_page_config(page_title="Power Monitoring Viewer — Усреднение", layout="wide")
state.init_once()

st.title("Усреднение по времени")

# ---- Навигация (ссылки на страницы) ----
with st.sidebar:
    st.markdown("### Навигация")
    st.page_link("monitoring/streamlit_app.py", label="Часовые данные", icon="📈")
    st.page_link("monitoring/pages/20_Usrednenie.py", label="Усреднение", icon="📊")
    st.markdown("---")

# ---- Проверяем, что данные уже загружены на главной ----
if st.session_state.get("df_current") is None:
    st.info("Сначала откройте главную страницу и загрузите CSV.")
    st.stop()

df = st.session_state["df_current"]
num_cols = [c for c in df.columns if c not in HIDE_ALWAYS and pd.api.types.is_numeric_dtype(df[c])]
if not num_cols:
    st.error("Не нашёл числовых колонок для графика.")
    st.stop()

# ---- Параметры усреднения + высоты графиков ----
with st.sidebar:
    st.markdown("### Параметры усреднения")
    rule_label = st.selectbox("Период", ["1 мин", "5 мин", "15 мин"], index=0)
    rule_map = {"1 мин": "1min", "5 мин": "5min", "15 мин": "15min"}
    rule = rule_map[rule_label]

    agg_label = st.selectbox("Агрегат", ["Среднее", "Максимум", "Минимум", "P95"], index=0)
    agg_map = {"Среднее": "mean", "Максимум": "max", "Минимум": "min", "P95": "p95"}
    agg = agg_map[agg_label]

    main_height, group_height = height_controls()

# ---- Агрегация ----
try:
    df_agg = resample(df, rule=rule, agg=agg)
except Exception as e:
    st.error(f"Ошибка агрегации: {e}")
    st.stop()

# =================== ВЕРХНИЙ ГРАФИК ===================
st.subheader("Главный график (агрегированные данные)")
left, right = st.columns([0.55, 0.45], vertical_alignment="top")

with left:
    selected = series_selector(num_cols)   # выбираем серии по именам исходных колонок

with right:
    axis_map = axis_selector(selected)     # назначаем им A1/A2

fig_main = main_chart(df_agg, selected, axis_map, height=main_height)
st.plotly_chart(fig_main, use_container_width=True)

# =================== НИЖНИЕ ПАНЕЛИ (ГРУППЫ) ===================
st.subheader("Группы (агрегированные)")

# Мощности — две оси
present_power = [c for c in GROUPS["Мощности (общие)"] if c in num_cols]
chosen_power = group_series_selector("(Усредн.) Мощности (общие)", present_power)
fig_power = group_panel(df_agg, chosen_power, height=group_height, two_axes=True)
st.plotly_chart(fig_power, use_container_width=True)

# Остальные — одна ось
for gname in ["Токи L1–L3", "Напряжения фазы", "Линейные U", "PF", "Углы"]:
    present = [c for c in GROUPS[gname] if c in num_cols]
    if not present:
        continue
    chosen = group_series_selector(f"(Усредн.) {gname}", present)
    fig = group_panel(df_agg, chosen, height=group_height, two_axes=False)
    st.plotly_chart(fig, use_container_width=True)
