import streamlit as st
import pandas as pd
from io import StringIO

st.set_page_config(page_title="Power Monitoring Viewer", layout="wide")
st.title("Просмотр графиков из CSV")

st.markdown(
    "1) Загрузите CSV. 2) Выберите столбец времени. 3) Отметьте, что рисовать. "
    "Если графика нет — ниже появятся подсказки."
)

def read_csv_smart(uploaded_file) -> pd.DataFrame:
    """Пытаемся корректно прочитать CSV с любым разделителем и десятичной запятой."""
    # Пробуем популярные разделители
    seps = [";", ",", "\t", "|"]
    content = uploaded_file.read()
    for sep in seps:
        try:
            df = pd.read_csv(StringIO(content.decode("utf-8", errors="ignore")),
                             sep=sep, engine="python")
            # Heuristic: если 1 колонка на весь файл — вероятно, разделитель не тот
            if df.shape[1] == 1 and sep != seps[-1]:
                continue
            return df
        except Exception:
            continue
    # fallback: пусть pandas сам решит
    uploaded_file.seek(0)
    return pd.read_csv(uploaded_file, sep=None, engine="python")

def coerce_numeric_cols(df: pd.DataFrame, skip_cols: list[str]) -> pd.DataFrame:
    """Преобразуем 'тексты' в числа: убираем пробелы, заменяем запятую на точку, режем суффиксы."""
    for c in df.columns:
        if c in skip_cols:
            continue
        if not pd.api.types.is_numeric_dtype(df[c]):
            s = (df[c].astype(str)
                    .str.replace("\u00A0", "", regex=False)  # неразрывные пробелы
                    .str.replace(" ", "", regex=False)
                    .str.replace(",", ".", regex=False)      # запятая → точка
                    .str.replace(r"[^0-9eE\+\-\.]", "", regex=True))  # убираем всё, кроме цифр и знаков
            df[c] = pd.to_numeric(s, errors="coerce")
    return df

uploaded = st.file_uploader("Загрузить CSV-файл", type=["csv"])

if uploaded:
    df = read_csv_smart(uploaded)

    # Уберём пустые колонки и приведём имена
    df = df.loc[:, ~df.columns.astype(str).str.fullmatch(r"\s*")]
    df.columns = [str(c).strip() for c in df.columns]

    st.caption(f"Файл прочитан: {df.shape[0]} строк × {df.shape[1]} столбцов")
    with st.expander("Показать первые строки таблицы"):
        st.dataframe(df.head(30), use_container_width=True)

    # Выбор столбца времени
    guess_time = next((c for c in df.columns
                       if any(k in c.lower() for k in ["time", "timestamp", "время", "дата"])), None)
    time_col = st.selectbox("Столбец времени", options=["(без времени)"] + list(df.columns),
                            index=(df.columns.tolist().index(guess_time) + 1) if guess_time in df.columns else 0)

    # Готовим индекс времени (если выбран)
    skip_for_numeric = []
    if time_col != "(без времени)":
        skip_for_numeric = [time_col]
        # Парсим время
        t = pd.to_datetime(df[time_col], errors="coerce", dayfirst=True)
        if t.isna().all():
            st.warning("Не удалось распознать время – график построится по порядку строк.")
        else:
            df = df.loc[~t.isna()].copy()
            df.index = t[~t.isna()]
            df = df.sort_index()
    else:
        df.index.name = "index"

    # Превращаем текстовые числа в числовые
    df = coerce_numeric_cols(df, skip_cols=skip_for_numeric)

    # Выбор колонок для графика
    numeric_cols = [c for c in df.columns if c not in skip_for_numeric and pd.api.types.is_numeric_dtype(df[c])]
    preselect = [c for c in numeric_cols if len(c) and c[0].upper() in list("PSQIU")] or numeric_cols[:3]
    chosen = st.multiselect("Какие серии рисовать", options=numeric_cols, default=preselect)

    if not chosen:
        st.info("Отметьте хотя бы одну числовую колонку выше.")
    else:
        # Небольшой даунсэмплинг по желанию (для тяжёлых файлов)
        if len(df) > 200_000:
            st.caption("Много точек — для отзывчивости берём каждую 5-ю.")
            df_plot = df.iloc[::5]
        else:
            df_plot = df

        st.line_chart(df_plot[chosen], use_container_width=True)

        # Мини-диагностика
        with st.expander("Диагностика"):
            st.write("Типы столбцов:")
            st.write(df[chosen].dtypes)
else:
    st.info("Загрузите CSV — и ниже появится график.")
