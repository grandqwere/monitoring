from __future__ import annotations
import streamlit as st

from core import state
from ui.refresh import draw_refresh_all
from views.daily import render_daily_mode
from views.hourly import render_hourly_mode
from core.hour_loader import init_hour_state

st.set_page_config(page_title="Часовые графики электроизмерений", layout="wide")
state.init_once()
init_hour_state()

# Заголовок и «Обновить всё»
ALL_TOKEN = draw_refresh_all()

# Тумблер режима
mode_daily = st.toggle(
    "Режим: сутки",
    value=st.session_state.get("mode_daily", False),
    key="mode_daily"
)

# Роутинг по режимам
if mode_daily:
    render_daily_mode(ALL_TOKEN)
else:
    render_hourly_mode(ALL_TOKEN)
