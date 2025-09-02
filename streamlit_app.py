from __future__ import annotations

import pandas as pd
import streamlit as st

from core import state
from core.config import GROUPS, HIDE_ALWAYS, TIME_COL, DEFAULT_PRESET, PLOT_HEIGHT
from core.data_io import read_csv_local
from core.prepare import normalize
from core.plotting import main_chart, group_panel

st.set_page_config(page_title="Power Monitoring Viewer", layout="wide")
state.init_once()

st.title("Сводные графики электроизмерений")

# ---- Боковая панель: загрузка ----
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

# Определяем тему Streamlit для Plotly
theme_base = st.get_option("theme.base") or "light"

# =================== СВОДНЫЙ ГРАФИК ===================
st.subheader("Сводный график")
default_main = [c for c in DEFAULT_PRESET if c in num_cols] or num_cols[:3]
selected_main = st.multiselect(
    "Поля для сводного графика",
    options=num_cols,
    default=default_main,
)
fig_main = main_chart(df, selected_main, height=PLOT_HEIGHT, theme_base=theme_base)
st.plotly_chart(fig_main, use_container_width=True, config={"responsive": True}, key="main")

# =================== ГРУППЫ (без чекбоксов, названия «по-электрически») ===================

# 1) Мощности: активная/полная/реактивная
st.subheader("Мощность: активная / полная / реактивная")
present_power = ["P_total", "S_total", "Q_total"]
fig_power = group_panel(df, present_power, height=PLOT_HEIGHT, theme_base=theme_base)
st.plotly_chart(fig_power, use_container_width=True, config={"responsive": True}, key="grp_power")

# 2) Токи фаз L1–L3
st.subheader("Токи фаз L1–L3")
present_curr = ["Irms_L1", "Irms_L2", "Irms_L3"]
fig_curr = group_panel(df, present_curr, height=PLOT_HEIGHT, theme_base=theme_base)
st.plotly_chart(fig_curr, use_container_width=True, config={"responsive": True}, key="grp_curr")

# 3) Напряжение фазное L1–L3
st.subheader("Напряжение (фазное) L1–L3")
present_urms = ["Urms_L1", "Urms_L2", "Urms_L3"]
fig_urms = group_panel(df, present_urms, height=PLOT_HEIGHT, theme_base=theme_base)
st.plotly_chart(fig_urms, use_container_width=True, config={"responsive": True}, key="grp_urms")

# 4) Напряжение линейное L12 / L23 / L31
st.subheader("Напряжение (линейное) L12 / L23 / L31")
present_uline = ["U_L1_L2", "U_L2_L3", "U_L3_L1"]
fig_uline = group_panel(df, present_uline, height=PLOT_HEIGHT, theme_base=theme_base)
st.plotly_chart(fig_uline, use_container_width=True, config={"responsive": True}, key="grp_uline")

# 5) Коэффициент мощности (PF)
st.subheader("Коэффициент мощности (PF)")
present_pf = ["pf_total", "pf_L1", "pf_L2", "pf_L3"]
fig_pf = group_panel(df, present_pf, height=PLOT_HEIGHT, theme_base=theme_base)
st.plotly_chart(fig_pf, use_container_width=True, config={"responsive": True}, key="grp_pf")

# 6) Углы между фазами
st.subheader("Фазовые углы (между линиями)")
present_ang = ["angle_L1_L2", "angle_L2_L3", "angle_L3_L1"]
fig_ang = group_panel(df, present_ang, height=PLOT_HEIGHT, theme_base=theme_base)
st.plotly_chart(fig_ang, use_container_width=True, config={"responsive": True}, key="grp_ang")
