from __future__ import annotations
import pandas as pd

def _to_num_series(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s):
        return s
    if s.dtype.kind == "O":
        try:
            # заменяем запятую на точку и убираем пробелы — частый случай
            return pd.to_numeric(
                s.astype(str).str.replace(",", ".", regex=False).str.replace(" ", "", regex=False),
                errors="ignore",
            )
        except Exception:
            return s
    return s

def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """
    • Время берём из ПЕРВОГО столбца файла и делаем DatetimeIndex.
    • Колонку uptime удаляем, если встретится.
    • Остальные столбцы пробуем привести к числам.
    """
    if df is None or df.empty:
        return df

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # 1) индекс времени: ПЕРВЫЙ столбец
    time_col = df.columns[0]
    ts = pd.to_datetime(df[time_col], errors="coerce", infer_datetime_format=True, utc=False)
    if ts.notna().sum() < len(df) * 0.8:
        # ещё раз пробуем — вдруг числа в виде секунд/мс от эпохи
        try:
            ts2 = pd.to_datetime(df[time_col], unit="s", errors="coerce", utc=False)
            if ts2.notna().sum() >= len(df) * 0.8:
                ts = ts2
        except Exception:
            pass
    df = df.drop(columns=[time_col])
    df.index = ts
    df = df.sort_index()

    # 2) убрать uptime (если есть)
    to_drop = [c for c in df.columns if c.lower() == "uptime"]
    if to_drop:
        df = df.drop(columns=to_drop)

    # 3) привести числовые
    for c in df.columns:
        df[c] = _to_num_series(df[c])

    return df
