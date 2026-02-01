# tools/recompute_stats.py
from __future__ import annotations

import io
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
import time
from typing import Dict, Iterable, List, Optional, Set, Tuple

import boto3
import numpy as np
import pandas as pd
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError


# -------------------- Константы статистики --------------------

# Имя столбца мощности, по которому строим статистику
TARGET_COLUMN = "P_total"
TIME_COLUMN = "timestamp"

# Перцентили для границ центральных интервалов
#  - P2.5 / P97.5: центральный 95%
#  - P5   / P95  : центральный 90%
#  - P0.5 / P99.5: центральный 98%
#  - P25  / P75  : центральный 50%
PERCENTILES: List[Tuple[float, str]] = [
    (0.005, "P0.5"),
    (0.025, "P2.5"),
    (0.05, "P5"),
    (0.25, "P25"),
    (0.75, "P75"),
    (0.95, "P95"),
    (0.975, "P97.5"),
    (0.995, "P99.5"),
]

AGG_MINUTES_FALLBACK = 5
PROCESS_SETTINGS_KEY = "plot_agg_minutes"

# Регэкспы
PROJECT_DIR_RE = re.compile(r".*\(\d+\)$")
DATE_DIR_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")


# -------------------- S3 конфигурация из env --------------------

def _env(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return "" if v is None else str(v)

def _env_bool(name: str, default: bool = False) -> bool:
    v = _env(name, "")
    if v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")

@dataclass(frozen=True)
class S3Cfg:
    bucket: str
    region: str
    endpoint_url: str
    access_key: str
    secret_key: str
    path_style: bool
    signature_version: str

def _load_s3_cfg() -> S3Cfg:
    cfg = S3Cfg(
        bucket=_env("S3_BUCKET"),
        region=_env("S3_REGION"),
        endpoint_url=_env("S3_ENDPOINT_URL"),
        access_key=_env("S3_ACCESS_KEY_ID"),
        secret_key=_env("S3_SECRET_ACCESS_KEY"),
        path_style=_env_bool("S3_PATH_STYLE", False),
        signature_version=_env("S3_SIGNATURE_VERSION"),
    )
    if not cfg.bucket:
        raise RuntimeError("S3_BUCKET is empty")
    if not cfg.region:
        raise RuntimeError("S3_REGION is empty")
    if not cfg.access_key or not cfg.secret_key:
        raise RuntimeError("S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY is empty")
    return cfg

def _make_s3_client(cfg: S3Cfg):
    cfg_kwargs = {}
    if cfg.signature_version:
        cfg_kwargs["signature_version"] = cfg.signature_version

    addressing = "path" if cfg.path_style else "virtual"
    boto_cfg = BotoConfig(s3={"addressing_style": addressing}, **cfg_kwargs)

    session = boto3.session.Session(
        aws_access_key_id=cfg.access_key or None,
        aws_secret_access_key=cfg.secret_key or None,
        region_name=cfg.region or None,
    )
    return session.client("s3", endpoint_url=(cfg.endpoint_url or None), config=boto_cfg)


# -------------------- S3 утилиты --------------------

def _s3_get_bytes(client, bucket: str, key: str) -> Optional[bytes]:
    try:
        obj = client.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except ClientError as e:
        code = (e.response or {}).get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NotFound"):
            return None
        raise

def _s3_put_bytes(client, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

def _s3_list_common_prefixes(client, bucket: str, prefix: str, delimiter: str = "/") -> List[str]:
    out: List[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter=delimiter):
        for cp in page.get("CommonPrefixes", []) or []:
            p = cp.get("Prefix")
            if p:
                out.append(p)
    return out

def _s3_list_objects(client, bucket: str, prefix: str) -> List[dict]:
    out: List[dict] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        out.extend(page.get("Contents", []) or [])
    return out

def _s3_prefix_has_any_object(client, bucket: str, prefix: str) -> bool:
    resp = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
    if int(resp.get("KeyCount", 0) or 0) > 0:
        return True
    return bool(resp.get("Contents"))


# -------------------- Поиск проектов и дней --------------------

def _discover_projects(client, bucket: str) -> List[str]:
    """
    Возвращает список project_prefix вида 'Name(123)/' на верхнем уровне бакета.
    Берём только те, чьё имя содержит (...) с числом внутри, и у которых есть 'All/'.
    """
    projects: List[str] = []
    # Основной путь: через Delimiter "/"
    try:
        cps = _s3_list_common_prefixes(client, bucket, prefix="", delimiter="/")
        for p in cps:
            name = p.rstrip("/")
            if not PROJECT_DIR_RE.match(name):
                continue
            if _s3_prefix_has_any_object(client, bucket, p + "All/"):
                projects.append(p)
        projects.sort()
        return projects
    except Exception:
        # Fallback: если Delimiter не поддержан — сканирование ключей.
        # Это может быть тяжелее, но спасает на нестандартных S3.
        rx = re.compile(r"^([^/]+)/All/\d{4}\.\d{2}\.\d{2}/")
        objs = _s3_list_objects(client, bucket, prefix="")
        seen: Set[str] = set()
        for o in objs:
            k = o.get("Key") or ""
            m = rx.match(k)
            if not m:
                continue
            root = m.group(1)
            if PROJECT_DIR_RE.match(root):
                seen.add(root + "/")
        projects = sorted(seen)
        return projects

def _discover_days(client, bucket: str, project_prefix: str) -> List[str]:
    """
    Список дней 'YYYY.MM.DD' в <project>/All/
    """
    base = project_prefix + "All/"
    days: List[str] = []

    # 1) через Delimiter
    try:
        cps = _s3_list_common_prefixes(client, bucket, prefix=base, delimiter="/")
        for p in cps:
            # ожидаем <project>/All/YYYY.MM.DD/
            day = p.rstrip("/").split("/")[-1]
            if DATE_DIR_RE.match(day):
                days.append(day)
        days.sort()
        if days:
            return days
    except Exception:
        pass

    # 2) fallback: по ключам
    rx = re.compile(re.escape(base) + r"(\d{4}\.\d{2}\.\d{2})/")
    objs = _s3_list_objects(client, bucket, prefix=base)
    seen: Set[str] = set()
    for o in objs:
        k = o.get("Key") or ""
        m = rx.search(k)
        if m:
            seen.add(m.group(1))
    return sorted(seen)

def _latest_day(days: List[str]) -> Optional[str]:
    if not days:
        return None
    # сортировка строк YYYY.MM.DD соответствует сортировке по дате
    return days[-1]

def _day_signature(client, bucket: str, project_prefix: str, day_str: str) -> Dict[str, object]:
    """
    Отпечаток папки дня: количество csv + max LastModified + max key.
    """
    prefix = f"{project_prefix}All/{day_str}/"
    objs = _s3_list_objects(client, bucket, prefix=prefix)
    csv_objs = [o for o in objs if (o.get("Key") or "").lower().endswith(".csv")]

    file_count = len(csv_objs)
    if file_count == 0:
        return {"day": day_str, "file_count": 0, "max_key": "", "max_last_modified": ""}

    max_key = max((o.get("Key") or "") for o in csv_objs)

    # LastModified может быть datetime
    max_lm = None
    for o in csv_objs:
        lm = o.get("LastModified")
        if lm is None:
            continue
        if max_lm is None or lm > max_lm:
            max_lm = lm

    max_lm_iso = ""
    if isinstance(max_lm, datetime):
        max_lm_iso = max_lm.replace(tzinfo=None).isoformat()

    return {
        "day": day_str,
        "file_count": int(file_count),
        "max_key": max_key,
        "max_last_modified": max_lm_iso,
    }


# -------------------- Календарь (общий + региональный) --------------------

def _parse_calendar_days(obj: dict) -> Set[date]:
    """
    Из JSON календаря берём months[].days, парсим числа (игнорируем суффиксы '*' '+').
    Возвращаем set(date(year, month, day)).
    """
    year = int(obj.get("year"))
    out: Set[date] = set()
    for m in obj.get("months", []) or []:
        try:
            month = int(m.get("month"))
        except Exception:
            continue
        days_str = str(m.get("days") or "").strip()
        if not days_str:
            continue
        for token in days_str.split(","):
            t = token.strip()
            if not t:
                continue
            mm = re.match(r"^(\d+)", t)
            if not mm:
                continue
            d = int(mm.group(1))
            try:
                out.add(date(year, month, d))
            except Exception:
                # некорректная дата (например 31 в месяце где нет) — пропускаем
                pass
    return out

def _load_calendar_json(client, bucket: str, key: str) -> Optional[dict]:
    b = _s3_get_bytes(client, bucket, key)
    if b is None:
        return None
    # календарь в UTF-8/UTF-8-SIG
    txt = b.decode("utf-8-sig", errors="replace")
    return json.loads(txt)

def _holiday_set_for_project_year(
    *,
    client,
    bucket: str,
    project_prefix: str,
    year: int,
    base_cache: Dict[int, Set[date]],
    region_cache: Dict[Tuple[str, int], Set[date]],
) -> Set[date]:
    """
    Возвращает множество выходных/праздничных дат для (project, year):
    Calendar/calendar_<year>.json + <project>/Stat/calendar_<year>_region_*.json (если есть).
    """
    # base
    if year not in base_cache:
        base_key = f"Calendar/calendar_{year}.json"
        base_obj = _load_calendar_json(client, bucket, base_key)
        base_cache[year] = _parse_calendar_days(base_obj) if base_obj else set()

    # region
    rk = (project_prefix, year)
    if rk not in region_cache:
        # ищем все файлы вида <project>/Stat/calendar_<year>_region_*.json
        stat_prefix = f"{project_prefix}Stat/calendar_{year}_region_"
        objs = _s3_list_objects(client, bucket, prefix=stat_prefix)
        keys = sorted({(o.get("Key") or "") for o in objs if (o.get("Key") or "").lower().endswith(".json")})

        reg_days: Set[date] = set()
        for k in keys:
            try:
                reg_obj = _load_calendar_json(client, bucket, k)
                if reg_obj:
                    reg_days |= _parse_calendar_days(reg_obj)
            except Exception:
                # региональный календарь битый — игнорируем, чтобы не ронять весь проект
                continue

        region_cache[rk] = reg_days

    return set(base_cache[year]) | set(region_cache[rk])


# -------------------- Чтение CSV и построение профиля дня --------------------

def _read_csv_from_bytes(data: bytes) -> pd.DataFrame:
    """
    Базовый формат: ';' + decimal ',' + UTF-8-SIG.
    Делаем fallback на auto-sep.
    """
    # 1) основной формат
    try:
        df = pd.read_csv(
            io.BytesIO(data),
            sep=";",
            decimal=",",
            encoding="utf-8-sig",
            engine="python",
        )
        if df.shape[1] >= 2:
            return df
    except Exception:
        pass

    # 2) fallback
    return pd.read_csv(io.BytesIO(data), sep=None, engine="python", encoding="utf-8-sig")

def _read_day_dataframe(
    client,
    bucket: str,
    project_prefix: str,
    day_str: str,
    target_col: str,
) -> pd.DataFrame:
    """
    Читает все CSV под <project>/All/<day>/..., собирает (timestamp, target_col).
    Битые/нестандартные файлы пропускает.
    """
    prefix = f"{project_prefix}All/{day_str}/"
    objs = _s3_list_objects(client, bucket, prefix=prefix)
    keys = sorted(
        (o.get("Key") or "")
        for o in objs
        if (o.get("Key") or "").lower().endswith(".csv")
    )

    parts: List[pd.DataFrame] = []
    for k in keys:
        try:
            b = _s3_get_bytes(client, bucket, k)
            if not b:
                continue
            df = _read_csv_from_bytes(b)

            if TIME_COLUMN not in df.columns:
                continue
            if target_col not in df.columns:
                continue

            sub = df[[TIME_COLUMN, target_col]].copy()
            sub[TIME_COLUMN] = pd.to_datetime(sub[TIME_COLUMN], errors="coerce")
            sub = sub.dropna(subset=[TIME_COLUMN])
            if sub.empty:
                continue

            sub[target_col] = pd.to_numeric(sub[target_col], errors="coerce")
            parts.append(sub)
        except Exception:
            continue

    if not parts:
        return pd.DataFrame(columns=[TIME_COLUMN, target_col])

    out = pd.concat(parts, ignore_index=True)
    out = out.dropna(subset=[TIME_COLUMN])
    out = out.sort_values(TIME_COLUMN).drop_duplicates(subset=[TIME_COLUMN], keep="last")
    return out

def _build_day_series(
    df: pd.DataFrame,
    *,
    day_str: str,
    agg_minutes: int,
    target_col: str,
) -> pd.Series:
    """
    Возвращает суточный ряд (index: 2000-01-01 00:00.., freq=agg_minutes) с mean по интервалам.
    """
    # день по имени папки
    day_dt = pd.to_datetime(day_str, format="%Y.%m.%d", errors="coerce")
    if pd.isna(day_dt) and not df.empty:
        day_dt = pd.to_datetime(df[TIME_COLUMN].min(), errors="coerce").floor("D")
    if pd.isna(day_dt):
        day_dt = pd.Timestamp("1970-01-01")

    day_start = day_dt.floor("D")
    n = int(24 * 60 / agg_minutes)
    bins = pd.date_range(day_start, periods=n, freq=f"{agg_minutes}min")

    base = pd.Timestamp("2000-01-01")
    x = pd.date_range(base, periods=n, freq=f"{agg_minutes}min")

    if df.empty:
        s = pd.Series(index=x, data=np.nan, name=day_str)
        return s

    s0 = df.set_index(TIME_COLUMN)[target_col]
    s0 = pd.to_numeric(s0, errors="coerce")
    s_m = s0.resample(f"{agg_minutes}min").mean()
    s_m = s_m.reindex(bins)
    s_m.index = x
    s_m.name = day_str
    return s_m

def _compute_quantiles(series_list: List[pd.Series], agg_minutes: int) -> pd.DataFrame:
    base = pd.Timestamp("2000-01-01")
    n = int(24 * 60 / agg_minutes)
    x = pd.date_range(base, periods=n, freq=f"{agg_minutes}min")

    cols = [label for _, label in PERCENTILES]

    if not series_list:
        out = pd.DataFrame(index=x, data={c: np.nan for c in cols})
        return out

    df = pd.concat([s.reindex(x) for s in series_list], axis=1).reindex(x)

    data: Dict[str, pd.Series] = {}
    for p, label in PERCENTILES:
        data[label] = df.quantile(p, axis=1, numeric_only=True)

    out = pd.DataFrame(data, index=x)
    return out



# -------------------- process_settings.json (agg_minutes) --------------------

def _get_agg_minutes_for_project(client, bucket: str, project_prefix: str) -> int:
    """
    Читает <project>/config/process_settings.json и берёт plot_agg_minutes.
    Если файла/ключа нет — fallback.
    """
    key = f"{project_prefix}config/process_settings.json"
    b = _s3_get_bytes(client, bucket, key)
    if not b:
        return int(AGG_MINUTES_FALLBACK)
    try:
        obj = json.loads(b.decode("utf-8-sig", errors="replace"))
        v = int(obj.get(PROCESS_SETTINGS_KEY, AGG_MINUTES_FALLBACK))
        if v <= 0:
            return int(AGG_MINUTES_FALLBACK)
        return int(v)
    except Exception:
        return int(AGG_MINUTES_FALLBACK)


# -------------------- State --------------------

def _read_state(client, bucket: str, project_prefix: str) -> dict:
    key = f"{project_prefix}Stat/state.json"
    b = _s3_get_bytes(client, bucket, key)
    if not b:
        return {}
    try:
        return json.loads(b.decode("utf-8-sig", errors="replace"))
    except Exception:
        return {}

def _write_state(client, bucket: str, project_prefix: str, state: dict) -> None:
    key = f"{project_prefix}Stat/state.json"
    data = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _s3_put_bytes(client, bucket, key, data, content_type="application/json; charset=utf-8")


# -------------------- Основной процесс --------------------

def _time_labels(agg_minutes: int, count: int) -> List[str]:
    """Список меток времени (HH:MM) для строк статистики."""
    labels: List[str] = []
    for i in range(count):
        minutes = i * int(agg_minutes)
        h = minutes // 60
        m = minutes % 60
        labels.append(f"{h:02d}:{m:02d}")
    return labels


def _write_quantile_csv(
    client,
    bucket: str,
    project_prefix: str,
    filename: str,
    qdf: pd.DataFrame,
    *,
    agg_minutes: int,
) -> None:
    out = qdf.copy()
    cols = [label for _, label in PERCENTILES]
    out.insert(0, "time", _time_labels(agg_minutes, len(out)))
    out = out[["time"] + cols]

    buf = io.StringIO()
    out.to_csv(buf, index=False, sep=";", decimal=",")
    data = buf.getvalue().encode("utf-8-sig")

    key = f"{project_prefix}Stat/{filename}"
    _s3_put_bytes(client, bucket, key, data, content_type="text/csv; charset=utf-8")

def _recompute_project(
    *,
    client,
    bucket: str,
    project_prefix: str,
    base_calendar_cache: Dict[int, Set[date]],
    region_calendar_cache: Dict[Tuple[str, int], Set[date]],
) -> str:
    project_name = project_prefix.rstrip("/").split("/")[-1]
    print(f"\n== Проект: {project_name} ==")

    if not _s3_prefix_has_any_object(client, bucket, project_prefix + "All/"):
        print("  нет папки All/ — пропуск")
        return "skipped_no_all"

    days = _discover_days(client, bucket, project_prefix)
    last_day = _latest_day(days)
    if not last_day:
        print("  нет дней в All/ — пропуск")
        return "skipped_no_days"

    sig = _day_signature(client, bucket, project_prefix, last_day)
    state = _read_state(client, bucket, project_prefix)

    agg_minutes = _get_agg_minutes_for_project(client, bucket, project_prefix)

    prev_day = str(state.get("last_day") or "")
    prev_count = int(state.get("last_day_file_count") or 0)
    prev_lm = str(state.get("last_day_max_last_modified") or "")
    prev_max_key = str(state.get("last_day_max_key") or "")

    same_input = (
        prev_day == sig["day"]
        and prev_count == int(sig["file_count"])
        and prev_lm == str(sig["max_last_modified"])
        and prev_max_key == str(sig["max_key"])
    )

    prev_target = str(state.get("target_column") or "")
    prev_agg = int(state.get("agg_minutes") or 0)
    prev_percentiles = list(state.get("percentiles") or [])
    cur_percentiles = [float(p) for p, _ in PERCENTILES]

    same_params = (
        prev_target == TARGET_COLUMN
        and prev_agg == int(agg_minutes)
        and prev_percentiles == cur_percentiles
    )

    # Если выходных файлов нет (или они пустые), пересчёт обязателен
    wd_ok = bool(_s3_get_bytes(client, bucket, f"{project_prefix}Stat/weekday.csv"))
    we_ok = bool(_s3_get_bytes(client, bucket, f"{project_prefix}Stat/weekend.csv"))
    outputs_ok = wd_ok and we_ok

    if same_input and same_params and outputs_ok:
        print(f"  последняя дата {last_day}: новых файлов нет и параметры не менялись — пересчёт не нужен")
        return "skipped_no_changes"

    if not same_input:
        reason = "обнаружены изменения во входных данных"
    elif not same_params:
        reason = "параметры расчёта изменились"
    else:
        reason = "выходные файлы отсутствуют/пустые"

    print(f"  последняя дата {last_day}: {reason}, пересчитываю все дни (agg_minutes={agg_minutes})")

    weekday_series: List[pd.Series] = []
    weekend_series: List[pd.Series] = []

    for d in days:
        try:
            y = int(d.split(".")[0])
        except Exception:
            y = None

        holiday_set = set()
        if y is not None:
            holiday_set = _holiday_set_for_project_year(
                client=client,
                bucket=bucket,
                project_prefix=project_prefix,
                year=y,
                base_cache=base_calendar_cache,
                region_cache=region_calendar_cache,
            )

        try:
            dd = date(int(d[0:4]), int(d[5:7]), int(d[8:10]))
        except Exception:
            dd = None

        is_holiday = bool(dd in holiday_set) if dd else False

        df = _read_day_dataframe(client, bucket, project_prefix, d, TARGET_COLUMN)
        s = _build_day_series(df, day_str=d, agg_minutes=agg_minutes, target_col=TARGET_COLUMN)

        if is_holiday:
            weekend_series.append(s)
        else:
            weekday_series.append(s)

    q_weekday = _compute_quantiles(weekday_series, agg_minutes)
    q_weekend = _compute_quantiles(weekend_series, agg_minutes)

    _write_quantile_csv(client, bucket, project_prefix, "weekday.csv", q_weekday, agg_minutes=agg_minutes)
    _write_quantile_csv(client, bucket, project_prefix, "weekend.csv", q_weekend, agg_minutes=agg_minutes)

    new_state = {
        "schema_version": 2,
        "computed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "last_day": sig["day"],
        "last_day_file_count": int(sig["file_count"]),
        "last_day_max_key": str(sig["max_key"]),
        "last_day_max_last_modified": str(sig["max_last_modified"]),
        "agg_minutes": int(agg_minutes),
        "target_column": TARGET_COLUMN,
        "percentiles": [float(p) for p, _ in PERCENTILES],
        "percentile_labels": [label for _, label in PERCENTILES],
        "days_total": int(len(days)),
        "days_weekday": int(len(weekday_series)),
        "days_weekend": int(len(weekend_series)),
    }
    _write_state(client, bucket, project_prefix, new_state)

    print(f"  готово: Stat/weekday.csv, Stat/weekend.csv, Stat/state.json")
    return "ok"


def main() -> int:
    t_total_start = time.perf_counter()

    cfg = _load_s3_cfg()
    client = _make_s3_client(cfg)

    base_calendar_cache: Dict[int, Set[date]] = {}
    region_calendar_cache: Dict[Tuple[str, int], Set[date]] = {}

    projects = _discover_projects(client, cfg.bucket)
    print(f"Найдено проектов: {len(projects)}")

    for p in projects:
        project_name = p.rstrip("/").split("/")[-1]
        t_proj_start = time.perf_counter()
        status = "ok"
        try:
            status = _recompute_project(
                client=client,
                bucket=cfg.bucket,
                project_prefix=p,
                base_calendar_cache=base_calendar_cache,
                region_calendar_cache=region_calendar_cache,
            )
        except Exception as e:
            status = "error"
            # не валим весь run из-за одного проекта
            print(f"\n!! Ошибка проекта {p}: {e}")

        dt = time.perf_counter() - t_proj_start
        print(f"TIME project={project_name} seconds={dt:.3f} status={status}")

    total_dt = time.perf_counter() - t_total_start
    print(f"\nTIME total seconds={total_dt:.3f} projects={len(projects)}")
    print("\nГотово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
