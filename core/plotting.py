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
    Сводный график:
      - базовая левая ось (для серий без галочки),
      - любые дополнительные ЛЕВЫЕ оси для серий из separate_axes,
      - у доп. осей только цифры (цвет = цвет линии), без заголовков,
      - легенда снизу,
      - если есть separate_axes -> рисуем «бумажную» сетку (paper), а гриды осей выключаем.
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

    # Стабильные цвета: цифры осей = цвет линии
    cw = list(params["colorway"])
    color_map: Dict[str, str] = {c: cw[i % len(cw)] for i, c in enumerate(present)}

    # 1) Базовые серии -> обычная ось y
    base_series = [c for c in present if c not in separate_axes]
    for c in base_series:
        fig.add_trace(
            go.Scattergl(
                x=df_plot.index, y=df_plot[c], mode="lines", name=c,
                line=dict(color=color_map[c]),
                hovertemplate="%{x}<br>"+c+": %{y}<extra></extra>",
            )
        )

    # 2) Доп. ЛЕВЫЕ оси для отмеченных серий — слева -> вправо
    pos_start = 0.02   # первая прямо у левого края
    pos_step  = 0.05   # следующие чуть правее
    pos_max   = 0.95

    axis_idx = 1  # yaxis — базовая; дальше yaxis2, yaxis3, ...
    for j, c in enumerate([s for s in present if s in separate_axes]):
        axis_idx += 1
        yaxis_name = f"yaxis{axis_idx}"
        yref = f"y{axis_idx}"

        pos_val = min(pos_max, pos_start + j * pos_step)

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
                x=df_plot.index, y=df_plot[c], mode="lines", name=c, yaxis=yref,
                line=dict(color=color_map[c]),
                hovertemplate="%{x}<br>"+c+": %{y}<extra></extra>",
            )
        )

    # 3) «Бумажная» сетка, если есть отдельные оси
    if len(separate_axes) > 0:
        shapes = []
        for y in (0.2, 0.4, 0.6, 0.8):
            shapes.append(
                dict(
                    type="line", xref="paper", yref="paper",
                    x0=0, x1=1, y0=y, y1=y,
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

    df_plot = _stride(df[present], MAX_POINTS_GROUP)

    for c in present:
        fig.add_trace(
            go.Scattergl(
                x=df_plot.index, y=df_plot[c], mode="lines", name=c,
                hovertemplate="%{x}<br>"+c+": %{y}<extra></extra>",
            )
        )

    return fig
