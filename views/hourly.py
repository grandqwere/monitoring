from __future__ import annotations
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st

from core.config import HIDE_ALWAYS, DEFAULT_PRESET, PLOT_HEIGHT
from core.hour_loader import (
    set_only_hour, append_hour, combined_df, has_current
)
from core.plotting import main_chart
from ui.refresh import refresh_bar
from ui.picker import render_date_hour_picker
from ui.summary import render_summary_controls
from ui.groups import render_group, render_power_group


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Страховка: приводим нечисловые столбцы к числу; сбойные значения -> NaN."""
    df = df.copy()
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            try:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            except Exception:
                pass
    return df


def render_hourly_mode(ALL_TOKEN: int) -> None:
    # Пикер даты/часа
    st.markdown("### Дата и час")
    picked_date, picked_hour = render_date_hour_picker()
    if picked_date and picked_hour is not None:
        if set_only_hour(picked_date, picked_hour):
            st.rerun()

    # Навигационные кнопки
    nav1, nav2, nav3, nav4 = st.columns([0.25, 0.25, 0.25, 0.25])
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
            if set_only_hour(dt.date(), dt.hour): st.rerun()
        if show_next:
            dt = datetime(base_d.year, base_d.month, base_d.day, base_h) + timedelta(hours=+1)
            if set_only_hour(dt.date(), dt.hour): st.rerun()
        if load_prev:
            dt = datetime(base_d.year, base_d.month, base_d.day, base_h) + timedelta(hours=-1)
            if append_hour(dt.date(), dt.hour): st.rerun()
        if load_next:
            dt = datetime(base_d.year, base_d.month, base_d.day, base_h) + timedelta(hours=+1)
            if append_hour(dt.date(), dt.hour): st.rerun()

    # Если нет данных — подскажем
    if not st.session_state["loaded_hours"]:
        st.info("Выберите день и час.")
        st.stop()

    # Сборка и страховка типов
    df_current = combined_df()
    if df_current.empty:
        st.info("Нет данных за выбранные час(ы). Попробуйте выбрать другой час.")
        st.stop()
    df_current = _coerce_numeric(df_current)

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

    # Сводный график
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

    # Группы
    render_power_group(df_current, PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Токи фаз L1–L3", "grp_curr", df_current,
                 ["Irms_L1", "Irms_L2", "Irms_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Напряжение (фазное) L1–L3", "grp_urms", df_current,
                 ["Urms_L1", "Urms_L2", "Urms_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Напряжение (линейное) L1-L2 / L2-L3 / L3-L1", "grp_uline", df_current,
                 ["U_L1_L2", "U_L2_L3", "U_L3_L1"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Коэффициент мощности (PF)", "grp_pf", df_current,
                 ["pf_total", "pf_L1", "pf_L2", "pf_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)

    # Частота (если есть)
    freq_cols = [
        c for c in df_current.columns
        if pd.api.types.is_numeric_dtype(df_current[c]) and (
            ("freq" in c.lower()) or ("frequency" in c.lower())
            or ("hz" in c.lower()) or (c.lower() == "f")
        )
    ]
    if freq_cols:
        render_group("Частота сети", "grp_freq", df_current, freq_cols,
                     PLOT_HEIGHT, theme_base, ALL_TOKEN)
