from __future__ import annotations
import streamlit as st
from typing import List, Dict
from core.config import AXIS_LABELS, DEFAULT_PRESET

def height_controls():
    main_height = st.slider("Высота верхнего графика, px", 700, 1200, 900, step=50, key="h_main")
    group_height = st.slider("Высота каждой панели внизу, px", 300, 700, 400, step=50, key="h_group")
    st.caption("Зум/панорамирование — колесо/drag, двойной клик — сброс, клик по легенде — скрыть серию.")
    return main_height, group_height

def _default_series(all_cols: List[str]) -> List[str]:
    """Дефолт для выбора серий (если пусто)."""
    return [c for c in DEFAULT_PRESET if c in all_cols] or all_cols[:3]

def series_selector(all_cols: List[str], key_prefix: str = "") -> List[str]:
    """
    Мультивыбор серий с сохранением в st.session_state.
    Ключи:
      - {key_prefix}series_state  — текущий список
      - {key_prefix}main_select   — сам виджет multiselect
    """
    st_key = f"{key_prefix}series_state"
    # Берём прошлый выбор и чистим от отсутствующих колонок
    prev = [c for c in st.session_state.get(st_key, []) if c in all_cols]
    default = prev or _default_series(all_cols)

    sel = st.multiselect(
        "Добавить серии в верхний график",
        options=all_cols,
        default=default,
        key=f"{key_prefix}main_select",
    )
    # Если пользователь всё снял, не оставляем график пустым — вернём предыдущий/дефолт
    if not sel:
        sel = default
    st.session_state[st_key] = sel
    return sel

def axis_selector(selected_cols: List[str], key_prefix: str = "") -> Dict[str, str]:
    """
    Выбор оси для каждой серии с сохранением в st.session_state.
    Ключи:
      - {key_prefix}axes_state   — dict {колонка: 'A1'|'A2'}
      - {key_prefix}axis_{col}   — виджет selectbox по каждой колонке
    """
    st.write("Назначение осей Y для выбранных серий")

    axes_key = f"{key_prefix}axes_state"
    prev_axes: Dict[str, str] = st.session_state.get(axes_key, {})

    axis_map: Dict[str, str] = {}
    for c in selected_cols:
        # Предпочитаем прошлое назначение, иначе эвристика: Q* -> A2
        default_axis = prev_axes.get(c, "A2" if c.startswith("Q") else "A1")
        axis_map[c] = st.selectbox(
            f"{c}",
            options=list(AXIS_LABELS.keys()),
            index=list(AXIS_LABELS.keys()).index(default_axis),
            format_func=lambda k: AXIS_LABELS[k],
            key=f"{key_prefix}axis_{c}",
        )

    # Очищаем состояние от колонок, которых больше нет
    st.session_state[axes_key] = {k: v for k, v in axis_map.items()}
    return axis_map

def group_series_selector(group_name: str, present_cols: List[str], key_prefix: str = "") -> List[str]:
    """
    Чекбоксы серий внутри панели группы.
    Используем уникальные ключи с префиксом, чтобы состояния табов не конфликтовали.
    """
    with st.container(border=True):
        st.markdown(f"**{group_name}**")
        cols_grid = st.columns(min(len(present_cols), 4) or 1)
        chosen = []
        for i, c in enumerate(present_cols):
            with cols_grid[i % len(cols_grid)]:
                if st.checkbox(c, value=True, key=f"{key_prefix}{group_name}:{c}"):
                    chosen.append(c)
        if not chosen:
            st.info("Ни одной серии не выбрано.")
        return chosen
