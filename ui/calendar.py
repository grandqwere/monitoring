from __future__ import annotations
from datetime import date, datetime
import calendar
import streamlit as st
import pandas as pd
from core.data_io import s3_build_index, build_availability

def month_start(d: date) -> date:
    return d.replace(day=1)

def add_month(d: date, delta: int) -> date:
    m = (d.month - 1 + delta) % 12 + 1
    y = d.year + (d.month - 1 + delta) // 12
    last_day = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last_day))

def render_calendar_and_pick(index_df: pd.DataFrame, cache_buster: int) -> tuple[date | None, str | None]:
    """Рисует календарь дней/часов. Возвращает (selected_day, chosen_key)."""
    days_set, hours_map, key_map = build_availability(index_df) if not index_df.empty else (set(), {}, {})

    # init month/day
    if "cal_month" not in st.session_state:
        if not index_df.empty:
            last_dt: datetime = index_df["dt"].max().to_pydatetime()
            st.session_state["cal_month"] = month_start(last_dt.date())
        else:
            st.session_state["cal_month"] = month_start(date.today())
    if "cal_day" not in st.session_state:
        st.session_state["cal_day"] = None

    # month nav
    nav_l, nav_c, nav_r = st.columns([0.1, 0.8, 0.1])
    with nav_l:
        if st.button("←", key=f"cal_prev_{cache_buster}"):
            st.session_state["cal_month"] = add_month(st.session_state["cal_month"], -1)
    with nav_c:
        cm = st.session_state["cal_month"]
        st.markdown(f"### {calendar.month_name[cm.month]} {cm.year}")
    with nav_r:
        if st.button("→", key=f"cal_next_{cache_buster}"):
            st.session_state["cal_month"] = add_month(st.session_state["cal_month"], +1)

    # grid days
    cm = st.session_state["cal_month"]
    first_weekday, days_in_month = calendar.monthrange(cm.year, cm.month)

    week_rows = []
    row = [None] * first_weekday
    for day_num in range(1, days_in_month + 1):
        row.append(date(cm.year, cm.month, day_num))
        if len(row) == 7:
            week_rows.append(row); row = []
    if row:
        row += [None] * (7 - len(row))
        week_rows.append(row)

    wd = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    cols = st.columns(7)
    for i, w in enumerate(wd):
        cols[i].markdown(f"**{w}**")

    selected_day = st.session_state.get("cal_day")
    for week in week_rows:
        cols = st.columns(7)
        for i, d in enumerate(week):
            if d is None:
                cols[i].markdown("&nbsp;"); continue
            has_data = d in days_set
            label = str(d.day)
            if has_data:
                if cols[i].button(label, key=f"day_{d.isoformat()}"):
                    st.session_state["cal_day"] = d
                    selected_day = d
            else:
                cols[i].button(label, key=f"day_{d.isoformat()}", disabled=True)

    if selected_day is None and days_set:
        selected_day = max(days_set)
        st.session_state["cal_day"] = selected_day

    chosen_key = None
    if selected_day is not None:
        st.markdown(f"**Выбранный день:** {selected_day.isoformat()}")
        # hours grid (3 rows x 8 cols)
        for block in range(3):
            cols = st.columns(8)
            for i in range(8):
                h = block * 8 + i
                if h > 23: continue
                active = (h in hours_map.get(selected_day, set()))
                label = f"{h:02d}:00"
                key = f"hour_{selected_day.isoformat()}_{h:02d}"
                if active:
                    if cols[i].button(label, key=key):
                        chosen_key = key_map.get((selected_day, h))
                else:
                    cols[i].button(label, key=key, disabled=True)
    return selected_day, chosen_key
