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
        # .items() есть у стандартного маппинга Secrets
        for k, v in getattr(raw, "items", lambda: [])():
            s[k] = v
    except Exception:
        pass
    # Гарантированный шаблон имени файла, если его нет в Secrets
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
    """В демо всегда читаем данные за тот же день августа 2025 (1..31). Вне демо — дата без изменений."""
    if _is_demo_mode():
        return date(2025, 8, min(d.day, 31))
    return d

def build_key_for(d: date, hour: int, subdir: str | None = None) -> str:
    """Универсальный сборщик ключей: current_prefix (из session_state) + (subdir/) + filename.
       В демо-режиме дата для ЧТЕНИЯ маппится на август 2025 того же номера дня.
    """
    s = _s3_secrets()
    d_eff = _map_day_for_storage(d)
    tpl = s.get("key_template") or "All-{YYYY}.{MM}.{DD}-{HH}.00.csv"
    fname = _render_filename(tpl, d_eff, hour)
    # Текущий «корень» S3 задаётся при входе (пароль/демо) и лежит в session_state
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

def build_root_key(filename: str) -> str:
    """
    Ключ для файла в КОРНЕ текущего префикса (например: <prefix>/description.txt).
    """
    current_prefix = st.session_state.get("current_prefix", "")
    base = _join_prefix(current_prefix, None)  # даст "prefix/" или ""
    return f"{base}{filename}"
