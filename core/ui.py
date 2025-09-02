from __future__ import annotations
import streamlit as st
from typing import List, Dict
from core.config import AXIS_LABELS, DEFAULT_PRESET


def height_controls():
    main_height = st.slider("Высота верхнего графика, px", 700, 1200, 900, step=50)
    group_height = st.slider("Высота каждой панели внизу, px", 300, 700, 400, step=50)
    st.caption("Зум/панорамирование — колесо/drag, двойной клик — сброс, клик по легенде — скрыть серию.")
    return main_height, group_height


def series_selector(all_cols: List[str]) -> List[str]:
    preselect = [c for c in DEFAULT_PRESET if c in all_cols] or all_cols[:3]
    return st.multiselect("Добавить серии в верхний график", options=all_cols, default=preselect, key="main_select")


def axis_selector(selected_cols: List[str]) -> Dict[str, str]:
    st.write("Назначение осей Y для выбранных серий")
    axis_map: Dict[str, str] = {}
    for c in selected_cols:
        default_axis = "A2" if c.startswith("Q") else "A1"
        axis_map[c] = st.selectbox(
            f"{c}",
            options=list(AXIS_LABELS.keys()),
            index=list(AXIS_LABELS.keys()).index(default_axis),
            format_func=lambda k: AXIS_LABELS[k],
            key=f"axis_{c}",
        )
    return axis_map


def group_series_selector(group_name: str, present_cols: List[str]) -> List[str]:
    """Чекбоксы серий внутри панели группы."""
    with st.container(border=True):
        st.markdown(f"**{group_name}**")
        cols_grid = st.columns(min(len(present_cols), 4) or 1)
        chosen = []
        for i, c in enumerate(present_cols):
            with cols_grid[i % len(cols_grid)]:
                if st.checkbox(c, value=True, key=f"{group_name}:{c}"):
                    chosen.append(c)
        if not chosen:
            st.info("Ни одной серии не выбрано.")
        return chosen
