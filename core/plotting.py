# core/plotting.py
from __future__ import annotations

from typing import List, Set, Dict
from math import ceil

import pandas as pd
import plotly.graph_objects as go
from plotly.colors import qualitative as qual

from core.config import (
    MAX_POINTS_MAIN,
    MAX_POINTS_GROUP,
    MAX_POINTS_MINUTE_MAIN,
    MAX_POINTS_MINUTE_GROUP,
)


def _stride(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    if len(df) <= max_points:
        return df
    step = ceil(len(df) / max_points)
    return df.iloc[::step].copy()


def _theme_params(theme_base: str | None):
    base = (theme_base or "light").lower()
    if base == "dark":
        return {
            "template": "plotly_dark",
            "bg": "#0b0f14",
            "grid": "rgba(160,160,160,0.25)",
            "colorway": qual.Plotly,
        }
    else:
        return {
            "template": "plotly_white",
            "bg": "#ffffff",
            "grid": "rgba(0,0,0,0.12)",
            "colorway": qual.Plotly,
        }


def main_chart(
    df: pd.DataFrame,
    series: List[str],
    height: int,
    theme_base: str | None = None,
    separate_axes: Set[str] | None = None,
) -> go.Figure:
    """
    Сводный график (часовой режим):
      - базовая левая ось (для серий без галочки),
      - доп. ЛЕВЫЕ оси для серий из separate_axes,
      - легенда снизу,
      - при отдельных осях рисуем «бумажную» сетку (paper).
    """
    params = _theme_params(theme_base)
    separate_axes = separate_axes or set()

    fig = go.Figure()
    fig.update_layout(
        template=params["template"],
        autosize=True,
        height=height,
        margin=dict(t=30, r=20, b=90, l=55),
        plot_bgcolor=params["bg"],
        paper_bgcolor=params["bg"],
        xaxis=dict(title=None),
        yaxis=dict(title=None, showgrid=(len(separate_axes) == 0), gridcolor=params["grid"]),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.15,
            x=0.5,
            xanchor="center",
            title=None,
        ),
        colorway=list(params["colorway"]),
    )

    if not series:
        return fig

    present = [c for c in series if c in df.columns]
    if not present:
        return fig
    df_plot = _stride(df[present], MAX_POINTS_MAIN)

    cw = list(params["colorway"])
    color_map: Dict[str, str] = {c: cw[i % len(cw)] for i, c in enumerate(present)}

    # Базовые серии
    base_series = [c for c in present if c not in separate_axes]
    for c in base_series:
        fig.add_trace(
            go.Scattergl(
                x=df_plot.index,
                y=df_plot[c],
                mode="lines",
                name=c,
                line=dict(color=color_map[c]),
                hovertemplate="%{x}<br>" + c + ": %{y}<extra></extra>",
            )
        )

    # Доп. ЛЕВЫЕ оси
    pos_start = 0.02
    pos_step = 0.05
    pos_max = 0.95

    axis_idx = 1
    for j, c in enumerate([s for s in present if s in separate_axes]):
        axis_idx += 1
        yaxis_name = f"yaxis{axis_idx}"
        yref = f"y{axis_idx}"
        pos_val = min(pos_max, pos_start + j * pos_step)

        fig.update_layout(
            **{
                yaxis_name: dict(
                    overlaying="y",
                    anchor="free",
                    side="left",
                    position=pos_val,
                    showgrid=False,
                    zeroline=False,
                    title=None,
                    tickfont=dict(color=color_map[c]),
                )
            }
        )

        fig.add_trace(
            go.Scattergl(
                x=df_plot.index,
                y=df_plot[c],
                mode="lines",
                name=c,
                yaxis=yref,
                line=dict(color=color_map[c]),
                hovertemplate="%{x}<br>" + c + ": %{y}<extra></extra>",
            )
        )

    # «Бумажная» сетка, если есть отдельные оси
    if len(separate_axes) > 0:
        shapes = []
        for y in (0.2, 0.4, 0.6, 0.8):
            shapes.append(
                dict(
                    type="line",
                    xref="paper",
                    yref="paper",
                    x0=0,
                    x1=1,
                    y0=y,
                    y1=y,
                    line=dict(color=params["grid"], width=1, dash="dot"),
                    layer="below",
                )
            )
        fig.update_layout(shapes=shapes)

    return fig


def group_panel(
    df: pd.DataFrame,
    cols: List[str],
    height: int,
    theme_base: str | None = None,
    *,
    max_points: int | None = None,
) -> go.Figure:
    """Группа: одна левая ось, без подписей; легенда снизу."""
    params = _theme_params(theme_base)

    fig = go.Figure()
    fig.update_layout(
        template=params["template"],
        autosize=True,
        height=height,
        margin=dict(t=26, r=20, b=80, l=55),
        plot_bgcolor=params["bg"],
        paper_bgcolor=params["bg"],
        xaxis=dict(title=None),
        yaxis=dict(title=None, showgrid=True, gridcolor=params["grid"]),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.12,
            x=0.5,
            xanchor="center",
            title=None,
        ),
        colorway=list(params["colorway"]),
    )

    present = [c for c in cols if c in df.columns]
    if not present:
        return fig

    mp = MAX_POINTS_GROUP if max_points is None else int(max_points)
    df_plot = _stride(df[present], mp)

    for c in present:
        fig.add_trace(
            go.Scattergl(
                x=df_plot.index,
                y=df_plot[c],
                mode="lines",
                name=c,
                hovertemplate="%{x}<br>" + c + ": %{y}<extra></extra>",
            )
        )

    return fig


def minutely_summary_chart(
    df: pd.DataFrame,
    height: int,
    theme_base: str | None = None,
    *,
    u_prefix: str = "Upeak_",
    i_prefix: str = "Ipeak_",
) -> go.Figure:
    """
    Минутный сводный (Ipeak+Upeak):
      - Upeak_* на левой оси (y),
      - Ipeak_* на правой оси (y2),
      - рассинхрон допускается (df уже объединён outer-join'ом),
      - лимиты точек отдельные (MAX_POINTS_MINUTE_MAIN).
    """
    params = _theme_params(theme_base)

    fig = go.Figure()
    fig.update_layout(
        template=params["template"],
        autosize=True,
        height=height,
        margin=dict(t=30, r=55, b=90, l=55),
        plot_bgcolor=params["bg"],
        paper_bgcolor=params["bg"],
        xaxis=dict(title=None),
        yaxis=dict(title=None, showgrid=True, gridcolor=params["grid"]),
        yaxis2=dict(
            title=None,
            overlaying="y",
            side="right",
            showgrid=False,
            zeroline=False,
        ),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.15,
            x=0.5,
            xanchor="center",
            title=None,
        ),
        colorway=list(params["colorway"]),
    )

    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return fig

    u_cols = [c for c in df.columns if str(c).startswith(u_prefix)]
    i_cols = [c for c in df.columns if str(c).startswith(i_prefix)]
    if not u_cols and not i_cols:
        return fig

    # порядок: сначала U (слева), затем I (справа) — стабильное назначение цветов
    ordered = u_cols + i_cols
    df_plot = _stride(df[ordered], MAX_POINTS_MINUTE_MAIN)

    cw = list(params["colorway"])
    color_map: Dict[str, str] = {c: cw[i % len(cw)] for i, c in enumerate(ordered)}

    for c in u_cols:
        fig.add_trace(
            go.Scattergl(
                x=df_plot.index,
                y=df_plot[c],
                mode="lines",
                name=c,
                yaxis="y",
                line=dict(color=color_map[c]),
                hovertemplate="%{x}<br>" + c + ": %{y}<extra></extra>",
            )
        )

    for c in i_cols:
        fig.add_trace(
            go.Scattergl(
                x=df_plot.index,
                y=df_plot[c],
                mode="lines",
                name=c,
                yaxis="y2",
                line=dict(color=color_map[c]),
                hovertemplate="%{x}<br>" + c + ": %{y}<extra></extra>",
            )
        )

    return fig


def daily_main_chart(
    df_mean: pd.DataFrame,
    df_p95: pd.DataFrame | None,
    df_max: pd.DataFrame | None,
    df_min: pd.DataFrame | None,
    series: List[str],
    height: int,
    theme_base: str | None = None,
    separate_axes: Set[str] | None = None,
    show_p95: bool = False,
    show_extrema: bool = False,
) -> go.Figure:
    """
    Суточный сводный: линия mean; (опционально p95 и маркеры max/min — выключены по умолчанию).
    Логику множества осей слева сохраняем как в main_chart.
    """
    params = _theme_params(theme_base)
    separate_axes = separate_axes or set()

    fig = go.Figure()
    fig.update_layout(
        template=params["template"],
        autosize=True,
        height=height,
        margin=dict(t=30, r=20, b=90, l=55),
        plot_bgcolor=params["bg"],
        paper_bgcolor=params["bg"],
        xaxis=dict(title=None),
        yaxis=dict(title=None, showgrid=(len(separate_axes) == 0), gridcolor=params["grid"]),
        legend=dict(orientation="h", yanchor="top", y=-0.15, x=0.5, xanchor="center", title=None),
        colorway=list(params["colorway"]),
    )

    if df_mean is None or df_mean.empty or not series:
        return fig

    present = [c for c in series if c in df_mean.columns]
    if not present:
        return fig

    cw = list(params["colorway"])
    color_map: Dict[str, str] = {c: cw[i % len(cw)] for i, c in enumerate(present)}

    # Базовые серии (mean) на общей оси
    base_series = [c for c in present if c not in separate_axes]
    for c in base_series:
        fig.add_trace(
            go.Scattergl(
                x=df_mean.index,
                y=df_mean[c],
                mode="lines",
                name=f"{c}",
                line=dict(color=color_map[c]),
                hovertemplate="%{x}<br>" + c + ": %{y}<extra></extra>",
            )
        )

    # Дополнительные оси слева
    pos_start, pos_step, pos_max = 0.02, 0.05, 0.95
    axis_idx = 1
    for j, c in enumerate([s for s in present if s in separate_axes]):
        axis_idx += 1
        yaxis_name, yref = f"yaxis{axis_idx}", f"y{axis_idx}"
        fig.update_layout(
            **{
                yaxis_name: dict(
                    overlaying="y",
                    anchor="free",
                    side="left",
                    position=min(pos_max, pos_start + j * pos_step),
                    showgrid=False,
                    zeroline=False,
                    title=None,
                    tickfont=dict(color=color_map[c]),
                )
            }
        )
        fig.add_trace(
            go.Scattergl(
                x=df_mean.index,
                y=df_mean[c],
                mode="lines",
                name=f"{c}",
                yaxis=yref,
                line=dict(color=color_map[c]),
                hovertemplate="%{x}<br>" + c + ": %{y}<extra></extra>",
            )
        )

    if len(separate_axes) > 0:
        shapes = []
        for y in (0.2, 0.4, 0.6, 0.8):
            shapes.append(
                dict(
                    type="line",
                    xref="paper",
                    yref="paper",
                    x0=0,
                    x1=1,
                    y0=y,
                    y1=y,
                    line=dict(color=params["grid"], width=1, dash="dot"),
                    layer="below",
                )
            )
        fig.update_layout(shapes=shapes)

    return fig
