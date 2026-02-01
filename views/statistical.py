# views/statistical.py
from __future__ import annotations

import io
import json
from typing import Dict, List, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.data_io import read_text_s3
from core.s3_paths import build_root_key


_STAT_HEIGHT = 560
_FILL_COLOR = "rgba(0,0,0,0.12)"

# Подписи (для чекбоксов) -> (нижняя колонка, верхняя колонка)
_INTERVALS: List[Tuple[str, str, str]] = [
    ("50%", "P25", "P75"),
    ("90%", "P5", "P95"),
    ("95%", "P2.5", "P97.5"),
    ("99%", "P0.5", "P99.5"),
]

# Приоритет для заливки (самый широкий интервал выигрывает)
_FILL_PRIORITY: List[str] = ["99%", "95%", "90%", "50%"]


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


def _pick_fill_bounds(enabled: Dict[str, bool]) -> Tuple[str, str] | None:
    if not any(enabled.values()):
        return None

    label_to_bounds = {lbl: (low, high) for lbl, low, high in _INTERVALS}
    for lbl in _FILL_PRIORITY:
        if enabled.get(lbl, False):
            low, high = label_to_bounds[lbl]
            return low, high
    return None


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
    y_max = max(vals) if vals else 1.0
    if not pd.isfinite(y_max) or y_max <= 0:
        y_max = 1.0
    return y_max


def _make_figure(
    df: pd.DataFrame,
    *,
    title: str,
    agg_minutes: int | None,
    target_col: str,
    enabled: Dict[str, bool],
    theme_base: str | None,
) -> go.Figure:
    params = _theme_params(theme_base)

    fig = go.Figure()

    fill_bounds = _pick_fill_bounds(enabled)

    # Заливка: только если хотя бы один интервал включён
    if fill_bounds is not None:
        low_c, high_c = fill_bounds
        if low_c in df.columns and high_c in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df[low_c],
                    mode="lines",
                    name="__fill_low__",
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
                    name="__fill_high__",
                    line=dict(width=0),
                    showlegend=False,
                    hoverinfo="skip",
                    fill="tonexty",
                    fillcolor=_FILL_COLOR,
                )
            )

    # Линии интервалов (по чекбоксам)
    for lbl, low_c, high_c in _INTERVALS:
        if not enabled.get(lbl, False):
            continue
        if low_c in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df[low_c],
                    mode="lines",
                    name=f"{lbl} (нижняя)",
                    line=dict(width=1),
                )
            )
        if high_c in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df[high_c],
                    mode="lines",
                    name=f"{lbl} (верхняя)",
                    line=dict(width=1),
                )
            )

    # Медиана
    if "P50" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["P50"],
                mode="lines",
                name="Медиана (P50)",
                line=dict(width=1),
            )
        )

    # Заголовок
    if agg_minutes is not None:
        plot_title = f"{title} (усреднение {int(agg_minutes)} мин)"
    else:
        plot_title = title

    # Ось Y: от нуля (как в plot_report.py)
    y_cols: List[str] = ["P50"]
    if fill_bounds is not None:
        y_cols += [fill_bounds[1]]
    for lbl, _, high_c in _INTERVALS:
        if enabled.get(lbl, False):
            y_cols.append(high_c)
    y_max = _compute_y_max(df, y_cols)

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

    # Чекбоксы (общие для обоих графиков)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        cb_50 = st.checkbox("50%", value=False, key="stat_cb_50")
    with c2:
        cb_90 = st.checkbox("90%", value=True, key="stat_cb_90")
    with c3:
        cb_95 = st.checkbox("95%", value=False, key="stat_cb_95")
    with c4:
        cb_99 = st.checkbox("99%", value=False, key="stat_cb_99")

    enabled = {
        "50%": bool(cb_50),
        "90%": bool(cb_90),
        "95%": bool(cb_95),
        "99%": bool(cb_99),
    }

    state = _read_stat_state()
    agg_minutes = state.get("agg_minutes", None)
    try:
        agg_minutes = int(agg_minutes) if agg_minutes is not None else None
    except Exception:
        agg_minutes = None

    target_col = str(state.get("target_column") or "P_total")

    theme_base = st.get_option("theme.base") or "light"

    shown = 0

    df_weekday = _read_stat_csv("weekday.csv")
    if df_weekday is not None and not df_weekday.empty:
        fig_wd = _make_figure(
            df_weekday,
            title="Будние дни",
            agg_minutes=agg_minutes,
            target_col=target_col,
            enabled=enabled,
            theme_base=theme_base,
        )
        st.plotly_chart(fig_wd, use_container_width=True, config={"responsive": True}, key="stat_weekday")
        shown += 1

    df_weekend = _read_stat_csv("weekend.csv")
    if df_weekend is not None and not df_weekend.empty:
        fig_we = _make_figure(
            df_weekend,
            title="Выходные/праздничные",
            agg_minutes=agg_minutes,
            target_col=target_col,
            enabled=enabled,
            theme_base=theme_base,
        )
        st.plotly_chart(fig_we, use_container_width=True, config={"responsive": True}, key="stat_weekend")
        shown += 1

    if shown == 0:
        st.info("Нет данных для статистики (не найдены файлы в папке Stat текущего проекта).")
