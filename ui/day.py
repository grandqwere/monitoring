from __future__ import annotations
from datetime import date, timedelta
import streamlit as st

def render_day_picker() -> date | None:
    """Календарь без авто-загрузки: день выбирается и подтверждается кнопкой."""
    confirmed = bool(st.session_state.get("selected_day_confirmed", False))
    current = st.session_state.get("selected_day", None)

    # Внутреннее «черновое» значение (не подтверждённое)
    with st.expander("Выбрать день", expanded=not confirmed):
        temp = st.date_input(
            "Дата",
            value=(current or date.today()),
            format="YYYY-MM-DD",
            key="date_pick_day",
        )
        if st.button("Показать день", key="btn_show_day", use_container_width=True):
            st.session_state["selected_day"] = temp
            st.session_state["selected_day_confirmed"] = True
            return temp

    # Возвращаем подтверждённый день (если уже выбран)
    if confirmed and st.session_state.get("selected_day"):
        return st.session_state["selected_day"]
    # Иначе — пока ничего не выбрано
    return None

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
