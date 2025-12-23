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
    __daily_cache хранит по ключу дня либо:
      - старый формат: DataFrame
      - новый формат: {"df": DataFrame, "hours_present": set[int]}
    """
    return st.session_state.setdefault("__daily_cache", {})


def _infer_hours_present(df: pd.DataFrame) -> set[int]:
    """Эвристика для обратной совместимости: по DatetimeIndex определяем, какие часы есть в df."""
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return set()
    try:
        return {int(h) for h in pd.Index(df.index.hour).unique()}
    except Exception:
        return set()


def _get_daily_entry(daily_cache: dict, day_key: str) -> dict:
    """Нормализуем запись к формату {"df":..., "hours_present":...} (поддержка старого кэша)."""
    val = daily_cache.get(day_key)
    if isinstance(val, dict) and "df" in val:
        val.setdefault("hours_present", _infer_hours_present(val.get("df")))
        return val

    if isinstance(val, pd.DataFrame):
        entry = {"df": val, "hours_present": _infer_hours_present(val)}
        daily_cache[day_key] = entry
        return entry

    entry = {"df": pd.DataFrame(), "hours_present": set()}
    daily_cache[day_key] = entry
    return entry


def _merge_frames(df_base: pd.DataFrame, new_frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Добавляем новые часы к уже имеющемуся df, сортируем, убираем дубликаты индекса."""
    if not new_frames:
        return df_base

    df_new = pd.concat(new_frames).sort_index()
    if df_base is None or df_base.empty:
        out = df_new
    else:
        out = pd.concat([df_base, df_new]).sort_index()

    if isinstance(out.index, pd.DatetimeIndex) and out.index.has_duplicates:
        out = out[~out.index.duplicated(keep="last")]

    return out


def _refresh_missing_hours(day: date_cls, entry: dict) -> tuple[dict, int]:
    """
    При «Обновить все графики»:
      - если часов меньше 24, пытаемся догрузить отсутствующие часы,
      - если появились на сервере — добавляем в entry["df"] и hours_present.
    Возвращает (entry, added_count).
    """
    hours_present: set[int] = set(entry.get("hours_present") or set())
    missing = [h for h in range(24) if h not in hours_present]

    if not missing:
        return entry, 0

    new_frames: list[pd.DataFrame] = []
    added = 0

    with st.status(f"Проверяем новые файлы за {day.isoformat()}…", expanded=True) as status:
        prog = st.progress(0, text=f"Проверяем часы: 0/{len(missing)}")
        for i, h in enumerate(missing, start=1):
            dfh = load_hour(day, h, silent=True)
            if dfh is not None and not dfh.empty:
                new_frames.append(dfh)
                hours_present.add(int(h))
                added += 1
            prog.progress(int(i / len(missing) * 100), text=f"Проверяем часы: {i}/{len(missing)}")

        if added > 0:
            status.update(label=f"Найдено новых часов: {added}. Догружаем в суточный кэш…", state="complete")
        else:
            status.update(label="Новых часов не найдено.", state="complete")

    if added > 0:
        df_base = entry.get("df")
        df_merged = _merge_frames(df_base, new_frames)
        df_merged = _coerce_numeric(df_merged)
        entry["df"] = df_merged
        entry["hours_present"] = hours_present

    return entry, added


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

    # --- Получаем (или создаём) entry ---
    entry = _get_daily_entry(daily_cache, day_key)

    # --- Если df ещё не собран — первичная сборка дня ---
    if entry["df"] is None or entry["df"].empty:
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
                entry["df"] = pd.DataFrame()
                entry["hours_present"] = set()
                daily_cache[day_key] = entry
                status.update(label=f"Отсутствуют данные за {day.isoformat()}.", state="error")
                st.warning(f"Отсутствуют данные за {day.isoformat()}.")
                return

            status.update(state="complete")

        df_day = pd.concat(frames).sort_index()
        df_day = _coerce_numeric(df_day)

        entry["df"] = df_day
        entry["hours_present"] = hours_present
        daily_cache[day_key] = entry

    df_day: pd.DataFrame = entry["df"]
    if df_day is None or df_day.empty:
        st.warning(f"Отсутствуют данные за {day.isoformat()}.")
        return

    # --- Кнопка "Обновить все графики": ДОГРУЗИТЬ новые часы, если их было < 24 ---
    if "refresh_daily_all" not in st.session_state:
        st.session_state["refresh_daily_all"] = 0

    # Подпись про полноту дня (полезно для понимания)
    hours_present_now = set(entry.get("hours_present") or _infer_hours_present(df_day))
    missing_cnt = 24 - len(hours_present_now)
    if missing_cnt > 0:
        st.caption(f"За день загружено часов: {len(hours_present_now)}/24 (не хватало {missing_cnt}).")

    if st.button("↻ Обновить все графики", use_container_width=True, key="btn_refresh_all_daily"):
        # 1) пытаемся догрузить появившиеся файлы
        entry, _added = _refresh_missing_hours(day, entry)
        daily_cache[day_key] = entry

        # 2) форсируем перерисовку (как и раньше)
        st.session_state["refresh_daily_all"] += 1
        st.rerun()

    ALL_TOKEN = st.session_state["refresh_daily_all"]

    # --- Дальше всё как было: формируем num_cols, агрегацию, графики ---
    df_day = entry["df"]

    num_cols = [
        c for c in df_day.columns
        if c not in HIDE_ALWAYS
        and pd.api.types.is_numeric_dtype(df_day[c])
        and df_day[c].notna().any()
    ]
    if not num_cols:
        st.info("Нет числовых колонок для отображения.")
        return

    # Интервал усреднения
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

    # Агрегация
    df_day_num = df_day[num_cols]
    df_mean = aggregate_by(df_day_num, rule=agg_rule)["mean"]

    theme_base = st.get_option("theme.base") or "light"

    # Сводный график
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

    # Группы
    all_token_daily = f"{ALL_TOKEN}_{day_key}_{agg_rule}"
    render_power_group(df_mean, PLOT_HEIGHT, theme_base, all_token_daily)
    render_group(
        "Токи фаз L1–L3",
        "daily_grp_curr",
        df_mean,
        ["Irms_L1", "Irms_L2", "Irms_L3"],
        PLOT_HEIGHT,
        theme_base,
        all_token_daily,
    )
    render_group(
        "Напряжение (фазное) L1–L3",
        "daily_grp_urms",
        df_mean,
        ["Urms_L1", "Urms_L2", "Urms_L3"],
        PLOT_HEIGHT,
        theme_base,
        all_token_daily,
    )
    render_group(
        "Напряжение (линейное) L1-L2 / L2-L3 / L3-L1",
        "daily_grp_uline",
        df_mean,
        ["U_L1_L2", "U_L2_L3", "U_L3_L1"],
        PLOT_HEIGHT,
        theme_base,
        all_token_daily,
    )
    render_group(
        "Коэффициент мощности (PF)",
        "daily_grp_pf",
        df_mean,
        ["pf_total", "pf_L1", "pf_L2", "pf_L3"],
        PLOT_HEIGHT,
        theme_base,
        all_token_daily,
    )

    freq_cols = [
        c for c in df_mean.columns
        if pd.api.types.is_numeric_dtype(df_mean[c]) and (
            ("freq" in c.lower()) or ("frequency" in c.lower()) or ("hz" in c.lower()) or (c.lower() == "f")
        )
    ]
    if freq_cols:
        render_group("Частота сети", "daily_grp_freq", df_mean, freq_cols, PLOT_HEIGHT, theme_base, all_token_daily)
