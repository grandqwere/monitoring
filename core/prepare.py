from __future__ import annotations
import pandas as pd
from core.config import TIME_COL, HIDE_ALWAYS


def _coerce_numeric(df: pd.DataFrame, skip: list[str]) -> pd.DataFrame:
    """Преобразуем «тексты» в числа: запятая как десятичная, убрать мусор/единицы."""
    for c in df.columns:
        if c in skip:
            continue
        if not pd.api.types.is_numeric_dtype(df[c]):
            s = (
                df[c]
                .astype(str)
                .str.replace("\u00A0", "", regex=False)  # неразрывные пробелы
                .str.replace(" ", "", regex=False)
                .str.replace(",", ".", regex=False)      # запятая -> точка
                .str.replace(r"[^0-9eE\+\-\.]", "", regex=True)
            )
            df[c] = pd.to_numeric(s, errors="coerce")
    return df


def normalize(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Сделать датафрейм готовым к графику:
    - парсим TIME_COL в datetime, ставим как индекс и сортируем;
    - удаляем скрытые колонки;
    - приводим остальные к числам.
    """
    df = df_raw.copy()
    # Удалим скрытые колонки, если есть
    cols_to_drop = [c for c in df.columns if c in HIDE_ALWAYS]
    if cols_to_drop:
        df = df.drop(columns=cols_to_drop)

    # Время -> datetime index
    if TIME_COL not in df.columns:
        # эвристика: если первая колонка похожа на время
        first = df.columns[0]
        t = pd.to_datetime(df[first], errors="coerce", dayfirst=True)
        if t.notna().sum() == 0:
            raise ValueError("Не найден столбец времени и не удалось распознать первую колонку как время")
        time_col = first
    else:
        time_col = TIME_COL
        t = pd.to_datetime(df[time_col], errors="coerce", dayfirst=True)

    df = df.loc[t.notna()].copy()
    df.index = t[t.notna()]
    df = df.sort_index()

    # Преобразуем не-временные в числовые
    df = _coerce_numeric(df, skip=[time_col])
    return df


def choose_existing(df: pd.DataFrame, cols):
    return [c for c in cols if c in df.columns]

