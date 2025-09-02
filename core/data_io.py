from __future__ import annotations
from typing import Optional, Iterable
import pandas as pd
import streamlit as st
from io import StringIO


@st.cache_data(show_spinner=False)
def read_csv_local(uploaded_file, usecols: Optional[Iterable[str]] = None) -> pd.DataFrame:
    """Прочитать CSV из локально загруженного файла.
    * Поддерживает автоопределение разделителя.
    * Кэшируется по содержимому файла + списку колонок usecols.
    """
    # Получаем байты без сдвига курсора
    try:
        content: bytes = uploaded_file.getvalue()
    except Exception:
        # fallback для совместимости
        pos = uploaded_file.tell()
        content = uploaded_file.read()
        uploaded_file.seek(pos)

    txt = content.decode("utf-8", errors="ignore")

    # Пробуем разные разделители
    for sep in [";", ",", "\t", "|"]:
        try:
            df = pd.read_csv(StringIO(txt), sep=sep, engine="python", usecols=usecols)
            # если оказалась одна колонка, вероятно разделитель не тот — пробуем дальше
            if df.shape[1] == 1 and sep != "|" and usecols is None:
                continue
            return df
        except Exception:
            continue
    # Пусть pandas сам решит
    return pd.read_csv(StringIO(txt), sep=None, engine="python", usecols=usecols)


# Заглушка под S3 (добавим на следующем этапе)
def read_csv_s3(bucket: str, key: str, usecols: Optional[Iterable[str]] = None) -> pd.DataFrame:
    raise NotImplementedError("S3 подключим на следующем шаге")
