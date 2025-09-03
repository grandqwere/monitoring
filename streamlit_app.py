from __future__ import annotations

from datetime import datetime, timedelta
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
from core.s3_paths import build_all_key_for  # формируем путь к файлу All/…


st.set_page_config(page_title="Сводные графики электроизмерений", layout="wide")
state.init_once()

# ---------------- Глобальная панель ----------------
ALL_TOKEN = draw_refresh_all()

# ---- Навигация по часам (слева/справа) ----
def _has_current() -> bool:
    return ("current_date" in st.session_state) and ("current_hour" in st.session_state)

nav_delta = 0
nav_left, nav_spacer, nav_right = st.columns([0.25, 0.5, 0.25])
with nav_left:
    if st.button("← Предыдущий час", disabled=not _has_current(), use_container_width=True):
        nav_delta = -1
with nav_right:
    if st.button("Следующий час →", disabled=not _has_current(), use_container_width=True):
        nav_delta = +1

# ---------------- Пикер даты/часа ----------------
st.markdown("### Дата и час (S3)")
picked_date, picked_hour = render_date_hour_picker()

# 1) кликом в пикере устанавливаем «текущий» выбор
if picked_date and picked_hour is not None:
    st.session_state["current_date"] = picked_date
    st.session_state["current_hour"] = picked_hour

# 2) кнопки «пред/след» сдвигают «текущий» выбор на ±1 час
if nav_delta != 0 and _has_current():
    d0 = st.session_state["current_date"]
    h0 = st.session_state["current_hour"]
    dt = datetime(d0.year, d0.month, d0.day, h0) + timedelta(hours=nav_delta)
    st.session_state["current_date"] = dt.date()
    st.session_state["current_hour"] = dt.hour

# если до сих пор нет выбранного часа — подсказываем и выходим
if not _has_current():
    st.info("Выберите день и час.")
    st.stop()

cur_date = st.session_state["current_date"]
cur_hour = st.session_state["current_hour"]

# ---------------- Кэш из двух часов (LRU=2) ----------------
if "hour_cache" not in st.session_state:
    st.session_state["hour_cache"] = {}   # key -> DataFrame
    st.session_state["hour_order"] = []   # список ключей по свежести

def _cache_key(d, h) -> str:
    return f"{d.isoformat()}T{h:02d}"

def _cache_get(d, h):
    k = _cache_key(d, h)
    cache = st.session_state["hour_cache"]
    order = st.session_state["hour_order"]
    if k in cache:
        # освежить порядок
        if k in order:
            order.remove(k)
        order.append(k)
        return cache[k]
    return None

def _cache_put(d, h, df):
    k = _cache_key(d, h)
    cache = st.session_state["hour_cache"]
    order = st.session_state["hour_order"]
    cache[k] = df
    if k in order:
        order.remove(k)
    order.append(k)
    # держим только два последних
    while len(order) > 2:
        old = order.pop(0)
        cache.pop(old, None)

# ---------------- Загрузка текущего часа ----------------
def load_current_df(d, h) -> pd.DataFrame | None:
    df = _cache_get(d, h)
    if df is not None:
        return df
    s3_key = build_all_key_for(d, h)
    try:
        df_raw = read_csv_s3(s3_key)
        df = normalize(df_raw)
        _cache_put(d, h, df)
        st.success(f"Загружено с S3: `{s3_key}`")
        return df
    except Exception as e:
        st.error(f"Файл не найден или не читается: `{s3_key}`. {e}")
        return None

df_current = load_current_df(cur_date, cur_hour)
if df_current is None:
    st.stop()

# ---------------- Дальше — графики ----------------
num_cols = [c for c in df_current.columns if c not in HIDE_ALWAYS and pd.api.types.is_numeric_dtype(df_current[c])]
if not num_cols:
    st.error("Не нашёл числовых колонок для графика.")
    st.stop()

theme_base = st.get_option("theme.base") or "light"

# Сводный график (заголовок + выбор полей/нормирование)
_ = refresh_bar("Сводный график", "main")
default_main = [c for c in DEFAULT_PRESET if c in num_cols] or num_cols[:3]
selected_main, separate_set = render_summary_controls(num_cols, default_main)

fig_main = main_chart(
    df=df_current,
    series=selected_main,
    height=PLOT_HEIGHT,
    theme_base=theme_base,
    separate_axes=set(separate_set),
)
st.plotly_chart(fig_main, use_container_width=True, config={"responsive": True}, key=f"main_{ALL_TOKEN}")

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
