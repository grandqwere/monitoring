from __future__ import annotations

import io
import os
from datetime import date
from typing import Dict

import boto3
import pandas as pd
import streamlit as st
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

# --- S3 конфигурация (как было) ---
def _s3_secrets() -> dict:
    s = dict(st.secrets.get("s3", {}))
    s.setdefault("bucket", os.getenv("S3_BUCKET", ""))
    s.setdefault("prefix", os.getenv("S3_PREFIX", ""))
    s.setdefault("region", os.getenv("AWS_DEFAULT_REGION", "eu-central-1"))
    s.setdefault("endpoint_url", os.getenv("S3_ENDPOINT_URL", ""))
    s.setdefault("aws_access_key_id", os.getenv("AWS_ACCESS_KEY_ID", ""))
    s.setdefault("aws_secret_access_key", os.getenv("AWS_SECRET_ACCESS_KEY", ""))
    s.setdefault("path_style", bool(str(s.get("path_style", "false")).lower() == "true"))
    s.setdefault("signature_version", os.getenv("S3_SIGNATURE_VERSION", s.get("signature_version", "")))
    return s

@st.cache_resource
def _get_s3_client():
    s = _s3_secrets()
    if not s.get("bucket"):
        raise RuntimeError("S3: не указан bucket в secrets.toml [s3].bucket")
    from botocore.config import Config as BotoConfig
    cfg_kwargs = {}
    if s.get("signature_version"):
        cfg_kwargs["signature_version"] = s["signature_version"]
    addressing = "path" if s.get("path_style") else "virtual"
    boto_cfg = BotoConfig(s3={"addressing_style": addressing}, **cfg_kwargs)
    session = boto3.session.Session(
        aws_access_key_id=s.get("aws_access_key_id") or None,
        aws_secret_access_key=s.get("aws_secret_access_key") or None,
        region_name=s.get("region") or None,
    )
    return session.client("s3", endpoint_url=(s.get("endpoint_url") or None), config=boto_cfg)

def _bucket_name() -> str:
    return _s3_secrets()["bucket"]

# --- Универсальный ридер CSV из байтов ---
def _read_csv_bytes(data: bytes) -> pd.DataFrame:
    """
    Пытаемся читать с учётом возможных 'точка/запятая' и 'точка с запятой'.
    1) пробуем ';' (наш основной формат),
    2) если колонок оказалось меньше 2 — пробуем авто (sep=None).
    """
    for try_sep in (";", None, "\t", ","):
        buf = io.BytesIO(data)
        try:
            df = pd.read_csv(buf, sep=try_sep, engine="python")
            if df.shape[1] >= 2:
                return df
        except Exception:
            continue
    # совсем крайний случай
    return pd.read_csv(io.BytesIO(data), sep=None, engine="python")

# --- Публичные функции чтения ---
def read_csv_local(uploaded_file) -> pd.DataFrame:
    data = uploaded_file.read()
    return _read_csv_bytes(data)

def read_csv_s3(key: str) -> pd.DataFrame:
    client = _get_s3_client()
    obj = client.get_object(Bucket=_bucket_name(), Key=key)
    data = obj["Body"].read()
    return _read_csv_bytes(data)

# --- (остальной код S3: head/available_hours... можно оставить без изменений, если используется) ---

# --- Заглушки для старого календаря (безопасно удалить, если не нужны) ---
def s3_build_index() -> pd.DataFrame:
    return pd.DataFrame(columns=["dt", "key"])

def build_availability(index_df: pd.DataFrame):
    """
    Возвращает (days_set, hours_map, key_map):
      days_set: set[date]
      hours_map: dict[date, set[int]]
      key_map: dict[(date, hour), s3_key]
    """
    return set(), {}, {}
