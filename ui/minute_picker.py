# ui/minute_picker.py
from __future__ import annotations

from datetime import date
import streamlit as st


def _btn(col, label: str, key: str, primary: bool, on_click=None, args=()) -> bool:
    """Кнопка с подсветкой; поддерживает on_click/args для совместимости версий Streamlit."""
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


def _mark_hour(hour: int) -> None:
    """Запомнить выбранный час (для отображения сетки минут)."""
    st.session_state["selected_minute_hour"] = int(hour)


def _mark_pending(date_obj: date, hour: int, minute: int) -> None:
    """Пометить выбранную минуту для обработки в начале следующего прогона."""
    st.session_state["__pending_minute_date"] = date_obj
    st.session_state["__pending_minute_hour"] = int(hour)
    st.session_state["__pending_minute_minute"] = int(minute)


def render_date_hour_minute_picker(*, key_prefix: str = "mp_", expanded: bool = True) -> tuple[date, int | None, int | None]:
    """
    Пикер: дата + час + минута.
    Подсветка:
      - ЧАС: подсвечиваем, если в st.session_state['loaded_minutes'] есть хоть одна минутная выборка для этого часа.
      - МИНУТА: подсвечиваем, если конкретная минута есть среди loaded_minutes.

    Клик по минуте пишет __pending_minute_* (date/hour/minute).
    Возвращаем (date, hour, None) — минуту отдаём через pending.
    """
    # Текущая выбранная дата
    selected_date = st.session_state.get("selected_minute_date") or st.session_state.get("selected_date") or date.today()

    # Текущий выбранный час (для показа сетки минут)
    selected_hour = st.session_state.get("selected_minute_hour")
    if selected_hour is None:
        selected_hour = st.session_state.get("current_minute_hour")
    if selected_hour is None:
        selected_hour = 0
    selected_hour = int(selected_hour)

    with st.expander("Выбрать дату, час и минуту", expanded=expanded):
        # Дата
        selected_date = st.date_input(
            "Дата",
            value=selected_date,
            format="YYYY-MM-DD",
            key=f"{key_prefix}date_pick",
        )
        st.session_state["selected_minute_date"] = selected_date

        # Загруженные минуты (для подсветки)
        loaded_minutes = st.session_state.get("loaded_minutes", [])  # [(date, hour, minute)]
        loaded_for_day = [(h, m) for (d, h, m) in loaded_minutes if d == selected_date]
        loaded_hours_set = {h for (h, _m) in loaded_for_day}
        loaded_min_set_for_hour = {m for (h, m) in loaded_for_day if h == selected_hour}

        # Сетка часов 00..23
        st.markdown("**Час:**")
        for block in range(3):
            cols = st.columns(8)
            for i in range(8):
                h = block * 8 + i
                if h > 23:
                    continue
                is_loaded_hour = h in loaded_hours_set
                label = f"{h:02d}:00"
                key = f"{key_prefix}hour_{selected_date.isoformat()}_{h:02d}"
                _btn(
                    cols[i],
                    label,
                    key,
                    primary=is_loaded_hour,
                    on_click=_mark_hour,
                    args=(h,),
                )

        # Если пользователь кликнул час, он уже в session_state
        selected_hour = int(st.session_state.get("selected_minute_hour", selected_hour))
        st.caption(f"Выбранный час для минут: {selected_hour:02d}:xx")

        # Пересчёт подсветки минут под новый выбранный час
        loaded_min_set_for_hour = {m for (h, m) in loaded_for_day if h == selected_hour}

        # Сетка минут 00..59 (6x10)
        st.markdown("**Минута:**")
        for row in range(6):
            cols = st.columns(10)
            for j in range(10):
                minute = row * 10 + j
                if minute > 59:
                    continue
                is_loaded_min = minute in loaded_min_set_for_hour
                label = f"{minute:02d}"
                key = f"{key_prefix}min_{selected_date.isoformat()}_{selected_hour:02d}_{minute:02d}"
                _btn(
                    cols[j],
                    label,
                    key,
                    primary=is_loaded_min,
                    on_click=_mark_pending,
                    args=(selected_date, selected_hour, minute),
                )

    return selected_date, selected_hour, None
