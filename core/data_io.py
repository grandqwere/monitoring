from __future__ import annotations

import io
import os
import re
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

def read_bytes_s3(key: str) -> bytes:
    """
    Прочитать файл из S3 и вернуть как bytes.
    Возвращает b"" при ошибке/отсутствии объекта.
    """
    try:
        client = _get_s3_client()
        obj = client.get_object(Bucket=_bucket_name(), Key=key)
        return obj["Body"].read()
    except Exception:
        return b""


def read_text_s3(key: str) -> str:
    """
    Прочитать текстовый файл из S3 и вернуть как str.
    Возвращает "" при ошибке/отсутствии объекта.
    """
    try:
        client = _get_s3_client()
        obj = client.get_object(Bucket=_bucket_name(), Key=key)
        data = obj["Body"].read()
        try:
            return data.decode("utf-8").strip()
        except UnicodeDecodeError:
            # запасной вариант, если файл в win-1251
            return data.decode("cp1251", errors="ignore").strip()
    except Exception:
        return ""

def _current_prefix_base() -> str:
    """Текущий префикс как 'prefix/' или ''."""
    curr = str(st.session_state.get("current_prefix", "") or "").strip().rstrip("/")
    return f"{curr}/" if curr else ""


def s3_prefix_has_any_object(prefix: str) -> bool:
    """
    Быстрая проверка: есть ли на сервере хоть один объект под данным Prefix.
    """
    try:
        client = _get_s3_client()
        resp = client.list_objects_v2(Bucket=_bucket_name(), Prefix=prefix, MaxKeys=1)
        # KeyCount надежнее, но бывает не у всех реализаций; подстрахуемся Contents
        if int(resp.get("KeyCount", 0)) > 0:
            return True
        return bool(resp.get("Contents"))
    except Exception:
        return False


def all_day_has_any_data(d: date) -> bool:
    """
    Есть ли хотя бы один файл в папке All/YYYY.MM.DD/ для заданного дня.
    Учитывает демо-маппинг (через build_all_day_prefix_for).
    """
    from core.s3_paths import build_all_day_prefix_for
    day_prefix = build_all_day_prefix_for(d)  # уже с trailing "/"
    return s3_prefix_has_any_object(day_prefix)


def s3_latest_available_day_all() -> date | None:
    """
    Находит самый поздний день, присутствующий в <prefix>/All/YYYY.MM.DD/
    Возвращает date или None, если ничего не найдено.
    """
    try:
        client = _get_s3_client()
        bucket = _bucket_name()
        base = _current_prefix_base() + "All/"

        dates: list[date] = []

        # 1) Пытаемся через Delimiter получить "папки" дней (CommonPrefixes)
        paginator = client.get_paginator("list_objects_v2")
        try:
            for page in paginator.paginate(Bucket=bucket, Prefix=base, Delimiter="/"):
                for cp in page.get("CommonPrefixes", []) or []:
                    p = cp.get("Prefix") or ""
                    # ожидаем .../All/YYYY.MM.DD/
                    # поддерживаем как "All/2025.08.25/", так и "<prefix>/All/2025.08.25/"
                    m = re.search(r"(?:^|/)All/(\d{4}\.\d{2}\.\d{2})/?$", p)
                    if m:
                        y, mo, da = m.group(1).split(".")
                        dates.append(date(int(y), int(mo), int(da)))
        except Exception:
            # если Delimiter не поддержан, уйдем в fallback
            pass

        # 2) Fallback: сканируем ключи и вытаскиваем дату из .../All/YYYY.MM.DD/...
        if not dates:
            # поддерживаем как "All/2025.08.25/...", так и "<prefix>/All/2025.08.25/..."
            rx = re.compile(r"(?:^|/)All/(\d{4}\.\d{2}\.\d{2})/")
            for page in paginator.paginate(Bucket=bucket, Prefix=base):
                for obj in page.get("Contents", []) or []:
                    k = obj.get("Key") or ""
                    m = rx.search(k)
                    if m:
                        y, mo, da = m.group(1).split(".")
                        try:
                            dates.append(date(int(y), int(mo), int(da)))
                        except Exception:
                            pass

        return max(dates) if dates else None
    except Exception:
        return None

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
