from __future__ import annotations
import streamlit as st

from core import state
from views.daily import render_daily_mode
from views.hourly import render_hourly_mode
from core.hour_loader import init_hour_state

st.set_page_config(page_title="Мониторинг электрических параметров", layout="wide")
state.init_once()
init_hour_state() 

# Заголовок страницы (уменьшенный)
st.markdown("<h3 style='margin:0'>Мониторинг электрических параметров</h3>", unsafe_allow_html=True)

# Инициализация режима: по умолчанию — суточный
if "mode" not in st.session_state:
    st.session_state["mode"] = "daily"

# Предвыбор активной кнопки в переключателе
if "mode_segmented" not in st.session_state:
    st.session_state["mode_segmented"] = "Суточные" if st.session_state["mode"] == "daily" else "Часовые"

# Горизонтальный переключатель «Вид графиков»
label = "Вид графиков"
options = ["Часовые", "Суточные"]
try:
    chosen = st.segmented_control(
        label,
        options=options,
        key="mode_segmented",
    )
except Exception:
    # Фолбэк для старых версий Streamlit
    chosen = st.radio(
        label,
        options=options,
        horizontal=True,
        index=(1 if st.session_state["mode"] == "daily" else 0),
        key="mode_segmented",
    )

st.session_state["mode"] = "daily" if chosen == "Суточные" else "hourly"

# Роутинг по режимам
if st.session_state["mode"] == "daily":
    render_daily_mode()
else:
    render_hourly_mode()
