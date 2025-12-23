from __future__ import annotations
import pandas as pd

def _to_num(s: pd.Series) -> pd.Series:
    """
    Жёстко приводим к числам:
    - убираем неразрывные пробелы и обычные пробелы,
    - заменяем запятую на точку,
    - pd.to_numeric(..., errors='coerce') — любые сбои -> NaN (не ломают тип столбца).
    """
    if pd.api.types.is_numeric_dtype(s):
        return s
    if s.dtype.kind == "O":
        try:
            s2 = (
                s.astype(str)
                 .str.replace("\u00a0", "", regex=False)   # неразрывный пробел
                 .str.replace(" ", "", regex=False)
                 .str.replace(",", ".", regex=False)
            )
            return pd.to_numeric(s2, errors="coerce")
        except Exception:
            return s
    return s

def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """
    • Индекс времени берём ИСКЛЮЧИТЕЛЬНО из ПЕРВОГО столбца.
    • Колонку 'uptime' (в любом регистре) удаляем.
    • Остальные столбцы приводим к числам (с запятой и пробелами), сбойные значения -> NaN.
    """
    if df is None or df.empty:
        return df

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # 1) индекс времени — первый столбец файла
    time_col = df.columns[0]
    ts = pd.to_datetime(
        df[time_col],
        errors="coerce",
        infer_datetime_format=True,
        utc=False,
    )
    # если авто-парсинг не сработал (редко), пробуем секунды от эпохи
    if ts.notna().sum() < len(df) * 0.8:
        try:
            ts2 = pd.to_datetime(df[time_col], unit="s", errors="coerce", utc=False)
            if ts2.notna().sum() >= len(df) * 0.8:
                ts = ts2
        except Exception:
            pass

    # Удаляем строки, где время не распарсилось (NaT),
    # иначе ресемплинг/агрегация может вести себя некорректно.
    mask = ts.notna()
    if mask.sum() == 0:
        return df.head(0)
    df = df.loc[mask].copy()
    ts = ts.loc[mask]

    df = df.drop(columns=[time_col])
    df.index = ts.values
    df = df.sort_index()

    # 2) убрать uptime
    drop = [c for c in df.columns if c.lower() == "uptime"]
    if drop:
        df = df.drop(columns=drop)

    # 3) привести к числам (с безопасным coerce)
    for c in df.columns:
        df[c] = _to_num(df[c])

    return df
