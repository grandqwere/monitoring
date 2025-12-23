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
from ui.day import render_day_picker, day_nav_buttons


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _reset_on_day_change(day: date_cls) -> None:
    day_key = day.strftime("%Y%m%d")
    prev = st.session_state.get("__daily_active_day_key")
    if prev != day_key:
        st.session_state["__daily_active_day_key"] = day_key
        # чистим только суточные ключи
        for k in list(st.session_state.keys()):
            if k.startswith("daily__") or k.startswith("daily_agg_rule_"):
                del st.session_state[k]
        st.rerun()


def _get_daily_cache() -> dict:
    """
    __daily_cache[day_key] -> dict:
      {
        "df": DataFrame,
        "hours_present": set[int],
      }
    (Если вдруг остался старый формат DataFrame — мигрируем.)
    """
    return st.session_state.setdefault("__daily_cache", {})


def _infer_hours_present_from_index(df: pd.DataFrame) -> set[int]:
    """Только для миграции старого кэша: по индексу определяем, какие часы есть."""
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return set()
    try:
        return {int(h) for h in pd.Index(df.index.hour).unique()}
    except Exception:
        return set()


def _get_entry(daily_cache: dict, day_key: str) -> dict:
    val = daily_cache.get(day_key)

    if isinstance(val, dict) and "df" in val:
        val.setdefault("hours_present", set())
        return val

    if isinstance(val, pd.DataFrame):
        entry = {"df": val, "hours_present": _infer_hours_present_from_index(val)}
        daily_cache[day_key] = entry
        return entry

    entry = {"df": pd.DataFrame(), "hours_present": set()}
    daily_cache[day_key] = entry
    return entry


def _load_full_day(day: date_cls) -> tuple[pd.DataFrame, set[int]]:
    """Полная пересборка дня: пробуем загрузить все 24 часа."""
    frames: list[pd.DataFrame] = []
    hours_present: set[int] = set()

    with st.status(f"Готовим данные за {day.isoformat()}…", expanded=True) as status:
        prog = st.progress(0, text="Загружаем часы: 0/24")
        for i, h in enumerate(range(24), start=1):
            dfh = load_hour(day, h, silent=True)
            if dfh is not None and not dfh.empty:
                frames.append(dfh)
                hours_present.add(int(h))
            prog.progress(int(i / 24 * 100), text=f"Загружаем часы: {i}/24")

        if not frames:
            status.update(label=f"Отсутствуют данные за {day.isoformat()}.", state="error")
            return pd.DataFrame(), set()

        status.update(state="complete")

    df_day = pd.concat(frames).sort_index()
    df_day = _coerce_numeric(df_day)

    if isinstance(df_day.index, pd.DatetimeIndex) and df_day.index.has_duplicates:
        df_day = df_day[~df_day.index.duplicated(keep="last")]

    return df_day, hours_present


def render_daily_mode() -> None:
    st.markdown("### День")

    if "selected_day" not in st.session_state:
        st.session_state["selected_day"] = date_cls.today()

    day = render_day_picker()
    day_nav_buttons(enabled=day is not None)

    if not day:
        st.info("Выберите дату.")
        return

    _reset_on_day_change(day)

    day_key = day.strftime("%Y%m%d")
    daily_cache = _get_daily_cache()
    entry = _get_entry(daily_cache, day_key)

    # Если день ещё не загружали — первичная полная загрузка
    if entry["df"] is None or entry["df"].empty:
        df_day, hours_present = _load_full_day(day)
        entry["df"] = df_day
        entry["hours_present"] = hours_present
        daily_cache[day_key] = entry

        if df_day.empty:
            st.warning(f"Отсутствуют данные за {day.isoformat()}.")
            return

    df_day: pd.DataFrame = entry["df"]
    if df_day is None or df_day.empty:
        st.warning(f"Отсутствуют данные за {day.isoformat()}.")
        return

    # Кнопка "Обновить все графики"
    if "refresh_daily_all" not in st.session_state:
        st.session_state["refresh_daily_all"] = 0

    hours_present_now = set(entry.get("hours_present") or set())
    loaded_cnt = len(hours_present_now)
    if loaded_cnt < 24:
        st.caption(f"Загружено часов: {loaded_cnt}/24. Чтобы добавить часы, нажмите кнопку 'Обновить все графики'")
    else:
        st.caption("Загружено часов: 24/24")

    if st.button("↻ Обновить все графики", use_container_width=True, key="btn_refresh_all_daily"):
        if loaded_cnt < 24:
            # ВАЖНО: пересобираем ВЕСЬ день заново, чтобы подтянуть появившиеся файлы
            df_day_new, hours_present_new = _load_full_day(day)
            entry["df"] = df_day_new
            entry["hours_present"] = hours_present_new
            daily_cache[day_key] = entry
        # В любом случае — просто перерисовка (как было)
        st.session_state["refresh_daily_all"] += 1
        st.rerun()

    ALL_TOKEN = st.session_state["refresh_daily_all"]

    # --- Дальше без изменений: колонки, агрегация, графики ---
    num_cols = [
        c for c in df_day.columns
        if c not in HIDE_ALWAYS
        and pd.api.types.is_numeric_dtype(df_day[c])
        and df_day[c].notna().any()
    ]
    if not num_cols:
        st.info("Нет числовых колонок для отображения.")
        return

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

    df_day_num = df_day[num_cols]
    df_mean = aggregate_by(df_day_num, rule=agg_rule)["mean"]

    theme_base = st.get_option("theme.base") or "light"

    token_main = refresh_bar("Суточный сводный график", "daily_main")
    default_main = [c for c in DEFAULT_PRESET if c in df_mean.columns] or list(df_mean.columns[:3])

    selected_main, separate_set = render_summary_controls(
        list(df_mean.columns),
        default_main,
        key_prefix="daily__",
        strict=False,
    )

    norm_token = "__".join(sorted(separate_set)) if separate_set else "none"
    sel_token = "__".join(selected_main) if selected_main else "none"
    chart_key = f"daily_main_{ALL_TOKEN}_{token_main}_{day_key}_{agg_rule}_{sel_token}_{norm_token}"

    fig_main = main_chart(
        df=df_mean,
        series=selected_main,
        height=PLOT_HEIGHT,
        theme_base=theme_base,
        separate_axes=set(separate_set),
    )
    st.plotly_chart(fig_main, use_container_width=True, config={"responsive": True}, key=chart_key)

    all_token_daily = f"{ALL_TOKEN}_{day_key}_{agg_rule}"
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
            ("freq" in c.lower()) or ("frequency" in c.lower()) or ("hz" in c.lower()) or (c.lower() == "f")
        )
    ]
    if freq_cols:
        render_group("Частота сети", "daily_grp_freq", df_mean, freq_cols,
                     PLOT_HEIGHT, theme_base, all_token_daily)
