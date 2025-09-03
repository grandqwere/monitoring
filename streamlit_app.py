from __future__ import annotations

import pandas as pd
import streamlit as st

from core import state
from core.config import HIDE_ALWAYS, DEFAULT_PRESET, PLOT_HEIGHT
from core.data_io import read_csv_local, s3_build_index, read_csv_s3
from core.data_io import build_availability  # если нужно где-то ещё
from core.prepare import normalize
from core.plotting import main_chart
from ui.refresh import draw_refresh_all
from ui.calendar import render_calendar_and_pick
from ui.summary import render_summary_controls
from ui.groups import render_group, render_power_group

st.set_page_config(page_title="Сводные графики электроизмерений", layout="wide")
state.init_once()

ALL_TOKEN = draw_refresh_all()

# Сайдбар: локальная загрузка (запасной вариант)
with st.sidebar:
    st.markdown("### Загрузите CSV (локально)")
    uploaded = st.file_uploader("Файл CSV (1 час = 3600 строк)", type=["csv"])

df_local = None
if uploaded:
    df_local = normalize(read_csv_local(uploaded))

# Индексация S3
try:
    index_df = s3_build_index(cache_buster=ALL_TOKEN)
except Exception as e:
    st.warning(f"Не удалось подключиться к S3: {e}")
    index_df = pd.DataFrame(columns=["key", "dt", "date", "hour"])

# Календарь выбора часа
st.markdown("### Выбор времени (S3)")
selected_day, chosen_key = render_calendar_and_pick(index_df, cache_buster=ALL_TOKEN)

# Получаем текущий DataFrame: либо S3-час, либо локальный запасной файл
df_current = None
if chosen_key:
    try:
        df_current = normalize(read_csv_s3(chosen_key))
        st.success(f"Загружено с S3: `{chosen_key}`")
    except Exception as e:
        st.error(f"Ошибка чтения с S3: {e}")
elif df_local is not None:
    df_current = df_local

if df_current is None:
    st.stop()

# Числовые колонки
num_cols = [c for c in df_current.columns if c not in HIDE_ALWAYS and pd.api.types.is_numeric_dtype(df_current[c])]
if not num_cols:
    st.error("Не нашёл числовых колонок для графика.")
    st.stop()

theme_base = st.get_option("theme.base") or "light"

# ------ Сводный график ------ #
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

# ------ Группы ------ #
render_power_group(df_current, PLOT_HEIGHT, theme_base, ALL_TOKEN)
render_group("Токи фаз L1–L3", "grp_curr", df_current, ["Irms_L1", "Irms_L2", "Irms_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
render_group("Напряжение (фазное) L1–L3", "grp_urms", df_current, ["Urms_L1", "Urms_L2", "Urms_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
render_group("Напряжение (линейное) L1-L2 / L2-L3 / L3-L1", "grp_uline", df_current, ["U_L1_L2", "U_L2_L3", "U_L3_L1"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
render_group("Коэффициент мощности (PF)", "grp_pf", df_current, ["pf_total", "pf_L1", "pf_L2", "pf_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
# Частота — автоматический поиск
freq_cols = [c for c in df_current.columns if pd.api.types.is_numeric_dtype(df_current[c]) and any(x in c.lower() for x in ["freq","frequency","hz"]) or c.lower()=="f"]
if freq_cols:
    render_group("Частота сети", "grp_freq", df_current, freq_cols, PLOT_HEIGHT, theme_base, ALL_TOKEN)
