from __future__ import annotations
from datetime import date
import streamlit as st

def _btn(col, label: str, key: str, primary: bool, on_click=None, args=()) -> bool:
    """Кнопка с подсветкой; поддерживает on_click/args для записи выбора в session_state."""
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

def render_date_hour_picker(*, key_prefix: str = "picker_", expanded: bool = True) -> tuple[date | None, int | None]:
    """
    Календарь и сетка часов 00..23.
    Подсветка часов берётся из st.session_state['loaded_hours'] — реально показанные на графике часы.
    Возвращает (дата, None): сам клик по часу отдаём через __pending_*.
    key_prefix — префикс ключей, чтобы безопасно перерисовывать виджет в тот же прогон.
    """
    selected_date = st.session_state.get("selected_date") or date.today()

    # Всегда держим панель раскрытой, чтобы выбор дня не закрывал часы
    with st.expander("Выбрать дату и час", expanded=expanded):
        selected_date = st.date_input(
            "Дата",
            value=selected_date,
            format="YYYY-MM-DD",
            key=f"{key_prefix}date_pick",
        )
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
                key = f"{key_prefix}hour_{selected_date.isoformat()}_{h:02d}"
                _btn(
                    cols[i],
                    label,
                    key,
                    primary=is_loaded,
                    on_click=_mark_pending,
                    args=(selected_date, h),
                )

    return selected_date, None
