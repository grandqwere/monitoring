from __future__ import annotations

import pandas as pd
import streamlit as st

from core import state
from core.config import GROUPS, HIDE_ALWAYS, TIME_COL, DEFAULT_PRESET, PLOT_HEIGHT
from core.data_io import read_csv_local
from core.prepare import normalize
from core.plotting import main_chart, group_panel
from core.downsample import resample  # для усреднения (радио-переключатель)

st.set_page_config(page_title="Power Monitoring Viewer", layout="wide")
state.init_once()

st.title("Просмотр графиков")

# ---- Боковая панель: загрузка файла ----
with st.sidebar:
    st.markdown("### Загрузите CSV")
    uploaded = st.file_uploader("Файл CSV (1 час = 3600 строк)", type=["csv"])

# ---- Чтение и нормализация ----
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

# ---- Режим (одна страница, без табов): "Часовые" / "Усреднение" ----
if "view_mode" not in st.session_state:
    st.session_state["view_mode"] = "Часовые"

mode = st.radio(
    "Режим данных",
    options=["Часовые", "Усреднение"],
    index=(0 if st.session_state["view_mode"] == "Часовые" else 1),
    horizontal=True,
)
st.session_state["view_mode"] = mode

# Узнаём базовую тему Streamlit для Plotly (light/dark)
theme_base = st.get_option("theme.base") or "light"

# --- Выбор исходного df для графиков ---
if mode == "Часовые":
    df_show = df
else:
    # простые пресеты усреднения, без доп. контролов: 1 мин среднее
    try:
        df_show = resample(df, rule="1min", agg="mean")
    except Exception as e:
        st.error(f"Ошибка усреднения: {e}")
        st.stop()

# =================== ВЕРХНИЙ ГРАФИК ===================
st.subheader("Главный график")
main_series = [c for c in DEFAULT_PRESET if c in num_cols] or num_cols[:3]
fig_main = main_chart(df_show, main_series, height=PLOT_HEIGHT, theme_base=theme_base)
st.plotly_chart(fig_main, use_container_width=True, config={"responsive": True}, key="main")

# =================== НИЖНИЕ ПАНЕЛИ (ГРУППЫ) ===================
st.subheader("Групповые графики (кликайте по легенде, чтобы скрывать/показывать серии)")

# Мощности
present_power = [c for c in GROUPS["Мощности (общие)"] if c in df_show.columns]
if present_power:
    fig_power = group_panel(df_show, present_power, height=PLOT_HEIGHT, theme_base=theme_base)
    st.plotly_chart(fig_power, use_container_width=True, config={"responsive": True}, key="grp_power")

# Остальные группы
order = ["Токи L1–L3", "Напряжения фазы", "Линейные U", "PF", "Углы"]
for i, gname in enumerate(order, start=1):
    present = [c for c in GROUPS[gname] if c in df_show.columns]
    if not present:
        continue
    fig = group_panel(df_show, present, height=PLOT_HEIGHT, theme_base=theme_base)
    st.plotly_chart(fig, use_container_width=True, config={"responsive": True}, key=f"grp_{i}")
