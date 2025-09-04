from __future__ import annotations
import streamlit as st

from core import state
from views.daily import render_daily_mode
from views.hourly import render_hourly_mode
from core.hour_loader import init_hour_state

st.set_page_config(page_title="Графики электроизмерений", layout="wide")
state.init_once()
init_hour_state()

# Заголовок страницы
st.title("Графики электроизмерений")

# Единый режим (масштабируется на новые вкладки)
if "mode" not in st.session_state:
    # Мягкая миграция со старого переключателя
    if "mode_daily" in st.session_state:
        st.session_state["mode"] = "daily" if st.session_state["mode_daily"] else "hourly"
    else:
        st.session_state["mode"] = "hourly"

# Переключатель «линейка-вкладки»: Часовые | Суточные
try:
    chosen = st.segmented_control(
        "Режим",
        options=["Часовые", "Суточные"],
        key="mode_segmented",
    )
except Exception:
    chosen = st.radio(
        "Режим",
        options=["Часовые", "Суточные"],
        horizontal=True,
        key="mode_segmented",
    )

st.session_state["mode"] = "daily" if chosen == "Суточные" else "hourly"

# Роутинг по режимам
if st.session_state["mode"] == "daily":
    render_daily_mode()
else:
    render_hourly_mode()
