from __future__ import annotations
import streamlit as st


def init_once():
    if "df_current" not in st.session_state:
        st.session_state["df_current"] = None
    if "time_col" not in st.session_state:
        st.session_state["time_col"] = "timestamp"
