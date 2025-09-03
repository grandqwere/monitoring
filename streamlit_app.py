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
from core.s3_paths import build_all_key_for  # формируем путь к файлам All/…


st.set_page_config(page_title="Сводные графики электроизмерений", layout="wide")
state.init_once()

# ---------------- Глобальная панель ----------------
ALL_TOKEN = draw_refresh_all()

# --------- состояние отображаемых часов (макс. 2) ----------
# loaded_hours: список [(date, hour)] в порядке добавления (последние — самые «свежие»)
if "loaded_hours" not in st.session_state:
    st.session_state["loaded_hours"] = []          # [(date, hour)]
if "hour_cache" not in st.session_state:
    st.session_state["hour_cache"] = {}            # "YYYY-MM-DDTHH" -> DataFrame

def _key_for(d: date_cls, h: int) -> str:
    return f"{d.isoformat()}T{h:02d}"

def _load_hour(d: date_cls, h: int) -> pd.DataFrame | None:
    """Читает час из S3 и приводит, без лишних кешей. Возвращает df или None."""
    k = _key_for(d, h)
    if k in st.session_state["hour_cache"]:
        return st.session_state["hour_cache"][k]
    s3_key = build_all_key_for(d, h)
    try:
        df_raw = read_csv_s3(s3_key)
        df = normalize(df_raw)
        st.session_state["hour_cache"][k] = df
        return df
    except Exception as e:
        st.error(f"Файл не найден или не читается: `{s3_key}`. {e}")
        return None

def _set_only_hour(d: date_cls, h: int) -> bool:
    """Режим «Показать ...»: оставляем только этот час (без второго)."""
    df = _load_hour(d, h)
    if df is None:
        return False
    st.session_state["loaded_hours"] = [(d, h)]
    # чистим кеш от всего лишнего
    to_keep = {_key_for(d, h)}
    st.session_state["hour_cache"] = {k: v for k, v in st.session_state["hour_cache"].items() if k in to_keep}
    # также обновим «текущий выбор» для пикера
    st.session_state["current_date"] = d
    st.session_state["current_hour"] = h
    return True

def _append_hour(d: date_cls, h: int) -> bool:
    """Режим «Загрузить ...»: добавляем второй час, максимум 2 в памяти (с выбросом самого старого)."""
    df = _load_hour(d, h)
    if df is None:
        return False
    pair = (d, h)
    # если уже есть — просто обновим порядок
    lh: list[tuple[date_cls, int]] = st.session_state["loaded_hours"]
    if pair in lh:
        lh.remove(pair)
    lh.append(pair)
    # ограничение до 2 часов
    while len(lh) > 2:
        old = lh.pop(0)
        st.session_state["hour_cache"].pop(_key_for(*old), None)
    # текущим считаем последний добавленный
    st.session_state["current_date"], st.session_state["current_hour"] = lh[-1]
    return True

def _combined_df() -> pd.DataFrame:
    """Объединяет загруженные часы (1 или 2) в один df по времени."""
    frames = []
    for d, h in st.session_state["loaded_hours"]:
        k = _key_for(d, h)
        if k in st.session_state["hour_cache"]:
            frames.append(st.session_state["hour_cache"][k])
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames).sort_index()
    return df

def _has_current() -> bool:
    return ("current_date" in st.session_state) and ("current_hour" in st.session_state)

# ---------------- Кнопки навигации/загрузки ----------------
nav1, nav2, nav3, nav4 = st.columns([0.25, 0.25, 0.25, 0.25])
with nav1:
    show_prev = st.button("Показать предыдущий час", disabled=not _has_current(), use_container_width=True)
with nav2:
    load_prev = st.button("Загрузить предыдущий час", disabled=not _has_current(), use_container_width=True)
with nav3:
    load_next = st.button("Загрузить следующий час", disabled=not _has_current(), use_container_width=True)
with nav4:
    show_next = st.button("Показать следующий час", disabled=not _has_current(), use_container_width=True)

# ---------------- Пикер даты/часа ----------------
# Подсветим в таблице часов те, что загружены для выбранной даты
hl_for_date: set[int] = set()
sel_date_for_hl = st.session_state.get("selected_date")
if sel_date_for_hl:
    for d, h in st.session_state["loaded_hours"]:
        if d == sel_date_for_hl:
            hl_for_date.add(h)

st.markdown("### Дата и час (S3)")
picked_date, picked_hour = render_date_hour_picker(loaded_hours_for_selected_date=hl_for_date)

# выбор из пикера -> «Показать» этот час
if picked_date and picked_hour is not None:
    _set_only_hour(picked_date, picked_hour)

# обработка кнопок «Показать/Загрузить» (только после того, как уже выбран хотя бы один час)
if _has_current():
    base_d = st.session_state["current_date"]
    base_h = st.session_state["current_hour"]
    if show_prev:
        dt = datetime(base_d.year, base_d.month, base_d.day, base_h) + timedelta(hours=-1)
        _set_only_hour(dt.date(), dt.hour)
    if show_next:
        dt = datetime(base_d.year, base_d.month, base_d.day, base_h) + timedelta(hours=+1)
        _set_only_hour(dt.date(), dt.hour)
    if load_prev:
        dt = datetime(base_d.year, base_d.month, base_d.day, base_h) + timedelta(hours=-1)
        _append_hour(dt.date(), dt.hour)
    if load_next:
        dt = datetime(base_d.year, base_d.month, base_d.day, base_h) + timedelta(hours=+1)
        _append_hour(dt.date(), dt.hour)

# если всё ещё нет данных — подскажем
if not st.session_state["loaded_hours"]:
    st.info("Выберите день и час.")
    st.stop()

# ---------------- Собираем итоговый df для графиков ----------------
df_current = _combined_df()
if df_current.empty:
    st.error("Не удалось загрузить данные за выбранный час(ы).")
    st.stop()

# ---------------- Дальше — графики ----------------
num_cols = [c for c in df_current.columns if c not in HIDE_ALWAYS and pd.api.types.is_numeric_dtype(df_current[c])]
if not num_cols:
    st.error("Не нашёл числовых колонок для графика.")
    st.stop()

theme_base = st.get_option("theme.base") or "light"

# Сводный график
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
