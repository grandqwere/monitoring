from __future__ import annotations
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st

from core.config import HIDE_ALWAYS, DEFAULT_PRESET, PLOT_HEIGHT
from core.hour_loader import set_only_hour, append_hour, combined_df, has_current
from core.plotting import main_chart
from ui.refresh import refresh_bar
from ui.picker import render_date_hour_picker
from ui.summary import render_summary_controls
from ui.groups import render_group, render_power_group


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            try:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            except Exception:
                pass
    return df


def _load_with_status_set_only(date_obj, hour: int, *, status_area) -> bool:
    """Загрузить ТОЛЬКО этот час (очищая кэш). Статус — строго под пикером (status_area)."""
    with status_area.container():
        with st.status(f"Готовим данные за {date_obj.isoformat()} {hour:02d}:00…", expanded=True) as status:
            prog = st.progress(0, text="Загружаем часы: 0/1")
            ok = set_only_hour(date_obj, hour)
            prog.progress(100, text="Загружаем часы: 1/1")
            if ok:
                status.update(state="complete")
            else:
                status.update(label=f"Отсутствуют данные за {date_obj.isoformat()} {hour:02d}:00.", state="error")
                st.warning(f"Отсутствуют данные за {date_obj.isoformat()} {hour:02d}:00.")
    if not ok:
        st.session_state["loaded_hours"] = []
        st.session_state["hour_cache"] = {}
        st.session_state["current_date"] = None
        st.session_state["current_hour"] = None
    return ok


def _load_with_status_append(date_obj, hour: int, *, status_area) -> bool:
    """Дозагрузить второй час. Статус — под пикером (status_area)."""
    with status_area.container():
        with st.status(f"Готовим данные за {date_obj.isoformat()} {hour:02d}:00…", expanded=True) as status:
            prog = st.progress(0, text="Загружаем часы: 0/1")
            ok = append_hour(date_obj, hour)
            prog.progress(100, text="Загружаем часы: 1/1")
            if ok:
                status.update(state="complete")
            else:
                status.update(label=f"Отсутствуют данные за {date_obj.isoformat()} {hour:02d}:00 (дозагрузка).", state="error")
                st.warning(f"Отсутствуют данные за {date_obj.isoformat()} {hour:02d}:00 (дозагрузка).")
    return ok


def _draw_picker(picker_ph) -> None:
    """Отрисовать пикер с уникальными ключами за текущий прогон."""
    rid = st.session_state.setdefault("__picker_redraw", 0)
    with picker_ph.container():
        render_date_hour_picker(key_prefix=f"picker_{rid}_", expanded=True)


def _redraw_picker(picker_ph) -> None:
    """Перерисовать пикер в том же месте с новыми ключами (чтобы не было дубликатов)."""
    st.session_state["__picker_redraw"] = int(st.session_state.get("__picker_redraw", 0)) + 1
    picker_ph.empty()
    _draw_picker(picker_ph)


def render_hourly_mode() -> None:
    # Заголовок
    st.markdown("### Дата и час")

    # Плейсхолдеры: сначала пикер, затем статус — порядок фиксирован
    picker_ph = st.empty()
    status_ph = st.empty()

    # 1) Сначала рисуем пикер
    _draw_picker(picker_ph)

    # 2) Обрабатываем клик по часу (из __pending_*) и ПЕРЕРИСОВЫВАЕМ пикер в том же месте с новым key_prefix
    pend_d = st.session_state.pop("__pending_date", None)
    pend_h = st.session_state.pop("__pending_hour", None)
    if pend_d is not None and pend_h is not None:
        if _load_with_status_set_only(pend_d, int(pend_h), status_area=status_ph):
            _redraw_picker(picker_ph)
        else:
            # даже если нет данных — обновим пикер (подсветка снимется)
            _redraw_picker(picker_ph)

    # 3) Навигация
    nav1, nav2, nav3, nav4 = st.columns(4)
    with nav1:
        show_prev = st.button("Показать предыдущий час", disabled=not has_current(), use_container_width=True)
    with nav2:
        load_prev = st.button("Загрузить предыдущий час", disabled=not has_current(), use_container_width=True)
    with nav3:
        load_next = st.button("Загрузить следующий час", disabled=not has_current(), use_container_width=True)
    with nav4:
        show_next = st.button("Показать следующий час", disabled=not has_current(), use_container_width=True)

    if has_current():
        base_d = st.session_state["current_date"]
        base_h = st.session_state["current_hour"]
        if show_prev:
            dt = datetime(base_d.year, base_d.month, base_d.day, base_h) + timedelta(hours=-1)
            if _load_with_status_set_only(dt.date(), dt.hour, status_area=status_ph):
                _redraw_picker(picker_ph)
        if show_next:
            dt = datetime(base_d.year, base_d.month, base_d.day, base_h) + timedelta(hours=+1)
            if _load_with_status_set_only(dt.date(), dt.hour, status_area=status_ph):
                _redraw_picker(picker_ph)
        if load_prev:
            dt = datetime(base_d.year, base_d.month, base_d.day, base_h) + timedelta(hours=-1)
            if _load_with_status_append(dt.date(), dt.hour, status_area=status_ph):
                _redraw_picker(picker_ph)
        if load_next:
            dt = datetime(base_d.year, base_d.month, base_d.day, base_h) + timedelta(hours=+1)
            if _load_with_status_append(dt.date(), dt.hour, status_area=status_ph):
                _redraw_picker(picker_ph)

    # 4) Если нет данных — подскажем и завершим режим
    if not st.session_state.get("loaded_hours"):
        st.stop()

    # 5) Графики
    df_current = combined_df()
    if df_current.empty:
        st.info("Нет данных за выбранные час(ы). Попробуйте выбрать другой час.")
        st.stop()
    df_current = _coerce_numeric(df_current)

    # Кнопка «Обновить все графики»
    if "refresh_hourly_all" not in st.session_state:
        st.session_state["refresh_hourly_all"] = 0
    if st.button("↻ Обновить все графики", use_container_width=True, key="btn_refresh_all_hourly"):
        st.session_state["refresh_hourly_all"] += 1
    ALL_TOKEN = st.session_state["refresh_hourly_all"]

    num_cols = [
        c for c in df_current.columns
        if c not in HIDE_ALWAYS
        and pd.api.types.is_numeric_dtype(df_current[c])
        and df_current[c].notna().any()
    ]
    if not num_cols:
        st.info("Нет пригодных числовых данных за выбранные часы.")
        st.stop()

    theme_base = st.get_option("theme.base") or "light"

    token_main = refresh_bar("Сводный график", "main")
    default_main = [c for c in DEFAULT_PRESET if c in num_cols] or num_cols[:3]
    selected_main, separate_set = render_summary_controls(num_cols, default_main)

    fig_main = main_chart(
        df=df_current,
        series=selected_main,
        height=PLOT_HEIGHT,
        theme_base=theme_base,
        separate_axes=set(separate_set),
    )
    st.plotly_chart(
        fig_main,
        use_container_width=True,
        config={"responsive": True},
        key=f"main_{ALL_TOKEN}_{token_main}",
    )

    render_power_group(df_current, PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Токи фаз L1–L3", "grp_curr", df_current, ["Irms_L1", "Irms_L2", "Irms_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Напряжение (фазное) L1–L3", "grp_urms", df_current, ["Urms_L1", "Urms_L2", "Urms_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Напряжение (линейное) L1-L2 / L2-L3 / L3-L1", "grp_uline", df_current, ["U_L1_L2", "U_L2_L3", "U_L3_L1"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Коэффициент мощности (PF)", "grp_pf", df_current, ["pf_total", "pf_L1", "pf_L2", "pf_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)

    freq_cols = [c for c in df_current.columns if pd.api.types.is_numeric_dtype(df_current[c]) and (("freq" in c.lower()) or ("frequency" in c.lower()) or ("hz" in c.lower()) or (c.lower() == "f"))]
    if freq_cols:
        render_group("Частота сети", "grp_freq", df_current, freq_cols, PLOT_HEIGHT, theme_base, ALL_TOKEN)
