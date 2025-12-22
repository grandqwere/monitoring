# core/minute_loader.py
from __future__ import annotations

from datetime import date as date_cls
import pandas as pd
import streamlit as st

from core.data_io import read_csv_s3
from core.prepare import normalize
from core.s3_paths import build_ipeak_key_for, build_upeak_key_for


def init_minute_state() -> None:
    """Инициализация session_state для минутных данных (Ipeak/Upeak)."""
    if "loaded_minutes" not in st.session_state:
        st.session_state["loaded_minutes"] = []  # [(date, hour, minute)]
    if "minute_cache" not in st.session_state:
        st.session_state["minute_cache"] = {}  # "YYYY-MM-DDTHH:MM" -> DataFrame
    if "current_minute_date" not in st.session_state:
        st.session_state["current_minute_date"] = None
    if "current_minute_hour" not in st.session_state:
        st.session_state["current_minute_hour"] = None
    if "current_minute_minute" not in st.session_state:
        st.session_state["current_minute_minute"] = None
    if "selected_minute_date" not in st.session_state:
        st.session_state["selected_minute_date"] = None


def _key_for(d: date_cls, h: int, m: int) -> str:
    return f"{d.isoformat()}T{h:02d}:{m:02d}"


def _reassign_index_date_keep_time(df: pd.DataFrame, new_day: date_cls) -> pd.DataFrame:
    """
    Заменяем компонент ДАТЫ в индексе на new_day, оставляя часы/минуты/секунды как есть.
    Используется в DEMO, чтобы отображать выбранную пользователем дату.
    """
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return df
    idx = df.index
    new_idx = pd.to_datetime(
        [ts.replace(year=new_day.year, month=new_day.month, day=new_day.day) for ts in idx]
    )
    out = df.copy()
    out.index = new_idx
    return out.sort_index()


def _drop_service_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Убираем служебные k_* и прочие нецелевые столбцы для минутных пиков."""
    if df is None or df.empty:
        return df
    drop = [c for c in df.columns if str(c).lower().startswith("k_")]
    if drop:
        df = df.drop(columns=drop, errors="ignore")
    return df


def _keep_prefix_cols(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Оставляем только колонки, начинающиеся с prefix (регистронезависимо)."""
    if df is None or df.empty:
        return df
    p = prefix.lower()
    cols = [c for c in df.columns if str(c).lower().startswith(p)]
    if not cols:
        return df.head(0)  # пустой, но с индексом
    return df[cols].copy()


def load_minute(d: date_cls, h: int, m: int, *, silent: bool = True) -> pd.DataFrame | None:
    """
    Загрузка одной минуты (Ipeak+Upeak) с кэшированием.
    Возвращает объединённый DataFrame (outer по времени) или None при отсутствии обоих файлов.

    DEMO:
      - ключи чтения маппятся на 2025.08.25 внутри build_*_key_for(),
      - здесь дополнительно «перешиваем» индекс на выбранную дату d.
    """
    k = _key_for(d, h, m)
    cache: dict[str, pd.DataFrame] = st.session_state["minute_cache"]
    if k in cache:
        return cache[k]

    # читаем Ipeak
    df_i: pd.DataFrame | None = None
    try:
        key_i = build_ipeak_key_for(d, h, m)
        df_raw_i = read_csv_s3(key_i)
        df_i = normalize(df_raw_i)
        df_i = _drop_service_cols(df_i)
        df_i = _keep_prefix_cols(df_i, "Ipeak")
    except Exception:
        df_i = None

    # читаем Upeak
    df_u: pd.DataFrame | None = None
    try:
        key_u = build_upeak_key_for(d, h, m)
        df_raw_u = read_csv_s3(key_u)
        df_u = normalize(df_raw_u)
        df_u = _drop_service_cols(df_u)
        df_u = _keep_prefix_cols(df_u, "Upeak")
    except Exception:
        df_u = None

    if (df_i is None or df_i.empty) and (df_u is None or df_u.empty):
        return None

    # Объединяем (рассинхрон допускаем): outer по индексу времени
    parts = []
    if df_u is not None and not df_u.empty:
        parts.append(df_u)
    if df_i is not None and not df_i.empty:
        parts.append(df_i)

    df = pd.concat(parts, axis=1)

    # На всякий случай: сортировка и уникализация индекса
    if isinstance(df.index, pd.DatetimeIndex):
        df = df.sort_index()
        if df.index.has_duplicates:
            df = df[~df.index.duplicated(keep="last")]

    # В DEMO отображаем выбранный день (чтение было из 2025-08-25)
    if st.session_state.get("auth_mode") == "demo":
        df = _reassign_index_date_keep_time(df, d)

    cache[k] = df
    return df


def set_only_minute(d: date_cls, h: int, m: int) -> bool:
    """Показать только эту минуту: очищаем остальной минутный кэш."""
    df = load_minute(d, h, m)
    if df is None:
        return False

    st.session_state["loaded_minutes"] = [(d, h, m)]
    keep = {_key_for(d, h, m)}
    st.session_state["minute_cache"] = {kk: vv for kk, vv in st.session_state["minute_cache"].items() if kk in keep}

    st.session_state["current_minute_date"] = d
    st.session_state["current_minute_hour"] = h
    st.session_state["current_minute_minute"] = m
    st.session_state["selected_minute_date"] = d
    return True


def append_minute(d: date_cls, h: int, m: int) -> bool:
    """Добавить минуту к графику (макс. 2): при переполнении удаляем самую старую."""
    df = load_minute(d, h, m)
    if df is None:
        return False

    triple = (d, h, m)
    lm: list[tuple[date_cls, int, int]] = st.session_state["loaded_minutes"]

    if triple in lm:
        lm.remove(triple)
    lm.append(triple)

    while len(lm) > 2:
        old = lm.pop(0)
        st.session_state["minute_cache"].pop(_key_for(*old), None)

    st.session_state["current_minute_date"], st.session_state["current_minute_hour"], st.session_state["current_minute_minute"] = lm[-1]
    st.session_state["selected_minute_date"] = st.session_state["current_minute_date"]
    return True


def combined_minute_df() -> pd.DataFrame:
    """Комбинирует загруженные минуты в единый DataFrame по индексу времени."""
    frames: list[pd.DataFrame] = []
    for d, h, m in st.session_state.get("loaded_minutes", []):
        k = _key_for(d, h, m)
        df = st.session_state["minute_cache"].get(k)
        if df is not None and not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames).sort_index()
    if isinstance(out.index, pd.DatetimeIndex) and out.index.has_duplicates:
        out = out[~out.index.duplicated(keep="last")]
    return out


def has_minute_current() -> bool:
    return (
        st.session_state.get("current_minute_date") is not None
        and st.session_state.get("current_minute_hour") is not None
        and st.session_state.get("current_minute_minute") is not None
    )
