# views/statistical.py
from __future__ import annotations

import io
import json
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.data_io import read_text_s3
from core.s3_paths import build_root_key


_STAT_HEIGHT = 560

# Фиксированные цвета (не зависят от порядка отображения трасс)
_LINE_COLORS: Dict[str, str] = {
    "50%": "#1f77b4",
    "90%": "#ff7f0e",
    "95%": "#9467bd",
    "99%": "#d62728",
    "median": "#2ca02c",
    "threshold": "#7f7f7f",
}

# 5 линий "Мощность" (фиксированные разные цвета, совпадают с маркерами в чекбоксах)
_THRESHOLDS: List[Tuple[str, str]] = [
    ("🔴", "#d62728"),
    ("🔵", "#1f77b4"),
    ("🟠", "#ff7f0e"),
    ("🟣", "#9467bd"),
    ("🟤", "#8c564b"),
]

# Вложенные серые области для интервалов (внешние светлее, внутренние темнее)
_FILL_COLORS: Dict[str, str] = {
    "99%": "rgba(0,0,0,0.06)",
    "95%": "rgba(0,0,0,0.09)",
    "90%": "rgba(0,0,0,0.12)",
    "50%": "rgba(0,0,0,0.16)",
}

# Подписи (для чекбоксов) -> (нижняя колонка, верхняя колонка)
_INTERVALS: List[Tuple[str, str, str]] = [
    ("50%", "P25", "P75"),
    ("90%", "P5", "P95"),
    ("95%", "P2.5", "P97.5"),
    ("99%", "P0.5", "P99.5"),
]

# Порядок интервалов от самого широкого к самому узкому (для вложенных заливок)
_FILL_ORDER: List[str] = ["99%", "95%", "90%", "50%"]


def _theme_params(theme_base: str | None) -> Dict[str, str]:
    base = (theme_base or "light").lower()
    if base == "dark":
        return {
            "template": "plotly_dark",
            "bg": "#0b0f14",
            "grid": "rgba(160,160,160,0.25)",
        }
    return {
        "template": "plotly_white",
        "bg": "#ffffff",
        "grid": "rgba(0,0,0,0.12)",
    }


def _read_stat_state() -> dict:
    txt = read_text_s3(build_root_key("Stat/state.json"))
    if not txt:
        return {}
    try:
        return json.loads(txt)
    except Exception:
        return {}


def _read_stat_csv(filename: str) -> pd.DataFrame | None:
    txt = read_text_s3(build_root_key(f"Stat/{filename}"))
    if not txt:
        return None

    try:
        df = pd.read_csv(io.StringIO(txt), sep=";", decimal=",")
    except Exception:
        try:
            df = pd.read_csv(io.StringIO(txt))
        except Exception:
            return None

    if df is None or df.empty:
        return None

    if "time" not in df.columns:
        return None

    # Ось X: фиктивная дата + время суток (HH:MM)
    t = df["time"].astype(str).str.strip()
    tt = pd.to_datetime(t, format="%H:%M", errors="coerce")
    if tt.isna().all():
        return None

    base = pd.Timestamp("2000-01-01")
    x = base + pd.to_timedelta(tt.dt.hour.fillna(0).astype(int), unit="h") + pd.to_timedelta(
        tt.dt.minute.fillna(0).astype(int), unit="m"
    )

    out = df.drop(columns=["time"]).copy()

    # Приводим числовые значения (на всякий случай, если что-то пришло строками)
    for c in out.columns:
        if not pd.api.types.is_numeric_dtype(out[c]):
            s = out[c].astype(str).str.replace(" ", "", regex=False).str.replace(",", ".", regex=False)
            out[c] = pd.to_numeric(s, errors="coerce")

    out.index = x
    out = out.sort_index()

    return out


def _iter_enabled_intervals_for_fill(enabled: Dict[str, bool]) -> List[Tuple[str, str, str]]:
    """Интервалы для вложенных заливок: от самого широкого к самому узкому.

    Серые области показываются всегда (не зависят от чекбоксов линий).
    """
    label_to_bounds = {lbl: (low, high) for lbl, low, high in _INTERVALS}
    out: List[Tuple[str, str, str]] = []
    for lbl in _FILL_ORDER:
        if lbl in label_to_bounds:
            low, high = label_to_bounds[lbl]
            out.append((lbl, low, high))
    return out


def _compute_y_max(df: pd.DataFrame, cols: List[str]) -> float:
    vals: List[float] = []
    for c in cols:
        if c in df.columns:
            try:
                m = float(pd.to_numeric(df[c], errors="coerce").max())
                if pd.notna(m):
                    vals.append(m)
            except Exception:
                pass
    y_max = max(vals) if vals else 0.0
    if not np.isfinite(y_max) or y_max <= 0:
        return 0.0
    return y_max


def _compute_global_y_max(
    dfs: List[pd.DataFrame | None],
    *,
    enabled: Dict[str, bool],
    show_median: bool,
    threshold_values: List[float],
) -> float:
    # Серые области показываются всегда, поэтому масштаб Y берём по верхним границам всех интервалов
    # (плюс медиана/пороги, если они включены).
    cols: List[str] = [high_c for _lbl, _low_c, high_c in _INTERVALS]
    if show_median:
        cols.append("P50")

    mx = 0.0
    for df in dfs:
        if df is None or df.empty:
            continue
        mx = max(mx, _compute_y_max(df, cols))

    if threshold_values:
        mx = max(mx, max(threshold_values))

    if not np.isfinite(mx) or mx <= 0:
        return 1.0
    return mx


def _make_figure(
    df: pd.DataFrame,
    *,
    title: str,
    agg_minutes: int | None,
    target_col: str,
    enabled: Dict[str, bool],
    show_median: bool,
    thresholds: List[Tuple[int, float]],
    y_max_global: float,
    theme_base: str | None,
) -> go.Figure:
    params = _theme_params(theme_base)

    fig = go.Figure()

    # Вложенные серые заливки интервалов (показываются всегда)
    for lbl, low_c, high_c in _iter_enabled_intervals_for_fill(enabled):
        if low_c in df.columns and high_c in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df[low_c],
                    mode="lines",
                    name=f"__fill_{lbl}_low__",
                    line=dict(width=0),
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df[high_c],
                    mode="lines",
                    name=f"__fill_{lbl}_high__",
                    line=dict(width=0),
                    showlegend=False,
                    hoverinfo="skip",
                    fill="tonexty",
                    fillcolor=_FILL_COLORS.get(lbl, "rgba(0,0,0,0.12)"),
                )
            )

    # Линии интервалов (по чекбоксам)
    for lbl, low_c, high_c in _INTERVALS:
        if not enabled.get(lbl, False):
            continue
        color = _LINE_COLORS.get(lbl, None)
        if low_c in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df[low_c],
                    mode="lines",
                    name=f"{lbl} (нижняя)",
                    line=dict(width=1, color=color),
                )
            )
        if high_c in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df[high_c],
                    mode="lines",
                    name=f"{lbl} (верхняя)",
                    line=dict(width=1, color=color),
                )
            )

    # Медиана
    if show_median and "P50" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["P50"],
                mode="lines",
                name="Медиана",
                line=dict(width=1, color=_LINE_COLORS.get("median")),
            )
        )

    # Горизонтальные линии (пороги)
    if thresholds:
        for i, v in thresholds:
            if v <= 0 or not np.isfinite(v):
                continue
            color = _THRESHOLDS[i - 1][1] if 1 <= i <= len(_THRESHOLDS) else _LINE_COLORS.get("threshold")
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=[v] * len(df.index),
                    mode="lines",
                    name=f"Мощность: {v:g} кВт",
                    showlegend=False,
                    line=dict(width=3, dash="dash", color=color),
                )
            )

    # Заголовок
    if agg_minutes is not None:
        plot_title = f"{title} (усреднение {int(agg_minutes)} мин)"
    else:
        plot_title = title

    # Ось Y: общий диапазон для weekday/weekend
    y_max = y_max_global

    fig.update_layout(
        template=params["template"],
        autosize=True,
        height=_STAT_HEIGHT,
        title=plot_title,
        xaxis_title="Время суток",
        yaxis_title=f"{target_col}, кВт",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.0),
        margin=dict(l=60, r=20, t=70, b=60),
        plot_bgcolor=params["bg"],
        paper_bgcolor=params["bg"],
        yaxis=dict(range=[0, y_max * 1.05], showgrid=True, gridcolor=params["grid"]),
        xaxis=dict(showgrid=True, gridcolor=params["grid"]),
    )

    # Ось X: подпись каждого часа
    fig.update_xaxes(
        tickmode="linear",
        tick0="2000-01-01 00:00:00",
        dtick=60 * 60 * 1000,
        tickformat="%H:%M",
    )

    return fig


def render_statistical_mode() -> None:
    st.markdown("### Статистические")

    # Минимальная дистанция между графиками (только для этой вкладки)
    st.markdown(
        """
        <style>
        div[data-testid='stPlotlyChart'] { margin-top: 0rem; margin-bottom: 0rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Чекбоксы (общие для обоих графиков)
    c0, c1, c2, c3, c4 = st.columns(5)
    with c0:
        cb_med = st.checkbox("Медиана", value=False, key="stat_cb_median")
    with c1:
        cb_50 = st.checkbox("50%", value=False, key="stat_cb_50")
    with c2:
        cb_90 = st.checkbox("90%", value=False, key="stat_cb_90")
    with c3:
        cb_95 = st.checkbox("95%", value=False, key="stat_cb_95")
    with c4:
        cb_99 = st.checkbox("99%", value=False, key="stat_cb_99")

    enabled: Dict[str, bool] = {
        "50%": bool(cb_50),
        "90%": bool(cb_90),
        "95%": bool(cb_95),
        "99%": bool(cb_99),
    }

    show_median = bool(cb_med)

    # 5 чекбоксов + числовые поля для горизонтальных линий "Мощность" (кВт)
    thresholds: List[Tuple[int, float]] = []
    threshold_values: List[float] = []
    for i, (emoji, _color) in enumerate(_THRESHOLDS, start=1):
        col_cb, col_inp, _sp = st.columns([1.25, 0.6, 6.0])
        with col_cb:
            en = st.checkbox(f"{emoji} Мощность (кВт)", value=False, key=f"stat_thr_en_{i}")
        with col_inp:
            v = st.number_input(
                f"thr_{i}_kw",
                min_value=0.0,
                value=0.0,
                step=1.0,
                key=f"stat_thr_val_{i}",
                label_visibility="collapsed",
            )
        try:
            vv = float(v)
        except Exception:
            vv = 0.0
        if en and vv > 0 and np.isfinite(vv):
            thresholds.append((i, vv))
            threshold_values.append(vv)

    state = _read_stat_state()
    agg_minutes = state.get("agg_minutes", None)
    try:
        agg_minutes = int(agg_minutes) if agg_minutes is not None else None
    except Exception:
        agg_minutes = None

    target_col = str(state.get("target_column") or "P_total")

    theme_base = st.get_option("theme.base") or "light"

    df_weekday = _read_stat_csv("weekday.csv")
    df_weekend = _read_stat_csv("weekend.csv")

    shown = 0
    y_max = _compute_global_y_max(
        [df_weekday, df_weekend],
        enabled=enabled,
        show_median=show_median,
        threshold_values=threshold_values,
    )

    if df_weekday is not None and not df_weekday.empty:
        fig_wd = _make_figure(
            df_weekday,
            title="Будние дни",
            agg_minutes=agg_minutes,
            target_col=target_col,
            enabled=enabled,
            show_median=show_median,
            thresholds=thresholds,
            y_max_global=y_max,
            theme_base=theme_base,
        )
        st.plotly_chart(fig_wd, use_container_width=True, config={"responsive": True}, key="stat_weekday")
        shown += 1

    if df_weekend is not None and not df_weekend.empty:
        fig_we = _make_figure(
            df_weekend,
            title="Выходные/праздничные",
            agg_minutes=agg_minutes,
            target_col=target_col,
            enabled=enabled,
            show_median=show_median,
            thresholds=thresholds,
            y_max_global=y_max,
            theme_base=theme_base,
        )
        st.plotly_chart(fig_we, use_container_width=True, config={"responsive": True}, key="stat_weekend")
        shown += 1

    if shown == 0:
        st.info("Нет данных для статистики (не найдены файлы в папке Stat текущего проекта).")
