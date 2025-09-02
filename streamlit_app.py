from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components  # для мини-хака resize

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

# ---- Блок фиксации диапазона времени (сохраняется между режимами) ----
with st.sidebar:
    st.markdown("### 3) Диапазон времени")
    # Инициализация стейта
    if "lock_time" not in st.session_state:
        st.session_state["lock_time"] = False
    # Границы по данным
    min_ts = pd.to_datetime(df.index.min()).to_pydatetime()
    max_ts = pd.to_datetime(df.index.max()).to_pydatetime()
    lock_time = st.checkbox("Фиксировать время на графиках", value=st.session_state["lock_time"])
    st.session_state["lock_time"] = lock_time

    time_range = None
    if lock_time:
        # Берём прошлый интервал, но ограничиваем текущими данными
        prev_start, prev_end = st.session_state.get("time_range", (min_ts, max_ts))
        start_default = max(min_ts, prev_start) if prev_start else min_ts
        end_default   = min(max_ts, prev_end)   if prev_end   else max_ts
        time_range = st.slider(
            "Интервал (по времени оси X)",
            min_value=min_ts, max_value=max_ts,
            value=(start_default, end_default),
            format="HH:mm:ss"
        )
        st.session_state["time_range"] = time_range

# ---- Переключатель режима (радио) ----
if "view_mode" not in st.session_state:
    st.session_state["view_mode"] = "Часовые"

mode = st.radio(
    "Режим просмотра",
    options=["Часовые", "Усреднение"],
    index=(0 if st.session_state["view_mode"] == "Часовые" else 1),
    horizontal=True,
)
st.session_state["view_mode"] = mode  # сохраняем явно

# Мини-скрипт: форсируем событие resize после отрисовки (лечит «белое поле» у Plotly)
def trigger_resize():
    components.html(
        "<script>setTimeout(()=>{window.dispatchEvent(new Event('resize'));}, 60)</script>",
        height=0, width=0
    )

# Применяем фиксированный диапазон времени к фигуре, если он включён
def apply_time_range(fig):
    if st.session_state.get("lock_time") and st.session_state.get("time_range"):
        start, end = st.session_state["time_range"]
        fig.update_xaxes(range=[start, end])

# =================== РЕЖИМ: ЧАСОВЫЕ ===================
if mode == "Часовые":
    st.subheader("Главный график (настраиваемые оси Y)")
    left, right = st.columns([0.55, 0.45], vertical_alignment="top")
    with left:
        selected_raw = series_selector(num_cols, key_prefix="raw_")   # сохраняется в session_state
    with right:
        axis_map_raw = axis_selector(selected_raw, key_prefix="raw_") # сохраняется в session_state

    fig_main_raw = main_chart(df, selected_raw, axis_map_raw, height=main_height)
    apply_time_range(fig_main_raw)
    st.plotly_chart(fig_main_raw, use_container_width=True, key="raw_main", config={"responsive": True})
    trigger_resize()

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
    apply_time_range(fig_power)
    st.plotly_chart(fig_power, use_container_width=True, key="raw_group_power", config={"responsive": True})
    trigger_resize()

    for idx, gname in enumerate(["Токи L1–L3", "Напряжения фазы", "Линейные U", "PF", "Углы"], start=1):
        present = [c for c in GROUPS[gname] if c in num_cols]
        if not present:
            continue
        chosen = group_series_selector(gname, present, key_prefix="raw_")
        fig = group_panel(df, chosen, height=group_height, two_axes=False)
        apply_time_range(fig)
        st.plotly_chart(fig, use_container_width=True, key=f"raw_group_{idx}", config={"responsive": True})
        trigger_resize()

# =================== РЕЖИМ: УСРЕДНЕНИЕ ===================
else:
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
    apply_time_range(fig_main_agg)
    st.plotly_chart(fig_main_agg, use_container_width=True, key="agg_main", config={"responsive": True})
    trigger_resize()

    st.subheader("Группы (агрегированные)")
    present_power = [c for c in GROUPS["Мощности (общие)"] if c in num_cols]
    chosen_power = group_series_selector("(Усредн.) Мощности (общие)", present_power, key_prefix="agg_")
    fig_power = group_panel(df_agg, chosen_power, height=group_height, two_axes=True)
    apply_time_range(fig_power)
    st.plotly_chart(fig_power, use_container_width=True, key="agg_group_power", config={"responsive": True})
    trigger_resize()

    for idx, gname in enumerate(["Токи L1–L3", "Напряжения фазы", "Линейные U", "PF", "Углы"], start=1):
        present = [c for c in GROUPS[gname] if c in num_cols]
        if not present:
            continue
        chosen = group_series_selector(f"(Усредн.) {gname}", present, key_prefix="agg_")
        fig = group_panel(df_agg, chosen, height=group_height, two_axes=False)
        apply_time_range(fig)
        st.plotly_chart(fig, use_container_width=True, key=f"agg_group_{idx}", config={"responsive": True})
        trigger_resize()
