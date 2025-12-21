from __future__ import annotations
from datetime import date, timedelta
import streamlit as st

def render_day_picker() -> date:
    """
    Календарь БЕЗ кнопки подтверждения:
    при выборе даты сразу сохраняем её в состоянии и строим графики.
    """
    if "selected_day" not in st.session_state:
        st.session_state["selected_day"] = date.today()

    with st.expander("Выбрать день", expanded=False):
        st.date_input(
            "Дата",
            value=st.session_state["selected_day"],
            format="YYYY-MM-DD",
            key="selected_day",
        )

    return st.session_state["selected_day"]

def day_nav_buttons(enabled: bool) -> tuple[bool, bool]:
    """Кнопки 'Показать предыдущий/следующий день'."""
    c1, c2 = st.columns(2)
    with c1:
        prev = st.button("Показать предыдущий день", disabled=not enabled, use_container_width=True, key="btn_day_prev")
    with c2:
        nxt  = st.button("Показать следующий день", disabled=not enabled, use_container_width=True, key="btn_day_next")
    return prev, nxt

def shift_day(d: date, delta_days: int) -> date:
    return d + timedelta(days=delta_days)
