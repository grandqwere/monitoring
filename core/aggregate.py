from __future__ import annotations
import pandas as pd

__all__ = ["aggregate_by"]

def aggregate_by(df: pd.DataFrame, rule: str = "1min") -> dict[str, pd.DataFrame]:
    """
    Агрегация по DatetimeIndex с заданным правилом ('1min', '20s' и т.п.).
    Возвращает: словарь DataFrame'ов — mean, p95, max, min — только по числовым колонкам.
    """
    if df is None or df.empty:
        return {"mean": df, "p95": df, "max": df, "min": df}
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("aggregate_by: ожидается DatetimeIndex")

    df = df.sort_index()
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not num_cols:
        empty = df.head(0)
        return {"mean": empty, "p95": empty, "max": empty, "min": empty}

    dfn = df[num_cols]
    return {
        "mean": dfn.resample(rule).mean(),
        "p95" : dfn.resample(rule).quantile(0.95),
        "max" : dfn.resample(rule).max(),
        "min" : dfn.resample(rule).min(),
    }
