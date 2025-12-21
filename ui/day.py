from __future__ import annotations
from datetime import date, timedelta
import streamlit as st


def _nav_shift(delta_days: int) -> None:
    """Сдвиг выбранной даты безопасно (через callback кнопки)."""
    if "selected_day" not in st.session_state:
        st.session_state["selected_day"] = date.today()
    st.session_state["selected_day"] = st.session_state["selected_day"] + timedelta(days=delta_days)


def render_day_picker() -> date:
    if "selected_day" not in st.session_state:
        st.session_state["selected_day"] = date.today()

    with st.expander("Выбрать день", expanded=False):
        st.date_input(
            "Дата",
            key="selected_day",
            format="YYYY-MM-DD",
        )

    return st.session_state["selected_day"]


def day_nav_buttons(enabled: bool) -> None:
    """Кнопки 'Показать предыдущий/следующий день' (под календарём)."""
    c1, c2 = st.columns(2)
    with c1:
        st.button(
            "Показать предыдущий день",
            disabled=not enabled,
            use_container_width=True,
            key="btn_day_prev",
            on_click=_nav_shift,
            args=(-1,),
        )
    with c2:
        st.button(
            "Показать следующий день",
            disabled=not enabled,
            use_container_width=True,
            key="btn_day_next",
            on_click=_nav_shift,
            args=(+1,),
        )


def shift_day(d: date, delta_days: int) -> date:
    return d + timedelta(days=delta_days)
