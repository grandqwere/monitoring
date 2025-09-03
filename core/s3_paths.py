from __future__ import annotations
from datetime import date
import streamlit as st

def _s3_secrets() -> dict:
    s = dict(st.secrets.get("s3", {}))
    # Имя файла (без папок). По умолчанию: All-YYYY.MM.DD-HH.00.csv
    s.setdefault("key_template", "All-{YYYY}.{MM}.{DD}-{HH}.00.csv")
    # Внешний префикс (например: "deviceA/"). Оставляем как есть.
    s.setdefault("prefix", s.get("prefix", ""))
    return s

def _join_prefix(prefix: str, subdir: str | None) -> str:
    p = prefix or ""
    if p and not p.endswith("/"):
        p += "/"
    d = (subdir or "").strip("/")
    if d:
        p += d + "/"
    return p

def _render_filename(tpl: str, d: date, hour: int) -> str:
    return (
        tpl.replace("{YYYY}", f"{d.year:04d}")
           .replace("{MM}", f"{d.month:02d}")
           .replace("{DD}", f"{d.day:02d}")
           .replace("{HH}", f"{hour:02d}")
           .replace("{mm}", "00")
    )

def build_key_for(d: date, hour: int, subdir: str | None = None) -> str:
    """
    Универсальный сборщик ключей: prefix + (subdir/) + filename.
    subdir можно не задавать — тогда только prefix + filename.
    """
    s = _s3_secrets()
    fname = _render_filename(s["key_template"], d, hour)
    base = _join_prefix(s["prefix"], subdir)
    return f"{base}{fname}"

def build_all_key_for(d: date, hour: int) -> str:
    """
    Специально для часовых файлов из подпапки All/.
    Итоговый ключ: <prefix>All/<filename>
    """
    return build_key_for(d, hour, subdir="All")
