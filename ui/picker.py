from __future__ import annotations
from datetime import date
import streamlit as st

def _btn(col, label: str, key: str, primary: bool, on_click=None, args=()) -> bool:
    """Кнопка с подсветкой (type='primary' для загруженных часов).
       Поддерживаем on_click/args, чтобы писать выбор в session_state до следующего прогона."""
    try:
        return col.button(
            label,
            key=key,
            type=("primary" if primary else "secondary"),
            on_click=on_click,
            args=args,
        )
    except TypeError:
        return col.button(label, key=key, on_click=on_click, args=args)

def _mark_pending(date_obj: date, hour: int):
    """Пометить выбранный час для обработки в начале следующего прогона."""
    st.session_state["__pending_date"] = date_obj
    st.session_state["__pending_hour"] = hour

def render_date_hour_picker() -> tuple[date | None, int | None]:
    """
    Экспандер с календарём и сеткой часов 00..23.
    Подсветка часов берётся из st.session_state['loaded_hours'] — реально показанные на графике часы.
    Возвращает (дата, None), т.к. сам клик отдаём через __pending_* в session_state.
    """
    selected_date = st.session_state.get("selected_date") or date.today()

    with st.expander("Выбрать дату и час", expanded=False):
        selected_date = st.date_input("Дата", value=selected_date, format="YYYY-MM-DD", key="date_pick")
        st.session_state["selected_date"] = selected_date

        # Часы, уже загруженные на график за выбранный день
        loaded_set = {h for (d, h) in st.session_state.get("loaded_hours", []) if d == selected_date}

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
                _btn(
                    cols[i],
                    label,
                    key,
                    primary=is_loaded,
                    on_click=_mark_pending,
                    args=(selected_date, h),
                )

    return selected_date, None
