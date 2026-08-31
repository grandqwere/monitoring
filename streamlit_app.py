# streamlit_app.py
from __future__ import annotations
#
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
from core.stat_excel_export import build_statistical_workbook
from core.data_io import read_text_s3, read_bytes_s3, s3_measurement_period_all
from core.s3_paths import (
    build_root_key,
    build_all_key_for,
    build_ipeak_key_for,
    build_upeak_key_for,
)
from ui.date_format import format_datetime_ru
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
        "selected_date", "selected_day", "selected_day_confirmed",
        "__daily_cache", "__daily_active_day_key", "__daily_first_entry_done",
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

        # общий контекст переключения режимов
        "__mode_context_date", "__mode_context_hour",
        "__daily_selection_from_mode",

        # header
        "__measurement_period_all",

        # statistical
        "stat_cb_50", "stat_cb_90", "stat_cb_95", "stat_cb_99", "__stat_export",
    ]:
        if k in st.session_state:
            del st.session_state[k]


# Значение password_to_prefix может содержать один или несколько префиксов через ";".
def _parse_auth_prefixes(raw_value) -> list[str]:
    prefixes: list[str] = []
    seen: set[str] = set()
    for part in str(raw_value or "").split(";"):
        prefix = part.strip()
        if not prefix:
            continue
        normalized = prefix.rstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        prefixes.append(prefix)
    return prefixes


def _prefix_title(prefix: str) -> str:
    """Первая строка description.txt; при отсутствии — имя папки объекта."""
    clean = str(prefix or "").strip().rstrip("/")
    if not clean:
        return "Объект"
    try:
        txt = read_text_s3(f"{clean}/description.txt")
        if txt:
            first = txt.splitlines()[0].strip()
            if first:
                return first
    except Exception:
        pass
    return clean.rsplit("/", 1)[-1] or clean


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
        raw_value = mapping.get(pwd_raw) or mapping.get(pwd_fixed) or mapping.get(pwd_fixed_rev) or ""
        prefixes = _parse_auth_prefixes(raw_value)
        if prefixes:
            st.session_state.pop("auth_error", None)
            st.session_state["auth_ok"] = True
            st.session_state["auth_mode"] = "password"
            st.session_state["auth_prefixes"] = prefixes
            st.session_state["current_prefix"] = prefixes[0] if len(prefixes) == 1 else ""
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
        st.session_state["auth_prefixes"] = [demo_prefix]
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


# Для пароля с несколькими объектами сначала показываем выбор объекта.
if not st.session_state.get("current_prefix"):
    auth_prefixes = list(st.session_state.get("auth_prefixes") or [])
    if len(auth_prefixes) == 1:
        st.session_state["current_prefix"] = auth_prefixes[0]
    elif len(auth_prefixes) > 1:
        object_titles = [_prefix_title(prefix) for prefix in auth_prefixes]
        longest = max([len(title) for title in object_titles] + [len("Выйти")])
        button_width_px = min(max(longest * 10 + 48, 220), 1000)

        st.markdown("#### Выберите объект")

        def _select_object(prefix: str) -> None:
            st.session_state["current_prefix"] = prefix
            _clear_all_caches()

        with st.container(horizontal_alignment="left"):
            for idx, (prefix, title) in enumerate(zip(auth_prefixes, object_titles)):
                st.button(
                    title,
                    key=f"auth_object_{idx}",
                    on_click=_select_object,
                    args=(prefix,),
                    width=button_width_px,
                )

            if st.button("Выйти", key="auth_objects_logout", width=button_width_px):
                st.session_state.clear()
                st.rerun()
        st.stop()
    else:
        # Защита от неконсистентного состояния сессии после изменения конфигурации.
        st.session_state.clear()
        st.rerun()


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


def _is_demo_mode() -> bool:
    """Определяем демо-режим: auth_mode == 'demo' или текущий префикс совпадает с auth.demo_prefix."""
    try:
        if st.session_state.get("auth_mode") == "demo":
            return True
        demo_pref = str(st.secrets.get("auth", {}).get("demo_prefix", "")).strip().rstrip("/")
        curr_pref = str(st.session_state.get("current_prefix", "")).strip().rstrip("/")
        return bool(demo_pref and curr_pref and curr_pref == demo_pref)
    except Exception:
        return False


def _measurement_period_value() -> str:
    """Возвращает значение периода измерений без подписи поля."""
    if _is_demo_mode():
        return ""

    period = s3_measurement_period_all()
    if not period:
        return ""

    start = format_datetime_ru(period.get("start"))
    end = format_datetime_ru(period.get("end"))
    if not start or not end:
        return ""
    return f"с {start} по {end}"


def _measurement_period_text() -> str:
    """Возвращает строку периода измерений для заголовка страницы."""
    value = _measurement_period_value()
    return f"Период измерений: {value}" if value else ""


def _day_folder(d) -> str:
    return f"{d.year:04d}.{d.month:02d}.{d.day:02d}"


def _render_all_filename_for_zip(d, hour: int) -> str:
    """Имя часового файла (All-...) для архива. В демо — по отображаемой дате, без маппинга."""
    try:
        tpl = str(st.secrets.get("s3", {}).get("key_template", "")).strip()
    except Exception:
        tpl = ""
    if not tpl:
        tpl = "All-{YYYY}.{MM}.{DD}-{HH}.00.csv"
    return (
        tpl.replace("{YYYY}", f"{d.year:04d}")
           .replace("{MM}", f"{d.month:02d}")
           .replace("{DD}", f"{d.day:02d}")
           .replace("{HH}", f"{hour:02d}")
           .replace("{mm}", "00")
    )


def _all_arcname_for_zip(d, hour: int) -> str:
    df = _day_folder(d)
    fname = _render_all_filename_for_zip(d, hour)
    return f"All/{df}/{fname}"


def _peak_arcname_for_zip(kind: str, d, hour: int, minute: int) -> str:
    df = _day_folder(d)
    fname = f"{kind}-{df}-{hour:02d}.{minute:02d}.csv"
    return f"{kind}/{df}/{fname}"


def _download_keys_and_name() -> tuple[list[tuple[str, str | None]], str]:
    mode = st.session_state.get("mode") or "daily"
    demo = _is_demo_mode()

    if mode == "statistical":
        keys = [
            build_root_key("Stat/weekday.csv"),
            build_root_key("Stat/weekend.csv"),
        ]
        items = [(k, None) for k in keys]
        return items, "statistical.zip"

    if mode == "daily":
        day = st.session_state.get("selected_day")
        if not day:
            return [], ""
        daily_cache = st.session_state.get("__daily_cache") or {}
        day_key = day.strftime("%Y%m%d")
        entry = daily_cache.get(day_key) or {}
        hours = sorted(list(entry.get("hours_present") or []))
        keys = [build_all_key_for(day, int(h)) for h in hours]
        if demo:
            items = [(k, _all_arcname_for_zip(day, int(h))) for k, h in zip(keys, hours)]
        else:
            items = [(k, None) for k in keys]
        return items, f"daily_{day.isoformat()}.zip"

    if mode == "hourly":
        loaded = st.session_state.get("loaded_hours") or []
        if not loaded:
            return [], ""
        keys = [build_all_key_for(d, int(h)) for d, h in loaded]
        if demo:
            items = [(k, _all_arcname_for_zip(d, int(h))) for (d, h), k in zip(loaded, keys)]
        else:
            items = [(k, None) for k in keys]

        if len(loaded) == 1:
            d, h = loaded[0]
            return items, f"hourly_{d.isoformat()}_{int(h):02d}.zip"
        (d1, h1), (d2, h2) = loaded[0], loaded[1]
        return items, f"hourly_{d1.isoformat()}_{int(h1):02d}__{d2.isoformat()}_{int(h2):02d}.zip"

    if mode == "minutely":
        loaded = st.session_state.get("loaded_minutes") or []
        if not loaded:
            return [], ""
        items: list[tuple[str, str | None]] = []
        for d, h, m in loaded:
            k_i = build_ipeak_key_for(d, int(h), int(m))
            k_u = build_upeak_key_for(d, int(h), int(m))
            if demo:
                items.append((k_i, _peak_arcname_for_zip("Ipeak", d, int(h), int(m))))
                items.append((k_u, _peak_arcname_for_zip("Upeak", d, int(h), int(m))))
            else:
                items.append((k_i, None))
                items.append((k_u, None))

        if len(loaded) == 1:
            d, h, m = loaded[0]
            return items, f"minutely_{d.isoformat()}_{int(h):02d}.{int(m):02d}.zip"
        (d1, h1, m1), (d2, h2, m2) = loaded[0], loaded[1]
        return items, f"minutely_{d1.isoformat()}_{int(h1):02d}.{int(m1):02d}__{d2.isoformat()}_{int(h2):02d}.{int(m2):02d}.zip"

    return [], ""


def _build_zip_from_keys(items: list[tuple[str, str | None]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for key, arcname_override in items:
            data = read_bytes_s3(key)
            if not data:
                continue
            arcname = arcname_override or _strip_current_prefix(key)
            if not arcname:
                continue
            zf.writestr(arcname, data)
    return buf.getvalue()


@st.cache_data(show_spinner=False)
def _build_statistical_xlsx_cached(
    weekday_csv: str,
    weekend_csv: str,
    object_title: str,
    measurement_period: str,
    power_mode: str,
    shift_power: int,
    thresholds: tuple[tuple[bool, int], ...],
    show_median: bool,
    show_50: bool,
    show_90: bool,
    show_99: bool,
    show_max: bool,
    y_axis_min: float,
    y_axis_max: float,
) -> bytes:
    return build_statistical_workbook(
        weekday_csv=weekday_csv,
        weekend_csv=weekend_csv,
        object_title=object_title,
        measurement_period=measurement_period,
        power_mode=power_mode,
        shift_power=shift_power,
        thresholds=thresholds,
        show_median=show_median,
        show_50=show_50,
        show_90=show_90,
        show_99=show_99,
        show_max=show_max,
        y_axis_min=y_axis_min,
        y_axis_max=y_axis_max,
    )



st.markdown(f"<h3 style='margin:0'>{_current_title()}</h3>", unsafe_allow_html=True)
measurement_period = _measurement_period_text()
if measurement_period:
    st.markdown(
        f"<div style='font-size:0.86rem; line-height:1.25; margin:0.05rem 0 0.35rem 0; opacity:0.72;'>{measurement_period}</div>",
        unsafe_allow_html=True,
    )

# Кнопка «Выйти» (без строки «Источник данных»)
right = st.columns([0.8, 0.2])[1]
with right:
    if st.button("Выйти", use_container_width=True):
        auth_prefixes = list(st.session_state.get("auth_prefixes") or [])
        if st.session_state.get("auth_mode") == "password" and len(auth_prefixes) > 1:
            _clear_all_caches()
            st.session_state["current_prefix"] = ""
        else:
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

previous_mode = st.session_state["mode"]

if chosen == "Минутные":
    target_mode = "minutely"
elif chosen == "Часовые":
    target_mode = "hourly"
elif chosen == "Статистические":
    target_mode = "statistical"
else:
    target_mode = "daily"

if target_mode != previous_mode:
    state.synchronize_mode_selection(previous_mode, target_mode)
st.session_state["mode"] = target_mode

# Роутинг по режимам
if st.session_state["mode"] == "minutely":
    render_minutely_mode()
elif st.session_state["mode"] == "daily":
    render_daily_mode()
elif st.session_state["mode"] == "statistical":
    render_statistical_mode()
else:
    render_hourly_mode()


# Кнопка скачивания — справа от переключателя режимов, под кнопкой «Выйти».
# Для статистики отдаём заполненный Excel-шаблон; остальные режимы по-прежнему отдают ZIP.
if st.session_state["mode"] == "statistical":
    export_state = st.session_state.get("__stat_export") or {}
    weekday_csv = read_text_s3(build_root_key("Stat/weekday.csv"))
    weekend_csv = read_text_s3(build_root_key("Stat/weekend.csv"))
    if export_state and (weekday_csv or weekend_csv):
        # Снимок значений делаем в основном потоке. Сам Excel собирается callable-функцией
        # только по клику на download_button (Streamlit >= 1.57).
        object_title = _current_title()
        measurement_period = _measurement_period_value()
        power_mode = str(export_state.get("power_mode") or "")
        shift_power = int(export_state.get("shift_power") or 0)
        thresholds = tuple(export_state.get("thresholds") or ())
        show_median = bool(export_state.get("show_median"))
        show_50 = bool(export_state.get("show_50"))
        show_90 = bool(export_state.get("show_90"))
        show_99 = bool(export_state.get("show_99"))
        show_max = bool(export_state.get("show_max"))
        y_axis_min = float(export_state.get("y_axis_min") or 0.0)
        y_axis_max = float(export_state.get("y_axis_max") or 1.0)

        def _make_statistical_download() -> bytes:
            return _build_statistical_xlsx_cached(
                weekday_csv,
                weekend_csv,
                object_title,
                measurement_period,
                power_mode,
                shift_power,
                thresholds,
                show_median,
                show_50,
                show_90,
                show_99,
                show_max,
                y_axis_min,
                y_axis_max,
            )

        download_ph.download_button(
            "Скачать графики",
            data=_make_statistical_download,
            file_name="Потребление электроэнергии.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="statistical_xlsx_download",
            on_click="ignore",
            use_container_width=True,
        )
    else:
        download_ph.empty()
else:
    items, zip_name = _download_keys_and_name()
    if items:
        zip_bytes = _build_zip_from_keys(items)
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
