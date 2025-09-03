from __future__ import annotations

import io
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import boto3
import pandas as pd
import streamlit as st
from botocore.config import Config as BotoConfig


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
    # secrets.toml приоритетнее env
    s = dict(st.secrets.get("s3", {}))
    s.setdefault("bucket", os.getenv("S3_BUCKET", ""))
    s.setdefault("prefix", os.getenv("S3_PREFIX", ""))
    s.setdefault("region", os.getenv("AWS_DEFAULT_REGION", "eu-central-1"))
    s.setdefault("endpoint_url", os.getenv("S3_ENDPOINT_URL", ""))  # ВАЖНО
    s.setdefault("aws_access_key_id", os.getenv("AWS_ACCESS_KEY_ID", ""))
    s.setdefault("aws_secret_access_key", os.getenv("AWS_SECRET_ACCESS_KEY", ""))
    s.setdefault("path_style", bool(os.getenv("S3_PATH_STYLE", str(s.get("path_style", "false"))).lower() == "true"))
    s.setdefault("signature_version", os.getenv("S3_SIGNATURE_VERSION", s.get("signature_version", "")))
    s.setdefault("filename_regex", s.get("filename_regex", r"(?i).*-(?P<Y>\d{4})\.(?P<m>\d{2})\.(?P<d>\d{2})-(?P<H>\d{2})\.(?P<M>\d{2})\.csv$"))
    return s


@st.cache_resource
def _get_s3_client():
    s = _s3_secrets()
    if not s.get("bucket"):
        raise RuntimeError("S3: не указан bucket в secrets.toml [s3].bucket")

    cfg_kwargs = {}
    if s.get("signature_version"):
        cfg_kwargs["signature_version"] = s["signature_version"]
    # адресация бакета
    addressing = "path" if s.get("path_style") else "virtual"
    boto_cfg = BotoConfig(s3={"addressing_style": addressing}, **cfg_kwargs)

    session = boto3.session.Session(
        aws_access_key_id=s.get("aws_access_key_id") or None,
        aws_secret_access_key=s.get("aws_secret_access_key") or None,
        region_name=s.get("region") or None,
    )
    return session.client("s3", endpoint_url=(s.get("endpoint_url") or None), config=boto_cfg)


def _bucket_prefix() -> Tuple[str, str]:
    s = _s3_secrets()
    return s["bucket"], s.get("prefix", "").strip()


# -------------------------- Имена / парсинг ----------------------- #
@st.cache_resource
def _compiled_filename_regex():
    s = _s3_secrets()
    return re.compile(s["filename_regex"])


def _parse_key_to_dt(key: str) -> Optional[datetime]:
    """
    Извлекаем datetime из имени файла по regex (настраивается в secrets filename_regex).
    """
    basename = key.split("/")[-1]
    m = _compiled_filename_regex().match(basename)
    if not m:
        return None
    try:
        return datetime(
            int(m.group("Y")),
            int(m.group("m")),
            int(m.group("d")),
            int(m.group("H")),
            int(m.group("M")),
        )
    except Exception:
        return None


# --------------------------- Индексация S3 ------------------------ #
@st.cache_data(ttl=300)
def s3_build_index(cache_buster: int = 0) -> pd.DataFrame:
    """
    Возвращает таблицу с доступными файлами и их часами:
    columns: key, dt, date, hour
    """
    bucket, prefix = _bucket_prefix()
    client = _get_s3_client()

    keys: List[str] = []
    paginator = client.get_paginator("list_objects_v2")
    kwargs = {"Bucket": bucket}
    if prefix:
        kwargs["Prefix"] = prefix

    for page in paginator.paginate(**kwargs):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])

    rows = []
    for key in keys:
        dt = _parse_key_to_dt(key)
        if dt is None:
            continue
        rows.append((key, dt, dt.date(), dt.hour))

    if not rows:
        return pd.DataFrame(columns=["key", "dt", "date", "hour"])

    df = pd.DataFrame(rows, columns=["key", "dt", "date", "hour"]).sort_values("dt").reset_index(drop=True)
    return df


# ------------------------------ Чтение S3 ------------------------- #
def read_csv_s3(key: str) -> pd.DataFrame:
    bucket, _ = _bucket_prefix()
    client = _get_s3_client()
    obj = client.get_object(Bucket=bucket, Key=key)
    data = obj["Body"].read()
    df = pd.read_csv(io.BytesIO(data), sep=None, engine="python")
    return _ensure_time_index(df)


# ----------------------- Утилиты доступности ---------------------- #
def build_availability(index_df: pd.DataFrame):
    """
    Возвращает:
      days_set: set(date)
      hours_map: dict[date] -> set[int]
      key_map: dict[(date, hour)] -> s3_key
    """
    days_set = set(index_df["date"].tolist())
    hours_map: Dict = {}
    key_map: Dict = {}
    for _, row in index_df.iterrows():
        d = row["date"]
        h = int(row["hour"])
        hours_map.setdefault(d, set()).add(h)
        key_map[(d, h)] = row["key"]
    return days_set, hours_map, key_map
