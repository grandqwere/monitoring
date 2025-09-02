from __future__ import annotations
import pandas as pd
from math import ceil


def stride(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    """Простое прореживание «по шагу», чтобы держать до ~max_points точек."""
    if len(df) <= max_points:
        return df
    step = ceil(len(df) / max_points)
    return df.iloc[::step].copy()


def resample(df: pd.DataFrame, rule: str, agg: str) -> pd.DataFrame:
    """Агрегация по времени.
    rule: '1min'|'5min'|'15min' (регистр не важен)
    agg:  'mean'|'max'|'min'|'p95'
    """
    rule = rule.lower()
    if rule.endswith("min") is False:
        raise ValueError("rule должен быть в минутах, напр. '1min'/'5min'/'15min'")

    if agg == "p95":
        return df.resample(rule).quantile(0.95)
    elif agg in {"mean", "max", "min"}:
        return getattr(df.resample(rule), agg)()
    else:
        raise ValueError("agg должен быть mean|max|min|p95")
