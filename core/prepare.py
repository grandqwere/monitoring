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


def _parse_time_first_col(col: pd.Series) -> pd.Series:
    """Парсим первый столбец как время максимально детерминированно.

    В реальных выгрузках встречается формат:
      YYYY-MM-DD HH:MM:SS,ffff
    где дробная часть секунды идёт через запятую и чаще всего имеет 4 знака (1e-4 сек).

    Важно: авто-парсинг pandas/dateutil может "съедать" дробную часть, превращая разные
    значения времени в одинаковые секунды -> появляются дубликаты индекса и «скачки» на графике.
    """
    # уже datetime -> как есть
    if pd.api.types.is_datetime64_any_dtype(col):
        return col

    # 1) пробуем строгий парсинг "YYYY-MM-DD[ T]HH:MM:SS[,.]frac"
    s = col.astype(str).str.strip()
    m = s.str.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[,.]\d+)?$", na=False)
    if m.mean() >= 0.8:
        s2 = s.str.replace("T", " ", regex=False)
        ex = s2.str.extract(
            r"^(?P<base>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:[,.](?P<frac>\d+))?$"
        )
        base = ex["base"]
        frac = ex["frac"].fillna("0")
        # frac хранит ДОЛЮ секунды (не микросекунды): дополняем справа до 6 знаков
        frac = frac.str.slice(0, 6).str.ljust(6, "0")
        norm = base + "." + frac
        ts_try = pd.to_datetime(norm, format="%Y-%m-%d %H:%M:%S.%f", errors="coerce", utc=False)
        if ts_try.notna().sum() >= len(s) * 0.8:
            return ts_try

    # 2) fallback: штатный авто-парсинг
    ts = pd.to_datetime(
        col,
        errors="coerce",
        infer_datetime_format=True,
        utc=False,
    )

    # 3) если авто-парсинг не сработал (редко), пробуем секунды от эпохи
    if ts.notna().sum() < len(col) * 0.8:
        try:
            ts2 = pd.to_datetime(col, unit="s", errors="coerce", utc=False)
            if ts2.notna().sum() >= len(col) * 0.8:
                ts = ts2
        except Exception:
            pass

    return ts



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
    ts = _parse_time_first_col(df[time_col])

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
