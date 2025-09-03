from __future__ import annotations

from datetime import datetime, timedelta, date as date_cls
import pandas as pd
import streamlit as st

from core import state
from core.config import HIDE_ALWAYS, DEFAULT_PRESET, PLOT_HEIGHT
from core.data_io import read_csv_s3
from core.prepare import normalize
from core.plotting import main_chart
from ui.refresh import draw_refresh_all, refresh_bar
from ui.picker import render_date_hour_picker
from ui.summary import render_summary_controls
from ui.groups import render_group, render_power_group
from core.s3_paths import build_all_key_for

from core.aggregate import aggregate_20s
from core.plotting import daily_main_chart
from ui.day import render_day_picker, day_nav_buttons, shift_day
from ui.summary import daily_overlays_controls


st.set_page_config(page_title="Часовые графики электроизмерений", layout="wide")
state.init_once()

# ---------------- Заголовок и «Обновить всё» ----------------
ALL_TOKEN = draw_refresh_all()
mode_daily = st.toggle("Режим: сутки", value=st.session_state.get("mode_daily", False), key="mode_daily")

# --------- состояние отображаемых часов (макс. 2) ----------
if "loaded_hours" not in st.session_state:
    st.session_state["loaded_hours"] = []          # [(date, hour)]
if "hour_cache" not in st.session_state:
    st.session_state["hour_cache"] = {}            # "YYYY-MM-DDTHH" -> DataFrame

def _key_for(d: date_cls, h: int) -> str:
    return f"{d.isoformat()}T{h:02d}"

def _load_hour(d: date_cls, h: int) -> pd.DataFrame | None:
    k = _key_for(d, h)
    if k in st.session_state["hour_cache"]:
        return st.session_state["hour_cache"][k]
    s3_key = build_all_key_for(d, h)
    try:
        df_raw = read_csv_s3(s3_key)
        df = normalize(df_raw)
        st.session_state["hour_cache"][k] = df
        return df
    except Exception:
        st.info(f"Нет файла за этот час: `{s3_key}`.")
        return None

def _set_only_hour(d: date_cls, h: int) -> bool:
    """Показать только этот час: очищаем всё остальное из памяти."""
    df = _load_hour(d, h)
    if df is None:
        return False
    st.session_state["loaded_hours"] = [(d, h)]
    keep = {_key_for(d, h)}
    st.session_state["hour_cache"] = {k: v for k, v in st.session_state["hour_cache"].items() if k in keep}
    st.session_state["current_date"] = d
    st.session_state["current_hour"] = h
    st.session_state["selected_date"] = d  # чтобы подсветка в пикере соответствовала текущему дню
    return True

def _append_hour(d: date_cls, h: int) -> bool:
    """Добавить час к графику (макс. 2): если уже 2 — выкинуть самый старый."""
    df = _load_hour(d, h)
    if df is None:
        return False
    pair = (d, h)
    lh: list[tuple[date_cls, int]] = st.session_state["loaded_hours"]
    if pair in lh:
        lh.remove(pair)
    lh.append(pair)
    while len(lh) > 2:
        old = lh.pop(0)
        st.session_state["hour_cache"].pop(_key_for(*old), None)
    st.session_state["current_date"], st.session_state["current_hour"] = lh[-1]
    st.session_state["selected_date"] = st.session_state["current_date"]
    return True

def _combined_df() -> pd.DataFrame:
    frames = []
    for d, h in st.session_state["loaded_hours"]:
        k = _key_for(d, h)
        if k in st.session_state["hour_cache"]:
            frames.append(st.session_state["hour_cache"][k])
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).sort_index()

def _has_current() -> bool:
    return ("current_date" in st.session_state) and ("current_hour" in st.session_state)

if mode_daily:
    # ---------- СУТОЧНЫЙ РЕЖИМ ----------
    st.markdown("### День (S3)")
    day = render_day_picker()

    # Навигация днями
    prev_day, next_day = day_nav_buttons(enabled=day is not None)
    if day and prev_day:
        st.session_state["selected_day"] = shift_day(day, -1)
        st.rerun()
    if day and next_day:
        st.session_state["selected_day"] = shift_day(day, +1)
        st.rerun()

    if not day:
        st.info("Выберите дату.")
        st.stop()

    # Собираем 24 часа (без «дозагрузки» в интерфейс — только один день на экране)
    frames = []
    for h in range(24):
        dfh = _load_hour(day, h)  # покажет st.info если файла нет — ок
        if dfh is not None and not dfh.empty:
            frames.append(dfh)

    if not frames:
        st.info("Нет данных за выбранный день.")
        st.stop()

    df_day = pd.concat(frames).sort_index()

    num_cols = [c for c in df_day.columns if c not in HIDE_ALWAYS and pd.api.types.is_numeric_dtype(df_day[c])]
    if not num_cols:
        st.info("Числовые колонки за день не найдены.")
        st.stop()

    theme_base = st.get_option("theme.base") or "light"

    # Контролы как в часах
    token_main = refresh_bar("Суточный сводный график", "daily_main")
    default_main = [c for c in DEFAULT_PRESET if c in num_cols] or num_cols[:3]
    selected_main, separate_set = render_summary_controls(num_cols, default_main)
    show_p95, show_ext = daily_overlays_controls()

    # Агрегация 20с
    agg = aggregate_20s(df_day[num_cols])
    df_mean, df_p95, df_max, df_min = agg["mean"], agg["p95"], agg["max"], agg["min"]

    # Рисуем
    fig_main = daily_main_chart(
        df_mean=df_mean, df_p95=df_p95, df_max=df_max, df_min=df_min,
        series=selected_main, height=PLOT_HEIGHT, theme_base=theme_base,
        separate_axes=set(separate_set), show_p95=show_p95, show_extrema=show_ext,
    )
    st.plotly_chart(
        fig_main, use_container_width=True, config={"responsive": True},
        key=f"daily_main_{ALL_TOKEN}_{token_main}",
    )

    # Нижние панели — показываем усреднённые значения (mean) за 20с, те же группы
    render_power_group(df_mean, PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Токи фаз L1–L3", "daily_grp_curr", df_mean, ["Irms_L1", "Irms_L2", "Irms_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Напряжение (фазное) L1–L3", "daily_grp_urms", df_mean, ["Urms_L1", "Urms_L2", "Urms_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Напряжение (линейное) L1-L2 / L2-L3 / L3-L1", "daily_grp_uline", df_mean, ["U_L1_L2", "U_L2_L3", "U_L3_L1"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Коэффициент мощности (PF)", "daily_grp_pf", df_mean, ["pf_total", "pf_L1", "pf_L2", "pf_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)

    # Частота (если есть)
    freq_cols = [c for c in df_mean.columns
                 if pd.api.types.is_numeric_dtype(df_mean[c]) and (
                     ("freq" in c.lower()) or ("frequency" in c.lower()) or ("hz" in c.lower()) or (c.lower() == "f")
                 )]
    if freq_cols:
        render_group("Частота сети", "daily_grp_freq", df_mean, freq_cols, PLOT_HEIGHT, theme_base, ALL_TOKEN)

    st.stop()


# ---------------- Пикер даты/часа (с подсветкой реальных данных) ----------------
st.markdown("### Дата и час (S3)")
picked_date, picked_hour = render_date_hour_picker()
if picked_date and picked_hour is not None:
    # Нажатие часа — сразу «Показать» (один час) + мгновенная перерисовка, чтобы подсветка обновилась
    if _set_only_hour(picked_date, picked_hour):
        st.rerun()

# ---------------- Кнопки между пикером и графиками ----------------
nav1, nav2, nav3, nav4 = st.columns([0.25, 0.25, 0.25, 0.25])
with nav1:
    show_prev = st.button("Показать предыдущий час", disabled=not _has_current(), use_container_width=True)
with nav2:
    load_prev = st.button("Загрузить предыдущий час", disabled=not _has_current(), use_container_width=True)
with nav3:
    load_next = st.button("Загрузить следующий час", disabled=not _has_current(), use_container_width=True)
with nav4:
    show_next = st.button("Показать следующий час", disabled=not _has_current(), use_container_width=True)

if _has_current():
    base_d = st.session_state["current_date"]
    base_h = st.session_state["current_hour"]
    if show_prev:
        dt = datetime(base_d.year, base_d.month, base_d.day, base_h) + timedelta(hours=-1)
        if _set_only_hour(dt.date(), dt.hour): st.rerun()
    if show_next:
        dt = datetime(base_d.year, base_d.month, base_d.day, base_h) + timedelta(hours=+1)
        if _set_only_hour(dt.date(), dt.hour): st.rerun()
    if load_prev:
        dt = datetime(base_d.year, base_d.month, base_d.day, base_h) + timedelta(hours=-1)
        if _append_hour(dt.date(), dt.hour): st.rerun()
    if load_next:
        dt = datetime(base_d.year, base_d.month, base_d.day, base_h) + timedelta(hours=+1)
        if _append_hour(dt.date(), dt.hour): st.rerun()

# если всё ещё нет данных — подскажем
if not st.session_state["loaded_hours"]:
    st.info("Выберите день и час.")
    st.stop()

# ---------------- Собираем итоговый df и рисуем ----------------
df_current = _combined_df()
if df_current.empty:
    st.info("Нет данных за выбранные час(ы). Попробуйте выбрать другой час.")
    st.stop()

num_cols = [c for c in df_current.columns if c not in HIDE_ALWAYS and pd.api.types.is_numeric_dtype(df_current[c])]
if not num_cols:
    st.error("Не нашёл числовых колонок для графика.")
    st.stop()

theme_base = st.get_option("theme.base") or "light"

# Сводный график
token_main = refresh_bar("Сводный график", "main")
default_main = [c for c in DEFAULT_PRESET if c in num_cols] or num_cols[:3]
selected_main, separate_set = render_summary_controls(num_cols, default_main)

fig_main = main_chart(
    df=df_current,
    series=selected_main,
    height=PLOT_HEIGHT,
    theme_base=theme_base,
    separate_axes=set(separate_set),
)
st.plotly_chart(
    fig_main,
    use_container_width=True,
    config={"responsive": True},
    key=f"main_{ALL_TOKEN}_{token_main}",  # ← токен в ключе
)

# Группы
render_power_group(df_current, PLOT_HEIGHT, theme_base, ALL_TOKEN)
render_group("Токи фаз L1–L3", "grp_curr", df_current, ["Irms_L1", "Irms_L2", "Irms_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
render_group("Напряжение (фазное) L1–L3", "grp_urms", df_current, ["Urms_L1", "Urms_L2", "Urms_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
render_group("Напряжение (линейное) L1-L2 / L2-L3 / L3-L1", "grp_uline", df_current, ["U_L1_L2", "U_L2_L3", "U_L3_L1"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
render_group("Коэффициент мощности (PF)", "grp_pf", df_current, ["pf_total", "pf_L1", "pf_L2", "pf_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)

# Частота
freq_cols = [c for c in df_current.columns
             if pd.api.types.is_numeric_dtype(df_current[c]) and (
                 ("freq" in c.lower()) or ("frequency" in c.lower()) or ("hz" in c.lower()) or (c.lower() == "f")
             )]
if freq_cols:
    render_group("Частота сети", "grp_freq", df_current, freq_cols, PLOT_HEIGHT, theme_base, ALL_TOKEN)
