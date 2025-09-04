from __future__ import annotations
from datetime import date as date_cls
import pandas as pd
import streamlit as st

from core.data_io import read_csv_s3
from core.prepare import normalize
from core.s3_paths import build_all_key_for


def init_hour_state():
    """Инициализация session_state для часовых данных."""
    if "loaded_hours" not in st.session_state:
        st.session_state["loaded_hours"] = []          # [(date, hour)]
    if "hour_cache" not in st.session_state:
        st.session_state["hour_cache"] = {}            # "YYYY-MM-DDTHH" -> DataFrame
    if "current_date" not in st.session_state:
        st.session_state["current_date"] = None
    if "current_hour" not in st.session_state:
        st.session_state["current_hour"] = None
    if "selected_date" not in st.session_state:
        st.session_state["selected_date"] = None


def _key_for(d: date_cls, h: int) -> str:
    return f"{d.isoformat()}T{h:02d}"


def load_hour(d: date_cls, h: int, *, silent: bool = True) -> pd.DataFrame | None:
    """Загрузка одного часа с кэшированием.
    При отсутствии файла возвращает None. Сообщения интерфейсу выводим на уровне view.
    silent зарезервирован на случай будущего поведения, по умолчанию ничего не печатаем.
    """
    k = _key_for(d, h)
    cache = st.session_state["hour_cache"]
    if k in cache:
        return cache[k]

    s3_key = build_all_key_for(d, h)
    try:
        df_raw = read_csv_s3(s3_key)
        df = normalize(df_raw)
        cache[k] = df
        return df
    except Exception:
        # Тихо сигналим отсутствием — без сообщений здесь
        return None


def set_only_hour(d: date_cls, h: int) -> bool:
    """Показать только этот час: очищаем остальной кэш."""
    df = load_hour(d, h)
    if df is None:
        return False

    st.session_state["loaded_hours"] = [(d, h)]
    keep = {_key_for(d, h)}
    st.session_state["hour_cache"] = {
        k: v for k, v in st.session_state["hour_cache"].items() if k in keep
    }
    st.session_state["current_date"] = d
    st.session_state["current_hour"] = h
    st.session_state["selected_date"] = d  # подсветка в пикере
    return True


def append_hour(d: date_cls, h: int) -> bool:
    """Добавить час к графику (макс. 2): при переполнении удаляем самый старый."""
    df = load_hour(d, h)
    if df is None:
        return False

    pair = (d, h)
    lh: list[tuple[date_cls, int]] = st.session_state["loaded_hours"]
    if pair in lh:
        lh.remove(pair)
    lh.append(pair)
    while len(lh) > 2:
        old = lh.pop(0)
        st.session_state["hour_cache"].pop(_key_for(*old), None)

    st.session_state["current_date"], st.session_state["current_hour"] = lh[-1]
    st.session_state["selected_date"] = st.session_state["current_date"]
    return True


def combined_df() -> pd.DataFrame:
    """Комбинирует загруженные часы в единый DataFrame по индексу времени."""
    frames = []
    for d, h in st.session_state["loaded_hours"]:
        k = _key_for(d, h)
        if k in st.session_state["hour_cache"]:
            frames.append(st.session_state["hour_cache"][k])
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).sort_index()


def has_current() -> bool:
    return (
        st.session_state.get("current_date") is not None
        and st.session_state.get("current_hour") is not None
    )
