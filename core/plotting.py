from __future__ import annotations
import plotly.graph_objects as go
import pandas as pd
from typing import Dict, List
from core.config import MAX_POINTS_MAIN, MAX_POINTS_GROUP
from core.downsample import stride


def main_chart(df: pd.DataFrame, series: List[str], axis_map: Dict[str, str], height: int) -> go.Figure:
    """Верхний график с двумя осями Y (A1/A2)."""
    if not series:
        fig = go.Figure()
        fig.update_layout(height=height)
        return fig

    df_plot = stride(df[series], MAX_POINTS_MAIN)

    fig = go.Figure()
    fig.update_layout(
        margin=dict(t=36, r=16, b=40, l=60),
        height=height,
        plot_bgcolor="#0b0f14",
        paper_bgcolor="#0b0f14",
        legend=dict(orientation="h"),
        xaxis=dict(title=dict(text="Время")),
        yaxis=dict(title=dict(text="A1"), gridcolor="#1a2430"),
        yaxis2=dict(title=dict(text="A2"), overlaying="y", side="right"),
    )

    # Заголовки осей — по первой серии на каждой оси
    a1_named = False
    a2_named = False

    for col in series:
        yref = "y" if axis_map.get(col, "A1") == "A1" else "y2"
        fig.add_trace(
            go.Scattergl(
                x=df_plot.index,
                y=df_plot[col],
                mode="lines",
                name=col,
                yaxis=yref,
                hovertemplate="%{x}<br>" + col + ": %{y}<extra></extra>",
            )
        )
        if yref == "y" and not a1_named:
            fig.update_layout(yaxis=dict(title=dict(text=col)))
            a1_named = True
        if yref == "y2" and not a2_named:
            fig.update_layout(yaxis2=dict(title=dict(text=col)))
            a2_named = True

    return fig


def group_panel(df: pd.DataFrame, chosen_cols: List[str], height: int, two_axes: bool) -> go.Figure:
    """Панель группы: одна ось или две (Q* на правую)."""
    if not chosen_cols:
        fig = go.Figure(); fig.update_layout(height=height); return fig

    df_plot = stride(df[chosen_cols], MAX_POINTS_GROUP)

    fig = go.Figure()
    fig.update_layout(
        margin=dict(t=26, r=16, b=36, l=60),
        height=height,
        plot_bgcolor="#0b0f14",
        paper_bgcolor="#0b0f14",
        showlegend=True,
        xaxis=dict(title="Время"),
    )

    if two_axes:
        left_cols = [c for c in chosen_cols if not c.startswith("Q")]
        right_cols = [c for c in chosen_cols if c.startswith("Q")]
        if not left_cols and right_cols:
            left_cols, right_cols = right_cols[:1], right_cols[1:]

        fig.update_layout(
            yaxis=dict(title=dict(text=(left_cols[0] if left_cols else "A1")), gridcolor="#1a2430"),
            yaxis2=dict(title=dict(text=(right_cols[0] if right_cols else "A2")), overlaying="y", side="right"),
        )
        for c in left_cols:
            fig.add_trace(go.Scattergl(x=df_plot.index, y=df_plot[c], mode="lines", name=c,
                                       hovertemplate="%{x}<br>"+c+": %{y}<extra></extra>"))
        for c in right_cols:
            fig.add_trace(go.Scattergl(x=df_plot.index, y=df_plot[c], mode="lines", name=c, yaxis="y2",
                                       hovertemplate="%{x}<br>"+c+": %{y}<extra></extra>"))
    else:
        fig.update_layout(yaxis=dict(title=dict(text=chosen_cols[0]), gridcolor="#1a2430"))
        for c in chosen_cols:
            fig.add_trace(go.Scattergl(x=df_plot.index, y=df_plot[c], mode="lines", name=c,
                                       hovertemplate="%{x}<br>"+c+": %{y}<extra></extra>"))

    return fig
