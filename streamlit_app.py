import hashlib
from io import StringIO
from math import ceil
from typing import Dict, List

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---------- НАСТРОЙКИ ПО УМОЛЧАНИЮ ----------
TIME_CANDIDATES = ["timestamp", "time", "время", "дата"]
HIDE_ALWAYS = {"uptime"}
MAX_POINTS_MAIN = 5000   # лимит точек на верхнем графике
MAX_POINTS_GROUP = 5000  # лимит точек на групповых
DEFAULT_PRESET = ["P_total", "S_total", "Q_total"]  # что предлагать по умолчанию
AXIS_LABELS = {"A1": "A1 (слева)", "A2": "A2 (справа)", "A3": "A3 (внутр. слева)", "A4": "A4 (внутр. справа)"}

GROUPS: Dict[str, List[str]] = {
    "Мощности (общие)": ["P_total", "S_total", "Q_total"],
    "Токи L1–L3": ["Irms_L1", "Irms_L2", "Irms_L3"],
    "Напряжения фазы": ["Urms_L1", "Urms_L2", "Urms_L3"],
    "Линейные U": ["U_L1_L2", "U_L2_L3", "U_L3_L1"],
    "PF": ["pf_total", "pf_L1", "pf_L2", "pf_L3"],
    "Углы": ["angle_L1_L2", "angle_L2_L3", "angle_L3_L1"],
}


# ---------- УТИЛИТЫ ----------
@st.cache_data(show_spinner=False)
def _read_csv_cached(content_bytes: bytes) -> pd.DataFrame:
    """
    Умно читаем CSV: авторазделитель, поддержка запятой как десятичной, удаляем мусор.
    Кэшируем по содержимому файла.
    """
    txt = content_bytes.decode("utf-8", errors="ignore")
    # Пробуем разные разделители
    for sep in [";", ",", "\t", "|"]:
        try:
            df = pd.read_csv(StringIO(txt), sep=sep, engine="python")
            if df.shape[1] == 1 and sep != "|":
                continue
            break
        except Exception:
            continue
    else:
        # пусть pandas сам
        df = pd.read_csv(StringIO(txt), sep=None, engine="python")

    # Чистим пустые/пробельные имена
    df = df.loc[:, ~df.columns.astype(str).str.fullmatch(r"\s*")]
    df.columns = [str(c).strip() for c in df.columns]
    return df


def detect_time_col(df: pd.DataFrame) -> str | None:
    cols_lower = {c.lower(): c for c in df.columns}
    for cand in TIME_CANDIDATES:
        if cand in cols_lower:
            return cols_lower[cand]
    # эвристика: первая колонка, если она похожа на время/дату
    first = df.columns[0]
    sample = pd.to_datetime(df[first], errors="coerce", dayfirst=True)
    if sample.notna().sum() >= max(3, int(0.01 * len(sample))):
        return first
    return None


def coerce_numeric(df: pd.DataFrame, skip: List[str]) -> pd.DataFrame:
    """
    Преобразуем «тексты» в числа: запятая как десятичная, лишние символы/пробелы.
    """
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
                .str.replace(r"[^0-9eE\+\-\.]", "", regex=True)  # удалим единицы измерения и текст
            )
            df[c] = pd.to_numeric(s, errors="coerce")
    return df


def downsample_stride(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    """
    Простое и быстрое прореживание «по шагу» (визуально ок до 5–10k точек).
    """
    if len(df) <= max_points:
        return df
    step = ceil(len(df) / max_points)
    return df.iloc[::step].copy()


def plot_main(df_time_indexed: pd.DataFrame, selected: List[str], axis_map: Dict[str, str], height: int):
    """
    Верхний «свободный» график с до 4 осей Y.
    axis_map: {column -> "A1"|"A2"|"A3"|"A4"}
    """
    if not selected:
        st.info("Выберите серии для верхнего графика.")
        return

    df_plot = downsample_stride(df_time_indexed[selected], MAX_POINTS_MAIN)

    # Настройка осей
    layout_kwargs = dict(
        margin=dict(t=36, r=16, b=40, l=60),
        height=height,
        xaxis=dict(title="Время", showspikes=True, spikemode="across", spikethickness=1),
        plot_bgcolor="#0b0f14",
        paper_bgcolor="#0b0f14",
        legend=dict(orientation="h"),
    )
    # Базовая левая ось
    yaxes = {
        "A1": dict(title="A1", titlefont=dict(size=12), tickfont=dict(size=11), gridcolor="#1a2430"),
        "A2": dict(title="A2", overlaying="y", side="right"),
        "A3": dict(title="A3", overlaying="y", side="left", position=0.06, showgrid=False),
        "A4": dict(title="A4", overlaying="y", side="right", position=0.94, showgrid=False),
    }

    fig = go.Figure()
    # Установим первую ось явно как y
    layout_kwargs["yaxis"] = yaxes["A1"]
    layout_kwargs["yaxis2"] = yaxes["A2"]
    layout_kwargs["yaxis3"] = yaxes["A3"]
    layout_kwargs["yaxis4"] = yaxes["A4"]

    # Подписи осей — по первой попавшейся серии на оси
    axis_first_title: Dict[str, str] = {}
    for col in selected:
        ax = axis_map.get(col, "A1")
        if ax not in axis_first_title:
            axis_first_title[ax] = col
            # обновим заголовок оси именем первой серии
            idx = "" if ax == "A1" else ax[-1]  # "" | "2" | "3" | "4"
            layout_kwargs[f"yaxis{idx}"]["title"] = col

    # Добавляем серии
    for col in selected:
        axis_code = axis_map.get(col, "A1")
        yref = {"A1": "y", "A2": "y2", "A3": "y3", "A4": "y4"}[axis_code]
        fig.add_trace(
            go.Scattergl(
                x=df_plot.index,
                y=df_plot[col],
                mode="lines",
                name=col,
                yaxis=yref,
                hovertemplate="%{x}<br>" + col + ": %{y}<extra></extra>",
            )
        )

    fig.update_layout(**layout_kwargs)
    st.plotly_chart(fig, use_container_width=True, theme=None)


def plot_group(
    df_time_indexed: pd.DataFrame,
    group_name: str,
    cols: List[str],
    height: int,
    two_axes: bool = False,
):
    """
    Одна панель группы. Если two_axes=True — делаем Q на правую ось, остальное слева.
    """
    present = [c for c in cols if c in df_time_indexed.columns]
    if not present:
        return

    with st.container(border=True):
        st.markdown(f"**{group_name}**")
        # чекбоксы серий
        defaults = {c: True for c in present}
        # небольшая сетка чекбоксов
        cols_grid = st.columns(min(len(present), 4))
        chosen = []
        for i, c in enumerate(present):
            with cols_grid[i % len(cols_grid)]:
                if st.checkbox(c, value=defaults[c], key=f"{group_name}:{c}"):
                    chosen.append(c)

        if not chosen:
            st.info("Ни одной серии не выбрано.")
            return

        df_plot = downsample_stride(df_time_indexed[chosen], MAX_POINTS_GROUP)
        layout_kwargs = dict(
            margin=dict(t=26, r=16, b=36, l=60),
            height=height,
            xaxis=dict(title="Время"),
            plot_bgcolor="#0b0f14",
            paper_bgcolor="#0b0f14",
            showlegend=True,
        )
        fig = go.Figure()

        if two_axes:
            # эвристика: Q_* на правую ось
            left_cols = [c for c in chosen if not c.startswith("Q")]
            right_cols = [c for c in chosen if c.startswith("Q")]
            if not left_cols:  # если вдруг выбирают только Q
                left_cols, right_cols = right_cols[:1], right_cols[1:]

            layout_kwargs["yaxis"] = dict(title=(left_cols[0] if left_cols else "A1"), gridcolor="#1a2430")
            layout_kwargs["yaxis2"] = dict(title=(right_cols[0] if right_cols else "A2"), overlaying="y", side="right")

            for c in left_cols:
                fig.add_trace(go.Scattergl(x=df_plot.index, y=df_plot[c], mode="lines", name=c, hovertemplate="%{x}<br>"+c+": %{y}<extra></extra>"))
            for c in right_cols:
                fig.add_trace(go.Scattergl(x=df_plot.index, y=df_plot[c], mode="lines", name=c, yaxis="y2",
                                           hovertemplate="%{x}<br>"+c+": %{y}<extra></extra>"))
        else:
            layout_kwargs["yaxis"] = dict(title=chosen[0], gridcolor="#1a2430")
            for c in chosen:
                fig.add_trace(go.Scattergl(x=df_plot.index, y=df_plot[c], mode="lines", name=c,
                                           hovertemplate="%{x}<br>"+c+": %{y}<extra></extra>"))

        fig.update_layout(**layout_kwargs)
        st.plotly_chart(fig, use_container_width=True, theme=None)


# ---------- UI ----------
st.set_page_config(page_title="Power Monitoring Viewer", layout="wide")
st.title("Просмотр графиков")

with st.sidebar:
    st.markdown("### 1) Загрузите CSV")
    uploaded = st.file_uploader("Файл CSV (1 час = 3600 строк)", type=["csv"])

    st.markdown("### 2) Настройки")
    main_height = st.slider("Высота верхнего графика, px", 700, 1200, 900, step=50)
    group_height = st.slider("Высота каждой панели внизу, px", 300, 700, 400, step=50)
    st.caption("Зум/панорамирование — колесо/drag, двойной клик — сброс, клик по легенде — скрыть серию.")

if not uploaded:
    st.info("Загрузите CSV в боковой панели.")
    st.stop()

# читаем и кэшируем по содержимому
content = uploaded.read()
df = _read_csv_cached(content)

# поиск столбца времени
time_col = detect_time_col(df)
if not time_col:
    st.error("Не нашёл столбец времени (timestamp). Добавьте его в CSV.")
    st.stop()

# готовим индекс времени
t = pd.to_datetime(df[time_col], errors="coerce", dayfirst=True)
df = df.loc[~t.isna()].copy()
df.index = t[~t.isna()]
df = df.sort_index()

# приводим остальные колонки к числам (кроме времени и скрываемых)
skip = [time_col] + list(HIDE_ALWAYS)
df = coerce_numeric(df, skip=skip)

# список доступных числовых колонок, исключая скрываемые
num_cols = [c for c in df.columns if c not in HIDE_ALWAYS and pd.api.types.is_numeric_dtype(df[c])]
if not num_cols:
    st.error("Не нашёл числовых колонок для графика.")
    st.stop()

# ---------- ВЕРХНИЙ ГРАФИК (свободный) ----------
st.subheader("Главный график (настраиваемые оси Y)")
left, right = st.columns([0.55, 0.45], vertical_alignment="top")

with left:
    # Предвыбор: если есть пресет — предложим его, иначе первые 3 колонки
    preselect = [c for c in DEFAULT_PRESET if c in num_cols] or num_cols[:3]
    selected = st.multiselect("Добавить серии", options=num_cols, default=preselect, key="main_select")

with right:
    st.write("Назначение осей Y для выбранных серий")
    axis_map: Dict[str, str] = {}
    # Стабильные ключи для виджетов
    for c in selected:
        # эвристика для старта: Q -> A2 (правая), остальное -> A1
        default_axis = "A2" if c.startswith("Q") else "A1"
        axis_map[c] = st.selectbox(
            f"{c}",
            options=list(AXIS_LABELS.keys()),
            index=["A1", "A2", "A3", "A4"].index(default_axis),
            format_func=lambda k: AXIS_LABELS[k],
            key=f"axis_{c}",
        )

plot_main(df, selected, axis_map, height=main_height)

with st.expander("Первые 50 строк таблицы (по запросу)"):
    st.dataframe(df.reset_index().rename(columns={"index": time_col}).head(50), use_container_width=True)

# ---------- НИЖЕ — ГРУППЫ СТЕКОМ ----------
st.subheader("Групповые графики (стеком)")

# Мощности — с двумя осями (Q на правую)
plot_group(df, "Мощности (общие)", GROUPS["Мощности (общие)"], height=group_height, two_axes=True)

# Остальные — с одной осью
for gname in ["Токи L1–L3", "Напряжения фазы", "Линейные U", "PF", "Углы"]:
    plot_group(df, gname, GROUPS[gname], height=group_height, two_axes=False)
