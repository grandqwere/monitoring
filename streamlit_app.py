# streamlit_app.py
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Мониторинг электрических параметров", layout="wide")

# Импорты проекта — ТОЛЬКО после set_page_config
from core import state
from views.daily import render_daily_mode
from views.hourly import render_hourly_mode
from views.minutely import render_minutely_mode  # NEW
from core.hour_loader import init_hour_state
from core.minute_loader import init_minute_state  # NEW
from core.data_io import read_text_s3
from core.s3_paths import build_root_key
state.init_once()
init_hour_state()
init_minute_state()  # NEW

# -------------------- Автоисправление раскладки пароля RU -> EN --------------------
_RU_TO_EN = str.maketrans({
    "ё": "`", "Ё": "~",
    "й": "q", "Й": "Q",
    "ц": "w", "Ц": "W",
    "у": "e", "У": "E",
    "к": "r", "К": "R",
    "е": "t", "Е": "T",
    "н": "y", "Н": "Y",
    "г": "u", "Г": "U",
    "ш": "i", "Ш": "I",
    "щ": "o", "Щ": "O",
    "з": "p", "З": "P",
    "х": "[", "Х": "{",
    "ъ": "]", "Ъ": "}",
    "ф": "a", "Ф": "A",
    "ы": "s", "Ы": "S",
    "в": "d", "В": "D",
    "а": "f", "А": "F",
    "п": "g", "П": "G",
    "р": "h", "Р": "H",
    "о": "j", "О": "J",
    "л": "k", "Л": "K",
    "д": "l", "Д": "L",
    "ж": ";", "Ж": ":",
    "э": "'", "Э": "\"",
    "я": "z", "Я": "Z",
    "ч": "x", "Ч": "X",
    "с": "c", "С": "C",
    "м": "v", "М": "V",
    "и": "b", "И": "B",
    "т": "n", "Т": "N",
    "ь": "m", "Ь": "M",
    "б": ",", "Б": "<",
    "ю": ".", "Ю": ">",
})

def _fix_layout_ru_to_en(s: str) -> str:
    """Если пароль набран в RU раскладке, преобразуем в EN по клавиатурному соответствию."""
    if not s:
        return s
    return s.translate(_RU_TO_EN)

# (Заголовок теперь рисуем ПОСЛЕ входа — из description.txt)

# -------------------- ПРОСТОЙ ДОСТУП: пароль / демо --------------------
# Секреты: [auth].demo_prefix и [auth].password_to_prefix (см. Secrets в Streamlit Cloud)
def _clear_all_caches():
    """Полный сброс данных/кэшей при смене источника (папки) или выхода."""
    for k in [
        # hourly
        "loaded_hours", "hour_cache", "current_date", "current_hour",
        "selected_date", "selected_day_confirmed",
        "__daily_cache", "__daily_active_day_key",
        "refresh_daily_all", "refresh_hourly_all",
        "__pending_date", "__pending_hour",
        "__picker_redraw",
        # minutely (NEW)
        "loaded_minutes", "minute_cache",
        "current_minute_date", "current_minute_hour", "current_minute_minute",
        "selected_minute_date", "selected_minute_hour",
        "__pending_minute_date", "__pending_minute_hour", "__pending_minute_minute",
        "__minute_picker_redraw",
        "refresh_minutely_all",
    ]:
        if k in st.session_state:
            del st.session_state[k]


# Если пользователь ещё не авторизован — показываем форму входа / демо
if not st.session_state.get("auth_ok", False):
    st.markdown("#### Доступ")

    auth_conf = dict(st.secrets.get("auth", {}))
    mapping = dict(auth_conf.get("password_to_prefix", {}))
    demo_prefix = (auth_conf.get("demo_prefix") or "").strip()

    def _do_login() -> None:
        pwd_raw = (st.session_state.get("auth_pwd") or "").strip()
        pwd_fixed = _fix_layout_ru_to_en(pwd_raw)
        prefix = (mapping.get(pwd_raw) or mapping.get(pwd_fixed) or "").strip()
        if prefix:
            st.session_state.pop("auth_error", None)
            st.session_state["auth_ok"] = True
            st.session_state["auth_mode"] = "password"
            st.session_state["current_prefix"] = prefix
            _clear_all_caches()
        else:
            st.session_state["auth_error"] = "Неверный пароль. Проверьте и попробуйте ещё раз."

    def _do_demo() -> None:
        if not demo_prefix:
            st.session_state["auth_error"] = "Демо-папка не настроена в Secrets (auth.demo_prefix)."
            return
        st.session_state.pop("auth_error", None)
        st.session_state["auth_ok"] = True
        st.session_state["auth_mode"] = "demo"
        st.session_state["current_prefix"] = demo_prefix
        _clear_all_caches()

    # Enter в поле → on_change вызывает логин
    st.text_input(
        "Код доступа",
        type="password",
        key="auth_pwd",
        placeholder="Введите код доступа",
        on_change=_do_login,
    )
    st.button("Войти", use_container_width=True, on_click=_do_login, key="btn_login")
    st.button("Демо-режим", use_container_width=True, on_click=_do_demo, key="btn_demo")

    if st.session_state.get("auth_error"):
        st.error(st.session_state["auth_error"])

    # Пока не вошёл — дальше приложение не рисуем
    st.stop()


# Заголовок страницы: первая строка из <current_prefix>/description.txt
def _current_title() -> str:
    default = "Мониторинг электрических параметров"
    try:
        key = build_root_key("description.txt")
        txt = read_text_s3(key)
        if txt:
            first = txt.splitlines()[0].strip()
            if first:
                return first
    except Exception:
        pass
    return default


st.markdown(f"<h3 style='margin:0'>{_current_title()}</h3>", unsafe_allow_html=True)

# Кнопка «Выйти» (без строки «Источник данных»)
right = st.columns([0.8, 0.2])[1]
with right:
    if st.button("Выйти", use_container_width=True):
        st.session_state.clear()
        st.rerun()


# Инициализация режима: по умолчанию — суточный
if "mode" not in st.session_state:
    st.session_state["mode"] = "daily"

# Предвыбор активной кнопки в переключателе
if "mode_segmented" not in st.session_state:
    if st.session_state["mode"] == "minutely":
        st.session_state["mode_segmented"] = "Минутные"
    elif st.session_state["mode"] == "hourly":
        st.session_state["mode_segmented"] = "Часовые"
    else:
        st.session_state["mode_segmented"] = "Суточные"

# Горизонтальный переключатель «Вид графиков»
label = "Вид графиков"
options = ["Минутные", "Часовые", "Суточные"]

try:
    chosen = st.segmented_control(
        label,
        options=options,
        key="mode_segmented",
    )
except Exception:
    # Фолбэк для старых версий Streamlit
    idx = 2  # daily
    if st.session_state["mode"] == "minutely":
        idx = 0
    elif st.session_state["mode"] == "hourly":
        idx = 1
    chosen = st.radio(
        label,
        options=options,
        horizontal=True,
        index=idx,
        key="mode_segmented",
    )

if chosen == "Минутные":
    st.session_state["mode"] = "minutely"
elif chosen == "Суточные":
    st.session_state["mode"] = "daily"
else:
    st.session_state["mode"] = "hourly"

# Роутинг по режимам
if st.session_state["mode"] == "minutely":
    render_minutely_mode()
elif st.session_state["mode"] == "daily":
    render_daily_mode()
else:
    render_hourly_mode()
