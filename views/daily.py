# views/daily.py
from __future__ import annotations
from datetime import date as date_cls
import pandas as pd
import streamlit as st

from core.config import HIDE_ALWAYS, DEFAULT_PRESET, PLOT_HEIGHT
from core.aggregate import aggregate_by
from core.hour_loader import load_hour
from core.plotting import main_chart
from ui.refresh import refresh_bar
from ui.summary import render_summary_controls
from ui.groups import render_group, render_power_group
from ui.day import render_day_picker, day_nav_buttons, shift_day


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            try:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            except Exception:
                pass
    return df


def _reset_on_day_change(day):
    day_key = day.strftime("%Y%m%d")
    prev = st.session_state.get("__daily_active_day_key")
    if prev != day_key:
        st.session_state["__daily_active_day_key"] = day_key
        for k in list(st.session_state.keys()):
            if k.startswith("daily__") or k.startswith("daily_agg_rule_"):
                del st.session_state[k]
        st.rerun()


def _get_daily_cache() -> dict[str, pd.DataFrame]:
    return st.session_state.setdefault("__daily_cache", {})


def render_daily_mode() -> None:
    st.markdown("### День")

    # Автовыбор текущих суток при первом заходе в режим
    if not st.session_state.get("selected_day_confirmed", False) and not st.session_state.get("selected_day"):
        st.session_state["selected_day"] = date_cls.today()
        st.session_state["selected_day_confirmed"] = True

    day = render_day_picker()

    # Навигация днями
    prev_day, next_day = day_nav_buttons(enabled=day is not None)
    if day and prev_day:
        st.session_state["selected_day"] = shift_day(day, -1)
        st.session_state["selected_day_confirmed"] = True
        st.rerun()
    if day and next_day:
        st.session_state["selected_day"] = shift_day(day, +1)
        st.session_state["selected_day_confirmed"] = True
        st.rerun()

    if not day:
        st.info("Выберите дату.")
        return

    _reset_on_day_change(day)

    day_key = day.strftime("%Y%m%d")
    daily_cache = _get_daily_cache()

    # --- Загрузка 24 часов выбранной даты ОДИН РАЗ ---
    if day_key in daily_cache:
        df_day = daily_cache[day_key]
        if df_day is None or df_day.empty:
            with st.status(f"Готовим данные за {day.isoformat()}…", expanded=True) as status:
                st.progress(100, text="Загружаем часы: 24/24")
                status.update(label=f"Отсутствуют данные за {day.isoformat()}.", state="error")
            st.warning(f"Отсутствуют данные за {day.isoformat()}.")
            return
    else:
        frames: list[pd.DataFrame] = []
        with st.status(f"Готовим данные за {day.isoformat()}…", expanded=True) as status:
            prog = st.progress(0, text="Загружаем часы: 0/24")
            for i, h in enumerate(range(24), start=1):
                dfh = load_hour(day, h, silent=True)
                if dfh is not None and not dfh.empty:
                    frames.append(dfh)
                prog.progress(int(i / 24 * 100), text=f"Загружаем часы: {i}/24")

            if not frames:
                daily_cache[day_key] = pd.DataFrame()
                status.update(label=f"Отсутствуют данные за {day.isoformat()}.", state="error")
                st.warning(f"Отсутствуют данные за {day.isoformat()}.")
                return

            status.update(label=f"Данные за {day.isoformat()} загружены.", state="complete")

        df_day = pd.concat(frames).sort_index()
        df_day = _coerce_numeric(df_day)
        daily_cache[day_key] = df_day

    # Доступные числовые колонки
    num_cols = [
        c for c in df_day.columns
        if c not in HIDE_ALWAYS
        and pd.api.types.is_numeric_dtype(df_day[c])
        and df_day[c].notna().any()
    ]
    if not num_cols:
        return

    # --- Селектор интервала усреднения ---
    OPTIONS = [("20 сек", "20s"), ("1 мин", "1min"), ("2 мин", "2min"), ("5 мин", "5min")]
    rules = [v for _, v in OPTIONS]
    labels = [l for l, _ in OPTIONS]

    radio_key = f"daily_agg_rule_{day_key}"
    current_rule = st.session_state.get(radio_key, "1min")
    if current_rule not in rules:
        current_rule = "1min"

    st.markdown("#### Интервал усреднения")
    idx = rules.index(current_rule)
    chosen_label = st.radio(
        "Интервал усреднения",
        options=labels,
        index=idx,
        horizontal=True,
        label_visibility="collapsed",
        key=f"{radio_key}__label",
    )
    new_rule = dict(OPTIONS)[chosen_label]
    if new_rule != current_rule:
        st.session_state[radio_key] = new_rule
        st.rerun()
    agg_rule = st.session_state.get(radio_key, new_rule)

    # Кнопка «Обновить все графики» — показываем ТОЛЬКО когда данные загружены
    if "refresh_daily_all" not in st.session_state:
        st.session_state["refresh_daily_all"] = 0
    if df_day is not None and not df_day.empty:
        if st.button("↻ Обновить все графики", use_container_width=True, key="btn_refresh_all_daily"):
            st.session_state["refresh_daily_all"] += 1
            st.rerun()
    ALL_TOKEN = st.session_state["refresh_daily_all"]

    # Агрегация по выбранному интервалу (только mean)
    df_day_num = df_day[[c for c in num_cols]]
    agg = aggregate_by(df_day_num, rule=agg_rule)
    df_mean = agg["mean"]

    theme_base = st.get_option("theme.base") or "light"

    # --- Суточный сводный график ---
    token_main = refresh_bar("Суточный сводный график", "daily_main")
    default_main = [c for c in DEFAULT_PRESET if c in df_mean.columns] or list(df_mean.columns[:3])

    selected_main, separate_set = render_summary_controls(
        list(df_mean.columns),
        default_main,
        key_prefix="daily__",
        strict=False,  # мягкий режим как в часовом
    )

    # Автообновление сводного при смене нормировки
    norm_token = "__".join(sorted(separate_set)) if separate_set else "none"
    prev_norm_key = f"__daily_prev_norm_{day_key}"
    prev_norm = st.session_state.get(prev_norm_key)
    if prev_norm is None:
        st.session_state[prev_norm_key] = norm_token
    elif prev_norm != norm_token:
        st.session_state[prev_norm_key] = norm_token
        k = "refresh_daily_main"
        st.session_state[k] = int(st.session_state.get(k, 0)) + 1
        st.rerun()

    sel_token = "__".join(selected_main) if selected_main else "none"
    agg_key = agg_rule
    chart_key = (
        f"daily_main_{ALL_TOKEN}_{day_key}_{agg_key}_{sel_token}_{norm_token}_"
        f"{st.session_state.get('refresh_daily_main', 0)}"
    )

    fig_main = main_chart(
        df=df_mean,
        series=selected_main,
        height=PLOT_HEIGHT,
        theme_base=theme_base,
        separate_axes=set(separate_set),
    )
    st.plotly_chart(
        fig_main,
        use_container_width=True,
        config={"responsive": True},
        key=chart_key,
    )

    # --- Группы (тот же df_mean) ---
    all_token_daily = f"{ALL_TOKEN}_{day_key}_{agg_key}"
    render_power_group(df_mean, PLOT_HEIGHT, theme_base, all_token_daily)
    render_group("Токи фаз L1–L3", "daily_grp_curr", df_mean,
                 ["Irms_L1", "Irms_L2", "Irms_L3"], PLOT_HEIGHT, theme_base, all_token_daily)
    render_group("Напряжение (фазное) L1–L3", "daily_grp_urms", df_mean,
                 ["Urms_L1", "Urms_L2", "Urms_L3"], PLOT_HEIGHT, theme_base, all_token_daily)
    render_group("Напряжение (линейное) L1-L2 / L2-L3 / L3-L1", "daily_grp_uline", df_mean,
                 ["U_L1_L2", "U_L2_L3", "U_L3_L1"], PLOT_HEIGHT, theme_base, all_token_daily)
    render_group("Коэффициент мощности (PF)", "daily_grp_pf", df_mean,
                 ["pf_total", "pf_L1", "pf_L2", "pf_L3"], PLOT_HEIGHT, theme_base, all_token_daily)

    freq_cols = [
        c for c in df_mean.columns
        if pd.api.types.is_numeric_dtype(df_mean[c]) and (
            ("freq" in c.lower()) or ("frequency" in c.lower())
            or ("hz" in c.lower()) or (c.lower() == "f")
        )
    ]
    if freq_cols:
        render_group("Частота сети", "daily_grp_freq", df_mean, freq_cols,
                     PLOT_HEIGHT, theme_base, all_token_daily)
