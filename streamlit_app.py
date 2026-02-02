# streamlit_app.py
from __future__ import annotations

import io
import zipfile
import streamlit as st

st.set_page_config(page_title="Мониторинг электрических параметров", layout="wide")

# Импорты проекта — ТОЛЬКО после set_page_config
from core import state
from views.daily import render_daily_mode
from views.hourly import render_hourly_mode
from views.minutely import render_minutely_mode  # NEW
from views.statistical import render_statistical_mode  # NEW
from core.hour_loader import init_hour_state
from core.minute_loader import init_minute_state  # NEW
from core.data_io import read_text_s3, read_bytes_s3
from core.s3_paths import (
    build_root_key,
    build_all_key_for,
    build_ipeak_key_for,
    build_upeak_key_for,
)
state.init_once()
init_hour_state()
init_minute_state()  # NEW

# -------------------- Автоисправление раскладки пароля RU <-> EN ---------------------
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

_EN_TO_RU = str.maketrans({v: chr(k) for k, v in _RU_TO_EN.items()})

def _fix_layout_ru_to_en(s: str) -> str:
    """Если пароль набран в RU раскладке, преобразуем в EN по клавиатурному соответствию."""
    if not s:
        return s
    return s.translate(_RU_TO_EN)

def _fix_layout_en_to_ru(s: str) -> str:
    """Если пароль набран в EN раскладке, преобразуем в RU по клавиатурному соответствию."""
    if not s:
        return s
    return s.translate(_EN_TO_RU)

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

        # statistical
        "stat_cb_50", "stat_cb_90", "stat_cb_95", "stat_cb_99",
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
        pwd_fixed_rev = _fix_layout_en_to_ru(pwd_raw)
        prefix = (mapping.get(pwd_raw) or mapping.get(pwd_fixed) or mapping.get(pwd_fixed_rev) or "").strip()
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


def _strip_current_prefix(key: str) -> str:
    curr = str(st.session_state.get("current_prefix", "") or "").strip().rstrip("/")
    if curr and key.startswith(curr + "/"):
        return key[len(curr) + 1 :]
    return key.lstrip("/")


def _download_keys_and_name() -> tuple[list[str], str]:
    mode = st.session_state.get("mode") or "daily"

    if mode == "statistical":
        keys = [
            build_root_key("Stat/weekday.csv"),
            build_root_key("Stat/weekend.csv"),
        ]
        return keys, "statistical.zip"

    if mode == "daily":
        day = st.session_state.get("selected_day")
        if not day:
            return [], ""
        daily_cache = st.session_state.get("__daily_cache") or {}
        day_key = day.strftime("%Y%m%d")
        entry = daily_cache.get(day_key) or {}
        hours = sorted(list(entry.get("hours_present") or []))
        keys = [build_all_key_for(day, int(h)) for h in hours]
        return keys, f"daily_{day.isoformat()}.zip"

    if mode == "hourly":
        loaded = st.session_state.get("loaded_hours") or []
        if not loaded:
            return [], ""
        keys = [build_all_key_for(d, int(h)) for d, h in loaded]
        if len(loaded) == 1:
            d, h = loaded[0]
            return keys, f"hourly_{d.isoformat()}_{int(h):02d}.zip"
        (d1, h1), (d2, h2) = loaded[0], loaded[1]
        return keys, f"hourly_{d1.isoformat()}_{int(h1):02d}__{d2.isoformat()}_{int(h2):02d}.zip"

    if mode == "minutely":
        loaded = st.session_state.get("loaded_minutes") or []
        if not loaded:
            return [], ""
        keys: list[str] = []
        for d, h, m in loaded:
            keys.append(build_ipeak_key_for(d, int(h), int(m)))
            keys.append(build_upeak_key_for(d, int(h), int(m)))
        if len(loaded) == 1:
            d, h, m = loaded[0]
            return keys, f"minutely_{d.isoformat()}_{int(h):02d}.{int(m):02d}.zip"
        (d1, h1, m1), (d2, h2, m2) = loaded[0], loaded[1]
        return keys, f"minutely_{d1.isoformat()}_{int(h1):02d}.{int(m1):02d}__{d2.isoformat()}_{int(h2):02d}.{int(m2):02d}.zip"

    return [], ""


def _build_zip_from_keys(keys: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for key in keys:
            data = read_bytes_s3(key)
            if not data:
                continue
            arcname = _strip_current_prefix(key)
            if not arcname:
                continue
            zf.writestr(arcname, data)
    return buf.getvalue()



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
    elif st.session_state["mode"] == "statistical":
        st.session_state["mode_segmented"] = "Статистические"
    else:
        st.session_state["mode_segmented"] = "Суточные"

# Горизонтальный переключатель «Вид графиков» + кнопка «Скачать данные»
label = "Вид графиков"
options = ["Минутные", "Часовые", "Суточные", "Статистические"]

nav_left, nav_right = st.columns([0.8, 0.2])

with nav_left:
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
        elif st.session_state["mode"] == "statistical":
            idx = 3
        chosen = st.radio(
            label,
            options=options,
            horizontal=True,
            index=idx,
            key="mode_segmented",
        )

with nav_right:
    download_ph = st.empty()

if chosen == "Минутные":
    st.session_state["mode"] = "minutely"
elif chosen == "Часовые":
    st.session_state["mode"] = "hourly"
elif chosen == "Статистические":
    st.session_state["mode"] = "statistical"
else:
    st.session_state["mode"] = "daily"

# Роутинг по режимам
if st.session_state["mode"] == "minutely":
    render_minutely_mode()
elif st.session_state["mode"] == "daily":
    render_daily_mode()
elif st.session_state["mode"] == "statistical":
    render_statistical_mode()
else:
    render_hourly_mode()


# Кнопка «Скачать данные» (ZIP) — справа от переключателя режимов, под кнопкой «Выйти»
keys, zip_name = _download_keys_and_name()
if keys:
    zip_bytes = _build_zip_from_keys(keys)
    if zip_bytes:
        download_ph.download_button(
            "Скачать данные (ZIP)",
            data=zip_bytes,
            file_name=zip_name or "data.zip",
            mime="application/zip",
            use_container_width=True,
        )
else:
    download_ph.empty()
