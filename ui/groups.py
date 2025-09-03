from __future__ import annotations
import pandas as pd
import streamlit as st
from core.plotting import group_panel
from ui.refresh import refresh_bar

def find_first(df_cols, *candidates):
    lower = {c.lower(): c for c in df_cols}
    for cand in candidates:
        if cand and cand.lower() in lower:
            return lower[cand.lower()]
    return None

def render_group(title: str, key_suffix: str, df: pd.DataFrame, cols: list[str], height: int, theme_base: str, all_token: int):
    token = refresh_bar(title, key_suffix)
    present = [c for c in cols if c in df.columns]
    if not present:
        st.info("Нет соответствующих колонок.")
        return
    fig = group_panel(df, present, height=height, theme_base=theme_base)
    st.plotly_chart(fig, use_container_width=True, config={"responsive": True}, key=f"{key_suffix}_{all_token}_{token}")

def render_power_group(df: pd.DataFrame, height: int, theme_base: str, all_token: int):
    token = refresh_bar("Мощность: активная / полная / реактивная / неактивная", "grp_power")
    c1, c2, c3, c4 = st.columns(4)
    with c1: show_total = st.checkbox("Общие", True, key="p_sel_total")
    with c2: show_l1    = st.checkbox("Фаза L1", False, key="p_sel_l1")
    with c3: show_l2    = st.checkbox("Фаза L2", False, key="p_sel_l2")
    with c4: show_l3    = st.checkbox("Фаза L3", False, key="p_sel_l3")

    power_cols: list[str] = []
    def add_power_set(tag: str):
        p = find_first(df.columns, f"P_{tag}")
        s = find_first(df.columns, f"S_{tag}")
        q = find_first(df.columns, f"Q_{tag}")
        n = find_first(df.columns, f"N_{tag}", f"N{'' if tag=='total' else '_' + tag}")
        for c in [p, s, q, n]:
            if c and c in df.columns:
                power_cols.append(c)

    if show_total: add_power_set("total")
    if show_l1:    add_power_set("L1")
    if show_l2:    add_power_set("L2")
    if show_l3:    add_power_set("L3")
    if not any([show_total, show_l1, show_l2, show_l3]):
        add_power_set("total")

    present = [c for c in power_cols if c in df.columns]
    fig = group_panel(df, present, height=height, theme_base=theme_base)
    st.plotly_chart(fig, use_container_width=True, config={"responsive": True}, key=f"grp_power_{all_token}_{token}")
