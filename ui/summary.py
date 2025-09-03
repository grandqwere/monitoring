from __future__ import annotations
from typing import List
import streamlit as st

def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]

def render_summary_controls(
    num_cols: List[str],
    default_main: List[str],
    key_prefix: str = ""
) -> tuple[list[str], set[str]]:
    """
    Выбор полей и нормирование шкал для сводного графика.
    Все внутренние ключи виджетов получают префикс key_prefix, чтобы не путать состояния
    между часовым/суточным режимами и разными интервалами усреднения.
    """
    main_key = f"{key_prefix}main_fields"

    selected_main = st.multiselect(
        "Поля для сводного графика",
        options=num_cols,
        default=default_main,
        key=main_key,
    )

    st.markdown("**Нормирование шкалы** — отдельные шкалы слева для отмеченных трендов:")

    # очистка устаревших ключей только нашего префикса
    norm_prefix = f"{key_prefix}norm_"
    for k in list(st.session_state.keys()):
        if k.startswith(norm_prefix):
            col = k[len(norm_prefix):]
            if col not in selected_main:
                del st.session_state[k]

    allowed = max(0, len(selected_main) - 1)
    flags = {c: bool(st.session_state.get(f"{norm_prefix}{c}", False)) for c in selected_main}

    for row in chunk(selected_main, 6):
        cols = st.columns(len(row))
        for i, c in enumerate(row):
            checked_others = sum(flags[x] for x in selected_main if x != c)
            disable_this = (checked_others >= allowed) and (not flags[c])
            with cols[i]:
                val = st.checkbox(c, value=flags[c], key=f"{norm_prefix}{c}", disabled=disable_this)
                flags[c] = bool(val)

    checked = [c for c, v in flags.items() if v]
    if len(checked) > allowed:
        to_keep = set([c for c in selected_main if c in checked][:allowed])
        for c in checked:
            if c not in to_keep:
                st.session_state[f"{norm_prefix}{c}"] = False
                flags[c] = False

    separate_set = {c for c, v in flags.items() if v}
    return selected_main, separate_set
