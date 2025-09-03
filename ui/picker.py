from __future__ import annotations
from datetime import date
import streamlit as st

def _btn(col, label: str, key: str, primary: bool) -> bool:
    """Кнопка с подсветкой: пробуем type='primary', если не поддерживается — без него."""
    try:
        return col.button(label, key=key, type=("primary" if primary else "secondary"))
    except TypeError:
        return col.button(label, key=key)

def render_date_hour_picker() -> tuple[date | None, int | None]:
    """
    Экспандер с календарём и сеткой часов 00..23.
    Подсветка часов берётся из st.session_state['loaded_hours'] -> реально показанные на графике часы.
    Возвращает (дата, выбранный_час) — если час кликнули, иначе (дата, None).
    """
    chosen_hour: int | None = None
    selected_date = st.session_state.get("selected_date") or date.today()

    with st.expander("Выбрать дату и час", expanded=False):
        selected_date = st.date_input("Дата", value=selected_date, format="YYYY-MM-DD", key="date_pick")
        st.session_state["selected_date"] = selected_date

        # набор часов, которые сейчас реально показаны на графике для выбранной даты
        loaded_set = set()
        for (d, h) in st.session_state.get("loaded_hours", []):
            if d == selected_date:
                loaded_set.add(h)

        # 3 строки по 8 часов (00..23) с подсветкой загруженных
        for block in range(3):
            cols = st.columns(8)
            for i in range(8):
                h = block * 8 + i
                if h > 23:
                    continue
                is_loaded = h in loaded_set
                label = f"{h:02d}:00"
                key = f"hour_{selected_date.isoformat()}_{h:02d}"
                if _btn(cols[i], label, key, primary=is_loaded):
                    chosen_hour = h

    return selected_date, chosen_hour
