import streamlit as st
import pandas as pd

st.set_page_config(page_title="Power Monitoring Viewer", layout="wide")
st.title("Просмотр графиков (через Streamlit)")

st.markdown(
    "Это тестовая версия. Можешь загрузить CSV с компьютера и посмотреть график. "
    "На следующем шаге подключим чтение прямо из S3."
)

uploaded = st.file_uploader("Загрузить CSV-файл", type=["csv"])
if uploaded:
    try:
        # Авто-определение разделителя
        df = pd.read_csv(uploaded, sep=None, engine="python")
        # Ищем колонку времени
        time_col = None
        for c in df.columns:
            if any(k in c.lower() for k in ["time", "timestamp", "время", "дата"]):
                time_col = c
                break
        if time_col:
            df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
            df = df.dropna(subset=[time_col]).sort_values(time_col)
            df = df.set_index(time_col)

        st.write("Размер таблицы:", df.shape)
        st.dataframe(df.head(20))

        # Убираем явно нечисловые колонки из графика
        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        if numeric_cols:
            st.line_chart(df[numeric_cols])
        else:
            st.info("Не нашёл числовых колонок для графика.")
    except Exception as e:
        st.error(f"Ошибка чтения файла: {e}")
else:
    st.info("Здесь появится график после загрузки CSV.")
