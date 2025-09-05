from __future__ import annotations
import streamlit as st

from core import state
from views.daily import render_daily_mode
from views.hourly import render_hourly_mode
from core.hour_loader import init_hour_state

st.set_page_config(page_title="Мониторинг электрических параметров", layout="wide")
state.init_once()
init_hour_state() 

# Заголовок страницы (уменьшенный)
st.markdown("<h3 style='margin:0'>Мониторинг электрических параметров</h3>", unsafe_allow_html=True)

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
    pwd = st.text_input("Пароль", type="password", key="auth_pwd", placeholder="Введите пароль")
    c1, c2 = st.columns(2)
    with c1:
        btn_login = st.button("Войти", use_container_width=True)
    with c2:
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

# Кнопка «Выйти» (сбросить доступ) и бейдж текущей папки
with st.container():
    left, right = st.columns([0.7, 0.3])
    with left:
        st.caption(f"Источник данных: `{st.session_state.get('current_prefix', '—')}`")
    with right:
        if st.button("Выйти", use_container_width=True):
            st.session_state.clear()
            st.rerun()

# Инициализация режима: по умолчанию — суточный
if "mode" not in st.session_state:
    st.session_state["mode"] = "daily"

# Предвыбор активной кнопки в переключателе
if "mode_segmented" not in st.session_state:
    st.session_state["mode_segmented"] = "Суточные" if st.session_state["mode"] == "daily" else "Часовые"

# Горизонтальный переключатель «Вид графиков»
label = "Вид графиков"
options = ["Часовые", "Суточные"]
try:
    chosen = st.segmented_control(
        label,
        options=options,
        key="mode_segmented",
    )
except Exception:
    # Фолбэк для старых версий Streamlit
    chosen = st.radio(
        label,
        options=options,
        horizontal=True,
        index=(1 if st.session_state["mode"] == "daily" else 0),
        key="mode_segmented",
    )

st.session_state["mode"] = "daily" if chosen == "Суточные" else "hourly"

# Роутинг по режимам
if st.session_state["mode"] == "daily":
    render_daily_mode()
else:
    render_hourly_mode()
