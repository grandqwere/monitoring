from __future__ import annotations

import io
import os
import re
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple

import boto3
import pandas as pd
import streamlit as st
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from core.s3_paths import build_all_key_for


# ------------------------- CSV: локальный ------------------------- #
def read_csv_local(uploaded_file) -> pd.DataFrame:
    df = pd.read_csv(uploaded_file, sep=None, engine="python")
    return _ensure_time_index(df)


# ------------------------- Вспомогательные ------------------------ #
def _ensure_time_index(df: pd.DataFrame) -> pd.DataFrame:
    time_candidates = ["timestamp", "time", "date", "datetime"]
    cols_lower = {c.lower(): c for c in df.columns}
    time_col = next((cols_lower[c] for c in time_candidates if c in cols_lower), None)
    if time_col:
        try:
            ts = pd.to_datetime(df[time_col], errors="coerce")
            if ts.notna().any():
                df = df.drop(columns=[time_col]).copy()
                df.index = ts
                df = df.sort_index()
        except Exception:
            pass
    return df


# --------------------------- S3 config ---------------------------- #
def _s3_secrets() -> dict:
    s = dict(st.secrets.get("s3", {}))
    s.setdefault("bucket", os.getenv("S3_BUCKET", ""))
    s.setdefault("prefix", os.getenv("S3_PREFIX", ""))   # для build_key_for используется в core/s3_paths.py
    s.setdefault("region", os.getenv("AWS_DEFAULT_REGION", "eu-central-1"))
    s.setdefault("endpoint_url", os.getenv("S3_ENDPOINT_URL", ""))    # ВАЖНО для S3-совместимых
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


# --------------------------- HEAD / GET --------------------------- #
def head_exists(key: str) -> bool:
    """HEAD-наличие объекта без скачивания содержимого."""
    client = _get_s3_client()
    try:
        client.head_object(Bucket=_bucket_name(), Key=key)
        return True
    except ClientError as e:
        code = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in (403, 404):  # нет прав или нет объекта — считаем «нет»
            return False
        # остальное пробрасываем, чтобы видеть реальные ошибки
        raise

def read_csv_s3(key: str) -> pd.DataFrame:
    """GET-скачивание CSV."""
    client = _get_s3_client()
    obj = client.get_object(Bucket=_bucket_name(), Key=key)
    data = obj["Body"].read()
    df = pd.read_csv(io.BytesIO(data), sep=None, engine="python")
    return _ensure_time_index(df)


# ---------------------- Кеш наличия часов (24) -------------------- #
@st.cache_data(ttl=900)  # 15 минут
def available_hours_for_date(d: date, cache_buster: int = 0) -> Dict[int, str]:
    """
    Проверяем 24 возможных часа на дату d через HEAD.
    Возвращает dict: hour -> s3_key (только существующие).
    """
    result: Dict[int, str] = {}
    for h in range(24):
        key = build_all_key_for(d, h)
        try:
            if head_exists(key):
                result[h] = key
        except Exception as e:
            # если провайдер иногда шлёт 500 — просто пропустим этот час
            continue
    return result
