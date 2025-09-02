from __future__ import annotations
from typing import Dict, List
import pandas as pd
import plotly.graph_objects as go
from math import ceil

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
        }
    else:
        return {
            "template": "plotly_white",
            "bg": "#ffffff",
            "grid": "#e6e6e6",
        }

def main_chart(
    df: pd.DataFrame,
    series: List[str],
    height: int,
    theme_base: str | None = None,
) -> go.Figure:
    """Верхний график: одна левая ось Y, легенда снизу."""
    params = _theme_params(theme_base)
    if not series:
        fig = go.Figure()
        fig.update_layout(template=params["template"], height=height, autosize=True)
        return fig

    df_plot = _stride(df[series], MAX_POINTS_MAIN)

    fig = go.Figure()
    fig.update_layout(
        template=params["template"],
        autosize=True,
        height=height,
        margin=dict(t=30, r=20, b=90, l=60),
        plot_bgcolor=params["bg"],
        paper_bgcolor=params["bg"],
        xaxis=dict(title="Время"),
        yaxis=dict(title=series[0], gridcolor=params["grid"]),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.15,
            x=0.5,
            xanchor="center",
            title=None,
        ),
    )

    for c in series:
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

def group_panel(
    df: pd.DataFrame,
    cols: List[str],
    height: int,
    theme_base: str | None = None,
) -> go.Figure:
    """Панель группы: без чекбоксов, показываем все переданные серии; одна ось слева, легенда снизу."""
    params = _theme_params(theme_base)
    present = [c for c in cols if c in df.columns]
    if not present:
        fig = go.Figure()
        fig.update_layout(template=params["template"], height=height, autosize=True)
        return fig

    df_plot = _stride(df[present], MAX_POINTS_GROUP)

    fig = go.Figure()
    fig.update_layout(
        template=params["template"],
        autosize=True,
        height=height,
        margin=dict(t=26, r=20, b=80, l=60),
        plot_bgcolor=params["bg"],
        paper_bgcolor=params["bg"],
        xaxis=dict(title="Время"),
        yaxis=dict(title=present[0], gridcolor=params["grid"]),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.12,
            x=0.5,
            xanchor="center",
            title=None,
        ),
    )

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
