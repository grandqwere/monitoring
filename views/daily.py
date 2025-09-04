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
    loaded_msg_key = f"daily_loaded_msg_{day_key}"

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
            # восстановим/сохраним сообщение о загрузке (для устойчивости при переключении режимов)
            st.session_state[loaded_msg_key] = f"Данные за {day.isoformat()} загружены."
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
        st.session_state[loaded_msg_key] = f"Данные за {day.isoformat()} загружены."

    # Доступные числовые колонки
    num_cols = [
        c for c in df_day.columns
        if c not in HIDE_ALWAYS
        and pd.api.types.is_numeric_dtype(df_day[c])
        and df_day[c].notna().any()
    ]
    if not num_cols:
        return

    # ——— Сообщение «Данные за … загружены» (персистентное) ———
    msg = st.session_state.get(loaded_msg_key)
    if msg:
        st.caption(msg)

    # ——— Кнопка «Обновить график» — показываем ТОЛЬКО когда данные загружены ———
    if "refresh_daily_all" not in st.session_state:
        st.session_state["refresh_daily_all"] = 0
    if st.button("↻ Обновить график", use_container_width=True, key="btn_refresh_all_daily"):
        st.session_state["refresh_daily_all"] += 1
        st.rerun()
    ALL_TOKEN = st.session_state["refresh_daily_all"]

    # --- Селектор интервала усреднения ---
    OPTIONS = [("20 сек", "20s"), ("1 мин", "1min"), ("2 мин", "2min"), ("5 мин", "5min")]
    rules = [v]()
