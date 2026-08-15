from __future__ import annotations
import streamlit as st


def init_once():
    if "df_current" not in st.session_state:
        st.session_state["df_current"] = None
    if "time_col" not in st.session_state:
        st.session_state["time_col"] = "timestamp"


def _hour_or_none(value) -> int | None:
    try:
        hour = int(value)
    except (TypeError, ValueError):
        return None
    return hour if 0 <= hour <= 23 else None


def _selection_for_mode(mode: str) -> tuple[object | None, int | None]:
    """Возвращает фактически выбранные дату и час исходного режима."""
    ss = st.session_state

    if mode == "daily":
        # Суточный режим передаёт только дату. Час в следующем окне
        # пользователь должен выбрать самостоятельно.
        return ss.get("selected_day"), None

    if mode == "hourly":
        selected_date = ss.get("selected_date") or ss.get("current_date")
        current_date = ss.get("current_date")
        current_hour = _hour_or_none(ss.get("current_hour"))
        if selected_date is None or current_date != selected_date:
            current_hour = None
        return selected_date, current_hour

    if mode == "minutely":
        selected_date = ss.get("selected_minute_date") or ss.get("current_minute_date")
        selected_hour = _hour_or_none(ss.get("selected_minute_hour"))
        if selected_hour is None and ss.get("current_minute_date") == selected_date:
            selected_hour = _hour_or_none(ss.get("current_minute_hour"))
        return selected_date, selected_hour

    if mode == "statistical":
        return ss.get("__mode_context_date"), _hour_or_none(ss.get("__mode_context_hour"))

    return None, None


def _clear_hourly_display() -> None:
    """Скрывает прежний часовой график, сохраняя загруженный кэш."""
    ss = st.session_state
    ss["loaded_hours"] = []
    ss["current_date"] = None
    ss["current_hour"] = None
    ss.pop("__pending_date", None)
    ss.pop("__pending_hour", None)


def _clear_minutely_display() -> None:
    """Скрывает прежний минутный график, сохраняя загруженный кэш."""
    ss = st.session_state
    ss["loaded_minutes"] = []
    ss["current_minute_date"] = None
    ss["current_minute_hour"] = None
    ss["current_minute_minute"] = None
    ss.pop("__pending_minute_date", None)
    ss.pop("__pending_minute_hour", None)
    ss.pop("__pending_minute_minute", None)


def synchronize_mode_selection(previous_mode: str, target_mode: str) -> None:
    """Синхронизирует дату/час перед первой отрисовкой нового режима."""
    if previous_mode == target_mode:
        return

    ss = st.session_state
    selected_date, selected_hour = _selection_for_mode(previous_mode)

    # Статистическое окно не меняет контекст. При входе в него запоминаем
    # выбор исходного режима, а при выходе восстанавливаем его отсюда.
    if previous_mode != "statistical":
        ss["__mode_context_date"] = selected_date
        ss["__mode_context_hour"] = selected_hour

    if target_mode == "statistical":
        return

    if target_mode == "daily":
        if selected_date is not None:
            ss["selected_day"] = selected_date
            ss["__daily_selection_from_mode"] = True
        return

    if target_mode == "hourly":
        if selected_date is not None:
            ss["selected_date"] = selected_date

        _clear_hourly_display()
        ss["__picker_redraw"] = int(ss.get("__picker_redraw", 0)) + 1

        # Час переносим только из часового/минутного контекста. Из суточного
        # selected_hour всегда None, поэтому час остаётся невыбранным.
        if selected_date is not None and selected_hour is not None:
            ss["__pending_date"] = selected_date
            ss["__pending_hour"] = selected_hour
        return

    if target_mode == "minutely":
        if selected_date is not None:
            ss["selected_minute_date"] = selected_date

        ss["__minute_picker_redraw"] = int(ss.get("__minute_picker_redraw", 0)) + 1
        ss.pop("__pending_minute_date", None)
        ss.pop("__pending_minute_hour", None)
        ss.pop("__pending_minute_minute", None)

        if selected_date is None or selected_hour is None:
            ss.pop("selected_minute_hour", None)
            _clear_minutely_display()
            return

        ss["selected_minute_hour"] = selected_hour
        same_loaded_hour = (
            bool(ss.get("loaded_minutes"))
            and ss.get("current_minute_date") == selected_date
            and _hour_or_none(ss.get("current_minute_hour")) == selected_hour
        )
        if not same_loaded_hour:
            _clear_minutely_display()
