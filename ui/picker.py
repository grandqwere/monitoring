from __future__ import annotations
from datetime import date
import streamlit as st

from core.data_io import available_hours_for_date

def render_date_hour_picker(cache_buster: int) -> tuple[date | None, str | None]:
    """
    Показывает кнопку/expander «Выбрать дату и час».
    Внутри — календарь st.date_input и сетка из 24 часов (активны те, что существуют).
    Возвращает (selected_date, chosen_key) — key только если час кликнули.
    """
    chosen_key = None
    selected_date = st.session_state.get("selected_date", date.today())

    with st.expander("Выбрать дату и час", expanded=False):
        selected_date = st.date_input("Дата", value=selected_date, format="YYYY-MM-DD", key="date_pick")
        st.session_state["selected_date"] = selected_date

        with st.spinner("Проверяю наличие часов на выбранную дату…"):
            hours_map = available_hours_for_date(selected_date, cache_buster=cache_buster)

        # 3 строки по 8 часов
        for block in range(3):
            cols = st.columns(8)
            for i in range(8):
                h = block * 8 + i
                if h > 23:
                    continue
                label = f"{h:02d}:00"
                active = h in hours_map
                key = f"hour_{selected_date.isoformat()}_{h:02d}"
                if active:
                    if cols[i].button(label, key=key):
                        chosen_key = hours_map[h]
                else:
                    cols[i].button(label, key=key, disabled=True)


    return selected_date, chosen_key
