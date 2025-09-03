from __future__ import annotations
from datetime import date
import streamlit as st

def _s3_secrets() -> dict:
    s = dict(st.secrets.get("s3", {}))
    # Шаблон имени: можно задать в secrets.toml -> [s3].key_template
    # По умолчанию: All-YYYY.MM.DD-HH.00.csv
    s.setdefault("key_template", "All-{YYYY}.{MM}.{DD}-{HH}.00.csv")
    s.setdefault("prefix", s.get("prefix", ""))  # например: "deviceA/"
    return s

def build_key_for(d: date, hour: int) -> str:
    """
    Собирает S3 key из шаблона и prefix.
    Поддерживаемые плейсхолдеры: {YYYY} {MM} {DD} {HH} {mm}
    """
    s = _s3_secrets()
    tpl: str = s["key_template"]
    fname = (
        tpl.replace("{YYYY}", f"{d.year:04d}")
           .replace("{MM}", f"{d.month:02d}")
           .replace("{DD}", f"{d.day:02d}")
           .replace("{HH}", f"{hour:02d}")
           .replace("{mm}", "00")
    )
    prefix = s["prefix"] or ""
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return f"{prefix}{fname}"
