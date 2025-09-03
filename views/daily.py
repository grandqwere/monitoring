from __future__ import annotations
from datetime import datetime
import pandas as pd
import streamlit as st

from core.config import HIDE_ALWAYS, DEFAULT_PRESET, PLOT_HEIGHT
from core.aggregate import aggregate_by
from core.hour_loader import load_hour
from core.plotting import daily_main_chart
from ui.refresh import refresh_bar
from ui.summary import render_summary_controls
from ui.groups import render_group, render_power_group
from ui.day import render_day_picker, day_nav_buttons, shift_day


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


def render_daily_mode(ALL_TOKEN: int) -> None:
    st.markdown("### День")
    day = render_day_picker()

    # Навигация днями
    prev_day, next_day = day_nav_buttons(enabled=day is not None)
    if day and prev_day:
        st.session_state["selected_day"] = shift_day(day, -1)
        st.rerun()
    if day and next_day:
        st.session_state["selected_day"] = shift_day(day, +1)
        st.rerun()

    if not day:
        st.info("Выберите дату.")
        st.stop()

    # Сборка 24 часов дня
    frames: list[pd.DataFrame] = []
    raw_points = 0

    try:
        with st.status(f"Готовим данные за {day.isoformat()}…", expanded=False) as status:
            prog = st.progress(0, text="Загружаем часы")
            found = 0
            for i, h in enumerate(range(24), start=1):
                dfh = load_hour(day, h)  # при отсутствии файла — мягкое st.info
                if dfh is not None and not dfh.empty:
                    frames.append(dfh)
                    raw_points += len(dfh)
                    found += 1
                prog.progress(int(i / 24 * 100), text=f"Загружаем часы: {i}/24")
            status.update(label="Агрегируем данные…", state="running")

            if not frames:
                status.update(label="Нет данных за выбранную дату.", state="error")
                st.info("Нет данных за выбранную дату.")
                st.stop()

            df_day = pd.concat(frames).sort_index()
            df_day = _coerce_numeric(df_day)

            num_cols = [
                c for c in df_day.columns
                if c not in HIDE_ALWAYS
                and pd.api.types.is_numeric_dtype(df_day[c])
                and df_day[c].notna().any()
            ]
            if not num_cols:
                status.update(label="Нет пригодных числовых данных за выбранную дату.", state="error")
                st.info("Нет пригодных числовых данных за выбранную дату.")
                st.stop()

            # Агрегация 5 минут — используем только mean
            agg = aggregate_by(df_day[num_cols], rule="5min")
            df_mean = agg["mean"]

            status.update(label=f"Данные за {day.isoformat()} загружены.", state="complete")
    except Exception:
        # Фолбэк для старых версий Streamlit без st.status
        with st.spinner(f"Готовим данные за {day.isoformat()}…"):
            for h in range(24):
                dfh = load_hour(day, h)
                if dfh is not None and not dfh.empty:
                    frames.append(dfh)
                    raw_points += len(dfh)
            if not frames:
                st.info("Нет данных за выбранную дату.")
                st.stop()
            df_day = pd.concat(frames).sort_index()
            df_day = _coerce_numeric(df_day)
            num_cols = [
                c for c in df_day.columns
                if c not in HIDE_ALWAYS
                and pd.api.types.is_numeric_dtype(df_day[c])
                and df_day[c].notna().any()
            ]
            if not num_cols:
                st.info("Нет пригодных числовых данных за выбранную дату.")
                st.stop()
            agg = aggregate_by(df_day[num_cols], rule="5min")
            df_mean = agg["mean"]

    theme_base = st.get_option("theme.base") or "light"

    # Контролы и сводный график
    token_main = refresh_bar("Суточный сводный график", "daily_main")
    default_main = [c for c in DEFAULT_PRESET if c in df_mean.columns] or list(df_mean.columns[:3])
    selected_main, separate_set = render_summary_controls(list(df_mean.columns), default_main)

    fig_main = daily_main_chart(
        df_mean=df_mean, df_p95=None, df_max=None, df_min=None,
        series=selected_main, height=PLOT_HEIGHT, theme_base=theme_base,
        separate_axes=set(separate_set), show_p95=False, show_extrema=False,
    )
    st.plotly_chart(
        fig_main, use_container_width=True, config={"responsive": True},
        key=f"daily_main_{ALL_TOKEN}_{token_main}",
    )

    # Группы
    render_power_group(df_mean, PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Токи фаз L1–L3", "daily_grp_curr", df_mean,
                 ["Irms_L1", "Irms_L2", "Irms_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Напряжение (фазное) L1–L3", "daily_grp_urms", df_mean,
                 ["Urms_L1", "Urms_L2", "Urms_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Напряжение (линейное) L1-L2 / L2-L3 / L3-L1", "daily_grp_uline", df_mean,
                 ["U_L1_L2", "U_L2_L3", "U_L3_L1"], PLOT_HEIGHT, theme_base, ALL_TOKEN)
    render_group("Коэффициент мощности (PF)", "daily_grp_pf", df_mean,
                 ["pf_total", "pf_L1", "pf_L2", "pf_L3"], PLOT_HEIGHT, theme_base, ALL_TOKEN)

    # Частота (если есть)
    freq_cols = [
        c for c in df_mean.columns
        if pd.api.types.is_numeric_dtype(df_mean[c]) and (
            ("freq" in c.lower()) or ("frequency" in c.lower())
            or ("hz" in c.lower()) or (c.lower() == "f")
        )
    ]
    if freq_cols:
        render_group("Частота сети", "daily_grp_freq", df_mean, freq_cols,
                     PLOT_HEIGHT, theme_base, ALL_TOKEN)

    st.stop()
