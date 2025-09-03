from __future__ import annotations
from datetime import date
import streamlit as st

def render_date_hour_picker(loaded_hours_for_selected_date: set[int] | None = None) -> tuple[date | None, int | None]:
    """
    Кнопка (expander) с календарём и сеткой часов.
    loaded_hours_for_selected_date — набор часов текущей даты, которые уже загружены (для подсветки).
    Возвращает (дата, выбранный_час) — час = int 0..23 или None.
    """
    chosen_hour: int | None = None
    loaded_hours_for_selected_date = loaded_hours_for_selected_date or set()
    # чтобы не было None в первом открытии
    selected_date = st.session_state.get("selected_date") or date.today()

    with st.expander("Выбрать дату и час", expanded=False):
        selected_date = st.date_input("Дата", value=selected_date, format="YYYY-MM-DD", key="date_pick")
        st.session_state["selected_date"] = selected_date

        # 3 строки по 8 часов (00..23)
        for block in range(3):
            cols = st.columns(8)
            for i in range(8):
                h = block * 8 + i
                if h > 23:
                    continue
                loaded = h in loaded_hours_for_selected_date
                label = f"{'◉ ' if loaded else ''}{h:02d}:00"
                key = f"hour_{selected_date.isoformat()}_{h:02d}"
                if cols[i].button(label, key=key):
                    chosen_hour = h

    return selected_date, chosen_hour
