from __future__ import annotations

import pandas as pd
import streamlit as st

from core import state
from core.config import HIDE_ALWAYS, DEFAULT_PRESET, PLOT_HEIGHT
from core.data_io import read_csv_local
from core.prepare import normalize
from core.plotting import main_chart, group_panel

st.set_page_config(page_title="Сводные графики электроизмерений", layout="wide")
state.init_once()

st.title("Сводные графики электроизмерений")

# ------- вспомогательное: кнопка «Обновить» для конкретного графика -------
def refresh_bar(title: str, name: str) -> int:
    """
    Рисует заголовок + кнопку «↻ Обновить» справа.
    Возвращает текущий refresh-счётчик (int) для включения в key графика.
    """
    key = f"refresh_{name}"
    if key not in st.session_state:
        st.session_state[key] = 0

    left, right = st.columns([0.85, 0.15])
    with left:
        st.subheader(title)
    with right:
        if st.button("↻ Обновить", key=f"btn_{name}"):
            st.session_state[key] += 1
    return st.session_state[key]
# ---------------------------------------------------------------------------

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

# Тема Streamlit (для шаблона/палитры Plotly)
theme_base = st.get_option("theme.base") or "light"

# =================== СВОДНЫЙ ГРАФИК ===================
token_main = refresh_bar("Сводный график", "main")

default_main = [c for c in DEFAULT_PRESET if c in num_cols] or num_cols[:3]
selected_main = st.multiselect(
    "Поля для сводного графика",
    options=num_cols,
    default=default_main,
    key="main_fields",
)

st.markdown("**Нормирование шкалы** (отдельные шкалы слева для отмеченных трендов):")
separate_set = set()
max_allowed = max(0, len(selected_main) - 1)
checked_count = 0

# почистим старые ключи чекбоксов, которых больше нет
for k in list(st.session_state.keys()):
    if k.startswith("norm_"):
        col = k[5:]
        if col not in selected_main:
            del st.session_state[k]

for c in selected_main:
    prev_val = bool(st.session_state.get(f"norm_{c}", False))
    disabled = (checked_count >= max_allowed) and (not prev_val)
    val = st.checkbox(c, value=prev_val, key=f"norm_{c}", disabled=disabled)
    if val:
        separate_set.add(c)
        checked_count += 1

# гарантия: хотя бы одна серия остаётся на базовой оси
if len(separate_set) >= len(selected_main) and selected_main:
    last = selected_main[-1]
    if last in separate_set:
        separate_set.remove(last)
        st.session_state[f"norm_{last}"] = False

fig_main = main_chart(
    df=df,
    series=selected_main,
    height=PLOT_HEIGHT,
    theme_base=theme_base,
    separate_axes=separate_set,
)
st.plotly_chart(
    fig_main,
    use_container_width=True,
    config={"responsive": True},
    key=f"main_{token_main}",
)

# =================== ГРУППЫ ===================

# 1) Мощность: активная / полная / реактивная
token_p = refresh_bar("Мощность: активная / полная / реактивная", "grp_power")
present_power = [c for c in ["P_total", "S_total", "Q_total"] if c in df.columns]
fig_power = group_panel(df, present_power, height=PLOT_HEIGHT, theme_base=theme_base)
st.plotly_chart(fig_power, use_container_width=True, config={"responsive": True}, key=f"grp_power_{token_p}")

# 2) Токи фаз L1–L3
token_c = refresh_bar("Токи фаз L1–L3", "grp_curr")
present_curr = [c for c in ["Irms_L1", "Irms_L2", "Irms_L3"] if c in df.columns]
fig_curr = group_panel(df, present_curr, height=PLOT_HEIGHT, theme_base=theme_base)
st.plotly_chart(fig_curr, use_container_width=True, config={"responsive": True}, key=f"grp_curr_{token_c}")

# 3) Напряжение (фазное) L1–L3
token_ur = refresh_bar("Напряжение (фазное) L1–L3", "grp_urms")
present_urms = [c for c in ["Urms_L1", "Urms_L2", "Urms_L3"] if c in df.columns]
fig_urms = group_panel(df, present_urms, height=PLOT_HEIGHT, theme_base=theme_base)
st.plotly_chart(fig_urms, use_container_width=True, config={"responsive": True}, key=f"grp_urms_{token_ur}")

# 4) Напряжение (линейное) L12 / L23 / L31
token_ul = refresh_bar("Напряжение (линейное) L12 / L23 / L31", "grp_uline")
present_uline = [c for c in ["U_L1_L2", "U_L2_L3", "U_L3_L1"] if c in df.columns]
fig_uline = group_panel(df, present_uline, height=PLOT_HEIGHT, theme_base=theme_base)
st.plotly_chart(fig_uline, use_container_width=True, config={"responsive": True}, key=f"grp_uline_{token_ul}")

# 5) Коэффициент мощности (PF)
token_pf = refresh_bar("Коэффициент мощности (PF)", "grp_pf")
present_pf = [c for c in ["pf_total", "pf_L1", "pf_L2", "pf_L3"] if c in df.columns]
fig_pf = group_panel(df, present_pf, height=PLOT_HEIGHT, theme_base=theme_base)
st.plotly_chart(fig_pf, use_container_width=True, config={"responsive": True}, key=f"grp_pf_{token_pf}")

# 6) Фазовые углы (между линиями)
token_ang = refresh_bar("Фазовые углы (между линиями)", "grp_ang")
present_ang = [c for c in ["angle_L1_L2", "angle_L2_L3", "angle_L3_L1"] if c in df.columns]
fig_ang = group_panel(df, present_ang, height=PLOT_HEIGHT, theme_base=theme_base)
st.plotly_chart(fig_ang, use_container_width=True, config={"responsive": True}, key=f"grp_ang_{token_ang}")
