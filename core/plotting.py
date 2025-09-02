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
            "grid": "#1a2430",
            "colorway": qual.Plotly,  # норм палитра и в тёмной теме
        }
    else:
        return {
            "template": "plotly_white",
            "bg": "#ffffff",
            "grid": "#e6e6e6",
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
      - одна базовая левая ось (для серий без нормирования),
      - любые доп. оси слева для серий из separate_axes,
      - без подписей осей, цифры доп. осей окрашены в цвет соответствующей серии,
      - легенда снизу.
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
        xaxis=dict(title=None),                     # без "Время"
        yaxis=dict(title=None, gridcolor=params["grid"]),  # без подписи оси Y
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

    df_plot = _stride(df[[c for c in series if c in df.columns]], MAX_POINTS_MAIN)

    # Цвета серий (по порядку добавления)
    color_cycle = list(params["colorway"])
    color_map: Dict[str, str] = {}
    for i, c in enumerate(series):
        color_map[c] = color_cycle[i % len(color_cycle)]

    # Базовая ось (y) — для «ненормированных» серий
    base_series = [c for c in series if c not in separate_axes]

    for c in base_series:
        if c not in df_plot.columns:
            continue
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

    # Дополнительные ЛЕВЫЕ оси для «нормированных» серий
    # Размещаем внутри области графика «лесенкой» — position слегка сдвигается вправо
    pos_start = 0.02
    pos_step = 0.05  # чем больше осей, тем ближе к графику
    axis_idx = 1     # yaxis -> base; дополнительные начнём с yaxis2

    for j, c in enumerate([s for s in series if s in separate_axes]):
        if c not in df_plot.columns:
            continue
        axis_idx += 1
        yaxis_name = f"yaxis{axis_idx}"
        yref = f"y{axis_idx}"
        pos_val = pos_start + j * pos_step
        if pos_val > 0.95:
            pos_val = 0.95  # на всякий случай, чтобы не вылезти

        # Ось без заголовка, только цифры, цвет цифр = цвет линии
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

    return fig


def group_panel(
    df: pd.DataFrame,
    cols: List[str],
    height: int,
    theme_base: str | None = None,
) -> go.Figure:
    """Группа: одна левая ось, без подписей осей; легенда снизу. Показываем все переданные серии."""
    params = _theme_params(theme_base)

    fig = go.Figure()
    fig.update_layout(
        template=params["template"],
        autosize=True,
        height=height,
        margin=dict(t=26, r=20, b=80, l=50),
        plot_bgcolor=params["bg"],
        paper_bgcolor=params["bg"],
        xaxis=dict(title=None),                     # без "Время"
        yaxis=dict(title=None, gridcolor=params["grid"]),
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

    for i, c in enumerate(present):
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
