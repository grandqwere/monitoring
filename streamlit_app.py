from __future__ import annotations

import pandas as pd
import streamlit as st

from core import state
from core.config import GROUPS, HIDE_ALWAYS, TIME_COL
from core.data_io import read_csv_local
from core.prepare import normalize
from core.plotting import main_chart, group_panel
from core.ui import height_controls, series_selector, axis_selector, group_series_selector
from core.downsample import resample

st.set_page_config(page_title="Power Monitoring Viewer", layout="wide")
state.init_once()

st.title("Просмотр графиков")

# ---- Боковая панель: загрузка + общие настройки ----
with st.sidebar:
    st.markdown("### 1) Загрузите CSV")
    uploaded = st.file_uploader("Файл CSV (1 час = 3600 строк)", type=["csv"])

    st.markdown("### 2) Настройки высоты графиков")
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

# =================== ТАБЫ ===================
tab1, tab2 = st.tabs(["Часовые", "Усреднение"])

# ---------- ТАБ 1: ЧАСОВЫЕ ----------
with tab1:
    st.subheader("Главный график (настраиваемые оси Y)")
    left, right = st.columns([0.55, 0.45], vertical_alignment="top")
    with left:
        selected_raw = series_selector(num_cols, key_prefix="raw_")
    with right:
        axis_map_raw = axis_selector(selected_raw, key_prefix="raw_")

    fig_main_raw = main_chart(df, selected_raw, axis_map_raw, height=main_height)
    st.plotly_chart(fig_main_raw, use_container_width=True)

    with st.expander("Первые 50 строк таблицы (по запросу)"):
        tbl = df.copy()
        if TIME_COL in tbl.columns:
            tbl = tbl.drop(columns=[TIME_COL])
        tbl = tbl.reset_index(names=TIME_COL)
        st.dataframe(tbl.head(50), use_container_width=True)

    st.subheader("Групповые графики (стеком)")
    present_power = [c for c in GROUPS["Мощности (общие)"] if c in num_cols]
    chosen_power = group_series_selector("Мощности (общие)", present_power, key_prefix="raw_")
    fig_power = group_panel(df, chosen_power, height=group_height, two_axes=True)
    st.plotly_chart(fig_power, use_container_width=True)

    for gname in ["Токи L1–L3", "Напряжения фазы", "Линейные U", "PF", "Углы"]:
        present = [c for c in GROUPS[gname] if c in num_cols]
        if not present:
            continue
        chosen = group_series_selector(gname, present, key_prefix="raw_")
        fig = group_panel(df, chosen, height=group_height, two_axes=False)
        st.plotly_chart(fig, use_container_width=True)

# ---------- ТАБ 2: УСРЕДНЕНИЕ ----------
with tab2:
    st.subheader("Параметры усреднения")
    rule_label = st.selectbox("Период", ["1 мин", "5 мин", "15 мин"], index=0, key="agg_rule")
    rule_map = {"1 мин": "1min", "5 мин": "5min", "15 мин": "15min"}
    rule = rule_map[rule_label]

    agg_label = st.selectbox("Агрегат", ["Среднее", "Максимум", "Минимум", "P95"], index=0, key="agg_fn")
    agg_map = {"Среднее": "mean", "Максимум": "max", "Минимум": "min", "P95": "p95"}
    agg = agg_map[agg_label]

    # Агрегация
    try:
        df_agg = resample(df, rule=rule, agg=agg)
    except Exception as e:
        st.error(f"Ошибка агрегации: {e}")
        st.stop()

    st.subheader("Главный график (агрегированные данные)")
    left, right = st.columns([0.55, 0.45], vertical_alignment="top")
    with left:
        selected_agg = series_selector(num_cols, key_prefix="agg_")
    with right:
        axis_map_agg = axis_selector(selected_agg, key_prefix="agg_")

    fig_main_agg = main_chart(df_agg, selected_agg, axis_map_agg, height=main_height)
    st.plotly_chart(fig_main_agg, use_container_width=True)

    st.subheader("Группы (агрегированные)")
    present_power = [c for c in GROUPS["Мощности (общие)"] if c in num_cols]
    chosen_power = group_series_selector("(Усредн.) Мощности (общие)", present_power, key_prefix="agg_")
    fig_power = group_panel(df_agg, chosen_power, height=group_height, two_axes=True)
    st.plotly_chart(fig_power, use_container_width=True)

    for gname in ["Токи L1–L3", "Напряжения фазы", "Линейные U", "PF", "Углы"]:
        present = [c for c in GROUPS[gname] if c in num_cols]
        if not present:
            continue
        chosen = group_series_selector(f"(Усредн.) {gname}", present, key_prefix="agg_")
        fig = group_panel(df_agg, chosen, height=group_height, two_axes=False)
        st.plotly_chart(fig, use_container_width=True)
