from __future__ import annotations
from datetime import date
import streamlit as st

def _s3_secrets() -> dict:
    s = dict(st.secrets.get("s3", {}))
    # Имя файла (без папок). По умолчанию: All-YYYY.MM.DD-HH.00.csv
    s.setdefault("key_template", "All-{YYYY}.{MM}.{DD}-{HH}.00.csv")
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

def build_key_for(d: date, hour: int, subdir: str | None = None) -> str:
    """Универсальный сборщик ключей: prefix + (subdir/) + filename."""
    s = _s3_secrets()
    fname = _render_filename(s["key_template"], d, hour)
    # Текущий «корень» S3 задаётся при входе (пароль/демо) и лежит в session_state
    current_prefix = st.session_state.get("current_prefix", "")
    base = _join_prefix(current_prefix, subdir)
    return f"{base}{fname}"

def build_all_key_for(d: date, hour: int) -> str:
    """
    Часовые файлы из папки All/ с дневными подпапками:
    <prefix>/All/YYYY.MM.DD/All-YYYY.MM.DD-HH.00.csv
    """
    day_folder = f"{d.year:04d}.{d.month:02d}.{d.day:02d}"
    subpath = f"All/{day_folder}"
    return build_key_for(d, hour, subdir=subpath)

def build_root_key(filename: str) -> str:
    """
    Ключ для файла в КОРНЕ текущего префикса (например: <prefix>/description.txt).
    """
    current_prefix = st.session_state.get("current_prefix", "")
    base = _join_prefix(current_prefix, None)  # даст "prefix/" или ""
    return f"{base}{filename}"
