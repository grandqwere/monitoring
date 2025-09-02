from __future__ import annotations
from typing import List, Set, Dict
from math import ceil
import pandas as pd
import plotly.graph_objects as go
from plotly.colors import qualitative as qual

from core.config import MAX_POINTS_MAIN, MAX_POINTS_GROUP


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
            "paper_grid": "rgba(160,160,160,0.25)",
            "axis_grid": "rgba(100,100,100,0.25)",
            "colorway": qual.Plotly,
        }
    else:
        return {
            "template": "plotly_white",
            "bg": "#ffffff",
            "paper_grid": "rgba(0,0,0,0.12)",
            "axis_grid": "rgba(0,0,0,0.10)",
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
    Сводный график:
      - базовая левая ось (для серий без галочки) — цвет цифр равен цвету первой базовой серии;
      - дополнительные ЛЕВЫЕ оси для серий из separate_axes — все «прижаты» к левому краю,
        только цветные цифры, без заголовков/гридов;
      - если есть separate_axes -> рисуем «бумажную» сетку (shapes в paper-координатах);
      - легенда снизу; подписи осей скрыты.
    """
    params = _theme_params(theme_base)
    separate_axes = separate_axes or set()

    fig = go.Figure()
    fig.update_layout(
        template=params["template"],
        autosize=True,
        height=height,
        margin=dict(t=30, r=20, b=90, l=50),
        plot_bgcolor=params["bg"],
        paper_bgcolor=params["bg"],
        xaxis=dict(title=None),
        # showgrid у базовой оси включаем только если нет отдельных осей
        yaxis=dict(title=None, showgrid=(len(separate_axes) == 0), gridcolor=params["axis_grid"]),
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

    # цвет каждой серии (стабильно по порядку)
    cw = list(params["colorway"])
    color_map: Dict[str, str] = {c: cw[i % len(cw)] for i, c in enumerate(present)}

    # базовые серии (без галочки) -> обычная ось y
    base_series = [c for c in present if c not in separate_axes]
    for c in base_series:
        fig.add_trace(
            go.Scattergl(
                x=df_plot.index,
                y=df_plot[c],
                mode="lines",
                name=c,
                line=dict(color=color_map[c]),
                hovertemplate="%{x}<br>"+c+": %{y}<extra></extra>",
            )
        )

    # цвет цифр у базовой оси = цвет первой базовой серии (есть гарантия, что она есть)
    if base_series:
        fig.update_layout(yaxis=dict(tickfont=dict(color=color_map[base_series[0]])))

    # дополнительные ЛЕВЫЕ оси — все «прижаты» к левому краю (минимальный сдвиг, чтобы не съехать за границу)
    pos_min = 0.001
    pos_step = 0.003  # чуть-чуть «веером», но визуально у самого края

    axis_idx = 1  # yaxis — базовая; дальше yaxis2, yaxis3, ...
    for j, c in enumerate([s for s in present if s in separate_axes]):
        axis_idx += 1
        yaxis_name = f"yaxis{axis_idx}"
        yref = f"y{axis_idx}"
        pos_val = min(0.02, pos_min + j * pos_step)  # «прижато» к левому краю

        fig.update_layout(
            **{
                yaxis_name: dict(
                    overlaying="y",
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
                hovertemplate="%{x}<br>"+c+": %{y}<extra></extra>",
            )
        )

    # «бумажная» горизонтальная сетка, если есть отдельные оси
    if len(separate_axes) > 0:
        shapes = []
        for y in (0.2, 0.4, 0.6, 0.8):
            shapes.append(
                dict(
                    type="line",
                    xref="paper", yref="paper",
                    x0=0, x1=1, y0=y, y1=y,
                    line=dict(color=params["paper_grid"], width=1, dash="dot"),
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
) -> go.Figure:
    """Группа: одна левая ось, без подписей; легенда снизу."""
    params = _theme_params(theme_base)

    fig = go.Figure()
    fig.update_layout(
        template=params["template"],
        autosize=True,
        height=height,
        margin=dict(t=26, r=20, b=80, l=50),
        plot_bgcolor=params["bg"],
        paper_bgcolor=params["bg"],
        xaxis=dict(title=None),
        yaxis=dict(title=None, showgrid=True, gridcolor=params["axis_grid"]),
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

    df_plot = _stride(df[present], MAX_POINTS_GROUP)

    for c in present:
        fig.add_trace(
            go.Scattergl(
                x=df_plot.index,
                y=df_plot[c],
                mode="lines",
                name=c,
                hovertemplate="%{x}<br>"+c+": %{y}<extra></extra>",
            )
        )

    return fig
