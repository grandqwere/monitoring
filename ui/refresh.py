from __future__ import annotations
import streamlit as st

def draw_refresh_all() -> int:
    if "refresh_all" not in st.session_state:
        st.session_state["refresh_all"] = 0

    left, right = st.columns([0.75, 0.25])
    with left:
        st.title("Часовые графики электроизмерений")  # ← новое имя
    with right:
        if st.button("↻ Обновить все графики", key="btn_all"):
            st.session_state["refresh_all"] += 1
            st.rerun()  # мгновенная перерисовка
    return st.session_state["refresh_all"]

def refresh_bar(title: str, name: str) -> int:
    key = f"refresh_{name}"
    if key not in st.session_state:
        st.session_state[key] = 0
    left, right = st.columns([0.85, 0.15])
    with left:
        st.subheader(title)
    with right:
        if st.button("↻ Обновить", key=f"btn_{name}"):
            st.session_state[key] += 1
    return st.session_state[key]
