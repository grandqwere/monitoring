# core/s3_paths.py
from __future__ import annotations

from datetime import date
import streamlit as st


def _s3_secrets() -> dict:
    """
    Безопасно извлекаем секцию [s3] из Secrets и гарантируем дефолты.
    """
    s: dict = {}
    try:
        raw = st.secrets.get("s3", {})
        for k, v in getattr(raw, "items", lambda: [])():
            s[k] = v
    except Exception:
        pass

    # Гарантированный шаблон имени файла, если его нет в Secrets (используется для All)
    if not s.get("key_template"):
        s["key_template"] = "All-{YYYY}.{MM}.{DD}-{HH}.00.csv"

    return s


def _join_prefix(prefix: str, subpath: str | None) -> str:
    """Склейка prefix + subpath (оба могут быть пустыми). Гарантируем завершающий /."""
    p = (prefix or "").rstrip("/")
    s = (subpath or "").strip("/")
    if p and s:
        base = f"{p}/{s}/"
    elif p:
        base = f"{p}/"
    elif s:
        base = f"{s}/"
    else:
        base = ""
    return base


def _render_filename(tpl: str, d: date, hour: int) -> str:
    """Рендер для часовых файлов All по шаблону (исторический)."""
    return (
        tpl.replace("{YYYY}", f"{d.year:04d}")
           .replace("{MM}", f"{d.month:02d}")
           .replace("{DD}", f"{d.day:02d}")
           .replace("{HH}", f"{hour:02d}")
           .replace("{mm}", "00")
    )


def _is_demo_mode() -> bool:
    """Определяем демо-режим: auth_mode == 'demo' или текущий префикс совпадает с auth.demo_prefix."""
    try:
        if st.session_state.get("auth_mode") == "demo":
            return True
        demo_pref = str(st.secrets.get("auth", {}).get("demo_prefix", "")).strip().rstrip("/")
        curr_pref = str(st.session_state.get("current_prefix", "")).strip().rstrip("/")
        return bool(demo_pref and curr_pref and demo_pref == curr_pref)
    except Exception:
        return False


def _map_day_for_storage(d: date) -> date:
    """
    Для All (часовые): в демо всегда читаем данные за тот же день августа 2025 (1..31).
    Вне демо — дата без изменений.
    """
    if _is_demo_mode():
        return date(2025, 8, min(d.day, 31))
    return d


# --- Минутные пики: демо-режим фиксируется на ОДНУ дату ---
_DEMO_MINUTE_DAY = date(2025, 8, 25)


def _map_day_for_minutely_storage(d: date) -> date:
    """
    Для Ipeak/Upeak (минутные): в демо всегда читаем данные за фиксированную дату 2025-08-25,
    независимо от выбранного дня.
    """
    if _is_demo_mode():
        return _DEMO_MINUTE_DAY
    return d


def build_key_for(d: date, hour: int, subdir: str | None = None) -> str:
    """
    Универсальный сборщик ключей для часовых файлов (All):
      current_prefix (из session_state) + (subdir/) + filename.
    В демо-режиме дата для ЧТЕНИЯ маппится на август 2025 того же номера дня.
    """
    s = _s3_secrets()
    d_eff = _map_day_for_storage(d)
    tpl = s.get("key_template") or "All-{YYYY}.{MM}.{DD}-{HH}.00.csv"
    fname = _render_filename(tpl, d_eff, hour)
    current_prefix = st.session_state.get("current_prefix", "")
    base = _join_prefix(current_prefix, subdir)
    return f"{base}{fname}"


def build_all_key_for(d: date, hour: int) -> str:
    """
    Часовые файлы из папки All/ с дневными подпапками:
      <prefix>/All/YYYY.MM.DD/All-YYYY.MM.DD-HH.00.csv
    """
    d_eff = _map_day_for_storage(d)
    day_folder = f"{d_eff.year:04d}.{d_eff.month:02d}.{d_eff.day:02d}"
    subpath = f"All/{day_folder}"
    return build_key_for(d, hour, subdir=subpath)

def build_all_day_prefix_for(d: date) -> str:
    """
    Префикс папки дня в All/:
      <prefix>/All/YYYY.MM.DD/
    Учитывает демо-маппинг даты (_map_day_for_storage).
    """
    d_eff = _map_day_for_storage(d)
    day_folder = f"{d_eff.year:04d}.{d_eff.month:02d}.{d_eff.day:02d}"
    current_prefix = st.session_state.get("current_prefix", "")
    return _join_prefix(current_prefix, f"All/{day_folder}")

def build_root_key(filename: str) -> str:
    """
    Ключ для файла в КОРНЕ текущего префикса (например: <prefix>/description.txt).
    """
    current_prefix = st.session_state.get("current_prefix", "")
    base = _join_prefix(current_prefix, None)
    return f"{base}{filename}"


# -------------------- Минутные файлы Ipeak/Upeak --------------------

def _render_peak_filename(kind: str, d_eff: date, hour: int, minute: int) -> str:
    """
    kind: 'Ipeak' | 'Upeak'
    Формат: {kind}-YYYY.MM.DD-HH.MM.csv
    """
    return (
        f"{kind}-"
        f"{d_eff.year:04d}.{d_eff.month:02d}.{d_eff.day:02d}-"
        f"{hour:02d}.{minute:02d}.csv"
    )


def _build_peak_key_for(kind: str, d: date, hour: int, minute: int) -> str:
    """
    Универсальный сборщик ключей для минутных файлов:
      <prefix>/{kind}/YYYY.MM.DD/{kind}-YYYY.MM.DD-HH.MM.csv
    В демо-режиме чтение фиксируется на 2025.08.25 (папка и имя файла).
    """
    d_eff = _map_day_for_minutely_storage(d)
    day_folder = f"{d_eff.year:04d}.{d_eff.month:02d}.{d_eff.day:02d}"
    subpath = f"{kind}/{day_folder}"
    fname = _render_peak_filename(kind, d_eff, hour, minute)

    current_prefix = st.session_state.get("current_prefix", "")
    base = _join_prefix(current_prefix, subpath)
    return f"{base}{fname}"


def build_ipeak_key_for(d: date, hour: int, minute: int) -> str:
    return _build_peak_key_for("Ipeak", d, hour, minute)


def build_upeak_key_for(d: date, hour: int, minute: int) -> str:
    return _build_peak_key_for("Upeak", d, hour, minute)
