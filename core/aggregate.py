from __future__ import annotations
import pandas as pd

def aggregate_20s(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    Возвращает словарь:
      mean: средние по 20с
      p95 : 95-й перцентиль по 20с
      max : максимум внутри 20с
      min : минимум внутри 20с
    Только по числовым колонкам; индекс — DatetimeIndex.
    """
    if df is None or df.empty:
        return {"mean": df, "p95": df, "max": df, "min": df}

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("aggregate_20s: ожидается DatetimeIndex")

    df = df.sort_index()
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not num_cols:
        return {"mean": df.head(0), "p95": df.head(0), "max": df.head(0), "min": df.head(0)}

    dfn = df[num_cols]
    return {
        "mean": dfn.resample("20s").mean(),
        "p95" : dfn.resample("20s").quantile(0.95),
        "max" : dfn.resample("20s").max(),
        "min" : dfn.resample("20s").min(),
    }
