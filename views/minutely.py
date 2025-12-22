# views/minutely.py
from __future__ import annotations

from datetime import datetime, timedelta
import pandas as pd
import streamlit as st

from core.config import PLOT_HEIGHT, MAX_POINTS_MINUTE_GROUP
from core.minute_loader import (
    set_only_minute,
    append_minute,
    combined_minute_df,
    has_minute_current,
)
from core.plotting import minutely_summary_chart, group_panel
from ui.refresh import refresh_bar
from ui.minute_picker import render_date_hour_minute_picker


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df = df.copy()
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            try:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            except Exception:
                pass
    return df


def _load_with_status_set_only(date_obj, hour: int, minute: int, *, status_area) -> bool:
    """Загрузить ТОЛЬКО эту минуту (очищая минутный кэш). Статус — под пикером."""
    with status_area.container():
        with st.status(
            f"Готовим данные за {date_obj.isoformat()} {hour:02d}:{minute:02d}…",
            expanded=True,
        ) as status:
            prog = st.progress(0, text="Загружаем минуту: 0/1")
            ok = set_only_minute(date_obj, int(hour), int(minute))
            prog.progress(100, text="Загружаем минуту: 1/1")
            if ok:
                status.update(state="complete")
            else:
                status.update(
                    label=f"Отсутствуют данные за {date_obj.isoformat()} {hour:02d}:{minute:02d}.",
                    state="error",
                )
                st.warning(f"Отсутствуют данные за {date_obj.isoformat()} {hour:02d}:{minute:02d}.")
    if not ok:
        st.session_state["loaded_minutes"] = []
        st.session_state["minute_cache"] = {}
        st.session_state["current_minute_date"] = None
        st.session_state["current_minute_hour"] = None
        st.session_state["current_minute_minute"] = None
    return ok


def _load_with_status_append(date_obj, hour: int, minute: int, *, status_area) -> bool:
    """Дозагрузить вторую минуту. Статус — под пикером."""
    with status_area.container():
        with st.status(
            f"Готовим данные за {date_obj.isoformat()} {hour:02d}:{minute:02d}…",
            expanded=True,
        ) as status:
            prog = st.progress(0, text="Загружаем минуту: 0/1")
            ok = append_minute(date_obj, int(hour), int(minute))
            prog.progress(100, text="Загружаем минуту: 1/1")
            if ok:
                status.update(state="complete")
            else:
                status.update(
                    label=f"Отсутствуют данные за {date_obj.isoformat()} {hour:02d}:{minute:02d} (дозагрузка).",
                    state="error",
                )
                st.warning(f"Отсутствуют данные за {date_obj.isoformat()} {hour:02d}:{minute:02d} (дозагрузка).")
    return ok


def _draw_picker(picker_ph) -> None:
    """Отрисовать минутный пикер с уникальными ключами за текущий прогон."""
    rid = st.session_state.setdefault("__minute_picker_redraw", 0)
    with picker_ph.container():
        render_date_hour_minute_picker(key_prefix=f"mp_{rid}_", expanded=True)


def _redraw_picker(picker_ph) -> None:
    """Перерисовать пикер в том же месте с новыми ключами (чтобы не было дубликатов)."""
    st.session_state["__minute_picker_redraw"] = int(st.session_state.get("__minute_picker_redraw", 0)) + 1
    picker_ph.empty()
    _draw_picker(picker_ph)


def render_minutely_mode() -> None:
    st.markdown("### Дата, час и минута")

    picker_ph = st.empty()
    status_ph = st.empty()

    # 1) Пикер
    _draw_picker(picker_ph)

    # 2) Клик по минуте (pending)
    pend_d = st.session_state.pop("__pending_minute_date", None)
    pend_h = st.session_state.pop("__pending_minute_hour", None)
    pend_m = st.session_state.pop("__pending_minute_minute", None)
    if pend_d is not None and pend_h is not None and pend_m is not None:
        if _load_with_status_set_only(pend_d, int(pend_h), int(pend_m), status_area=status_ph):
            _redraw_picker(picker_ph)
        else:
            _redraw_picker(picker_ph)

    # 3) Навигация по минутам
    nav1, nav2, nav3, nav4 = st.columns(4)
    with nav1:
        show_prev = st.button("Показать предыдущую минуту", disabled=not has_minute_current(), use_container_width=True)
    with nav2:
        load_prev = st.button("Загрузить предыдущую минуту", disabled=not has_minute_current(), use_container_width=True)
    with nav3:
        load_next = st.button("Загрузить следующую минуту", disabled=not has_minute_current(), use_container_width=True)
    with nav4:
        show_next = st.button("Показать следующую минуту", disabled=not has_minute_current(), use_container_width=True)

    if has_minute_current():
        base_d = st.session_state["current_minute_date"]
        base_h = int(st.session_state["current_minute_hour"])
        base_m = int(st.session_state["current_minute_minute"])
        base_dt = datetime(base_d.year, base_d.month, base_d.day, base_h, base_m)

        if show_prev:
            dt = base_dt + timedelta(minutes=-1)
            if _load_with_status_set_only(dt.date(), dt.hour, dt.minute, status_area=status_ph):
                _redraw_picker(picker_ph)

        if show_next:
            dt = base_dt + timedelta(minutes=+1)
            if _load_with_status_set_only(dt.date(), dt.hour, dt.minute, status_area=status_ph):
                _redraw_picker(picker_ph)

        if load_prev:
            dt = base_dt + timedelta(minutes=-1)
            if _load_with_status_append(dt.date(), dt.hour, dt.minute, status_area=status_ph):
                _redraw_picker(picker_ph)

        if load_next:
            dt = base_dt + timedelta(minutes=+1)
            if _load_with_status_append(dt.date(), dt.hour, dt.minute, status_area=status_ph):
                _redraw_picker(picker_ph)

    # 4) Если нет данных — завершаем режим
    if not st.session_state.get("loaded_minutes"):
        st.stop()

    # 5) Данные
    df_current = combined_minute_df()
    if df_current is None or df_current.empty:
        st.info("Нет данных за выбранные минут(ы). Попробуйте выбрать другую минуту.")
        st.stop()
    df_current = _coerce_numeric(df_current)

    theme_base = st.get_option("theme.base") or "light"

    # Кнопка «Обновить все графики»
    if "refresh_minutely_all" not in st.session_state:
        st.session_state["refresh_minutely_all"] = 0
    if st.button("↻ Обновить все графики", use_container_width=True, key="btn_refresh_all_minutely"):
        st.session_state["refresh_minutely_all"] += 1
        st.rerun()
    ALL_TOKEN = st.session_state["refresh_minutely_all"]

    # --- График 1: сводный (две оси: I слева, U справа) ---
    token_sum = refresh_bar("Минутный сводный график: Ipeak + Upeak", "minutely_summary")
    fig_sum = minutely_summary_chart(df_current, height=PLOT_HEIGHT, theme_base=theme_base)
    st.plotly_chart(
        fig_sum,
        use_container_width=True,
        config={"responsive": True},
        key=f"minutely_sum_{ALL_TOKEN}_{token_sum}",
    )

    # --- График 2: Ipeak ---
    i_cols = [c for c in df_current.columns if str(c).startswith("Ipeak_")]
    if i_cols:
        token_i = refresh_bar("Токи: Ipeak (L1–L3)", "minutely_ipeak")
        fig_i = group_panel(
            df_current,
            i_cols,
            height=PLOT_HEIGHT,
            theme_base=theme_base,
            max_points=MAX_POINTS_MINUTE_GROUP,
        )
        st.plotly_chart(
            fig_i,
            use_container_width=True,
            config={"responsive": True},
            key=f"minutely_i_{ALL_TOKEN}_{token_i}",
        )
    else:
        st.info("Нет колонок Ipeak_* в выбранных данных.")

    # --- График 3: Upeak ---
    u_cols = [c for c in df_current.columns if str(c).startswith("Upeak_")]
    if u_cols:
        token_u = refresh_bar("Напряжения: Upeak (L1–L3)", "minutely_upeak")
        fig_u = group_panel(
            df_current,
            u_cols,
            height=PLOT_HEIGHT,
            theme_base=theme_base,
            max_points=MAX_POINTS_MINUTE_GROUP,
        )
        st.plotly_chart(
            fig_u,
            use_container_width=True,
            config={"responsive": True},
            key=f"minutely_u_{ALL_TOKEN}_{token_u}",
        )
    else:
        st.info("Нет колонок Upeak_* в выбранных данных.")
