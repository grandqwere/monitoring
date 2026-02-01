from __future__ import annotations
import streamlit as st

from core import state
from views.daily import render_daily_mode
from views.hourly import render_hourly_mode
from views.statistical import render_statistical_mode
from core.hour_loader import init_hour_state
from core.data_io import read_text_s3
from core.s3_paths import build_root_key

st.set_page_config(page_title="Мониторинг электрических параметров", layout="wide")
state.init_once()
init_hour_state() 

# (Заголовок теперь рисуем ПОСЛЕ входа — из description.txt)

# -------------------- ПРОСТОЙ ДОСТУП: пароль / демо --------------------
# Секреты: [auth].demo_prefix и [auth].password_to_prefix (см. Secrets в Streamlit Cloud)
def _clear_all_caches():
    """Полный сброс данных/кэшей при смене источника (папки) или выхода."""
    for k in [
        "loaded_hours", "hour_cache", "current_date", "current_hour",
        "selected_date", "selected_day_confirmed",
        "__daily_cache", "__daily_active_day_key",
        "refresh_daily_all", "refresh_hourly_all",
    ]:
        if k in st.session_state:
            del st.session_state[k]

# Если пользователь ещё не авторизован — показываем форму входа / демо
if not st.session_state.get("auth_ok", False):
    st.markdown("#### Доступ")
    # Форма логина (Enter отправляет форму)
    with st.form("auth_form", clear_on_submit=False):
        pwd = st.text_input(
            "Код доступа",
            type="password",
            key="auth_pwd",
            placeholder="Введите код доступа",
        )
        btn_login = st.form_submit_button("Войти", use_container_width=True)
    # Кнопка «Демо-режим» — отдельным блоком ПОД формой
    btn_demo = st.button("Демо-режим", use_container_width=True)

    auth_conf = dict(st.secrets.get("auth", {}))
    mapping = dict(auth_conf.get("password_to_prefix", {}))
    demo_prefix = (auth_conf.get("demo_prefix") or "").strip()

    if btn_login:
        prefix = (mapping.get(pwd) or "").strip()
        if prefix:
            st.session_state["auth_ok"] = True
            st.session_state["auth_mode"] = "password"
            st.session_state["current_prefix"] = prefix
            _clear_all_caches()
            st.rerun()
        else:
            st.error("Неверный пароль. Проверьте и попробуйте ещё раз.")
            st.stop()

    if btn_demo:
        if not demo_prefix:
            st.error("Демо-папка не настроена в Secrets (auth.demo_prefix).")
            st.stop()
        st.session_state["auth_ok"] = True
        st.session_state["auth_mode"] = "demo"
        st.session_state["current_prefix"] = demo_prefix
        _clear_all_caches()
        st.rerun()

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
    if st.session_state["mode"] == "daily":
        st.session_state["mode_segmented"] = "Суточные"
    elif st.session_state["mode"] == "hourly":
        st.session_state["mode_segmented"] = "Часовые"
    else:
        st.session_state["mode_segmented"] = "Статистические"

# Горизонтальный переключатель «Вид графиков»
label = "Вид графиков"
options = ["Часовые", "Суточные", "Статистические"]
try:
    chosen = st.segmented_control(
        label,
        options=options,
        key="mode_segmented",
    )
except Exception:
    # Фолбэк для старых версий Streamlit
    fallback_index = 1 if st.session_state["mode"] == "daily" else 2 if st.session_state["mode"] == "statistical" else 0
    chosen = st.radio(
        label,
        options=options,
        horizontal=True,
        index=fallback_index,
        key="mode_segmented",
    )

if chosen == "Суточные":
    st.session_state["mode"] = "daily"
elif chosen == "Статистические":
    st.session_state["mode"] = "statistical"
else:
    st.session_state["mode"] = "hourly"

# Роутинг по режимам
if st.session_state["mode"] == "daily":
    render_daily_mode()
elif st.session_state["mode"] == "statistical":
    render_statistical_mode()
else:
    render_hourly_mode()
