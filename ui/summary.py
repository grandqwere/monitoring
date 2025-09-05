from __future__ import annotations
from typing import List
import streamlit as st

def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]

def render_summary_controls(
    num_cols: List[str],
    default_main: List[str],
    key_prefix: str = "",
    strict: bool = False,
) -> tuple[list[str], set[str]]:
    """
    Выбор полей и нормирование шкал для сводного графика.

    - key_prefix: уникальный префикс для ключей виджетов (избегаем конфликтов состояний).
    - strict=False (по умолчанию): старое «мягкое» поведение — как в часовом режиме (с disabled).
    - strict=True: «строгое» поведение — без disabled; если выбрали больше допустимого, мы
      пост-фактум снимаем лишние галочки (кроме последней изменённой) и делаем st.rerun().
      Это устраняет инверсию галочек, наблюдавшуюся в суточном режиме.
    """
    main_key = f"{key_prefix}main_fields"

    # Заголовок как у блока ниже — жирным
    st.markdown("Поля сводного графика:")
    selected_main = st.multiselect(
        "Поля сводного графика",
        options=num_cols,
        default=default_main,
        key=main_key,
        label_visibility="collapsed",
    )

    st.markdown("Добавить отдельную шкалу для выбранных трендов:")

    norm_prefix = f"{key_prefix}norm_"
    # очистка устаревших ключей только нашего префикса
    for k in list(st.session_state.keys()):
        if k.startswith(norm_prefix):
            col = k[len(norm_prefix):]
            if col not in selected_main:
                del st.session_state[k]

    allowed = max(0, len(selected_main) - 1)

    if not strict:
        # ==== МЯГКИЙ РЕЖИМ (как в часовом): используем disabled, ограничиваем выбор ====
        flags = {c: bool(st.session_state.get(f"{norm_prefix}{c}", False)) for c in selected_main}

        for row in chunk(selected_main, 6):
            cols = st.columns(len(row))
            for i, c in enumerate(row):
                checked_others = sum(flags[x] for x in selected_main if x != c)
                disable_this = (checked_others >= allowed) and (not flags[c])
                with cols[i]:
                    val = st.checkbox(c, value=flags[c], key=f"{norm_prefix}{c}", disabled=disable_this)
                    flags[c] = bool(val)

        # финальная нормализация (на случай «дрожи» состояний)
        checked = [c for c, v in flags.items() if v]
        if len(checked) > allowed:
            to_keep = set([c for c in selected_main if c in checked][:allowed])
            for c in checked:
                if c not in to_keep:
                    st.session_state[f"{norm_prefix}{c}"] = False
                    flags[c] = False

        separate_set = {c for c, v in flags.items() if v}
        return selected_main, separate_set

    # ==== СТРОГИЙ РЕЖИМ (для суточного): без disabled, с пост-коррекцией ====
    # Снимем «старые» флаги, чтобы понять, что изменилось.
    prev_checked = {c for c in selected_main if bool(st.session_state.get(f"{norm_prefix}{c}", False))}

    # Рисуем чекбоксы без отключения — пользователю они не «переворачиваются»
    for row in chunk(selected_main, 6):
        cols = st.columns(len(row))
        for i, c in enumerate(row):
            with cols[i]:
                st.checkbox(c, value=bool(st.session_state.get(f"{norm_prefix}{c}", False)), key=f"{norm_prefix}{c}")

    # Собираем новый набор после ввода
    new_checked = {c for c in selected_main if bool(st.session_state.get(f"{norm_prefix}{c}", False))}

    if len(new_checked) > allowed:
        # Определим, что именно изменили: добавленные галочки
        added = list(new_checked - prev_checked)

        # Кого сохраняем: сначала новодобавленные (в порядке появления), затем прежние
        to_keep_list = []
        for c in added:
            if len(to_keep_list) < allowed:
                to_keep_list.append(c)
        for c in prev_checked:
            if len(to_keep_list) < allowed and c not in to_keep_list:
                to_keep_list.append(c)

        to_keep = set(to_keep_list)

        # Снимем лишние галки и перезапустим отрисовку, чтобы пользователь увидел честное состояние
        for c in (new_checked - to_keep):
            st.session_state[f"{norm_prefix}{c}"] = False

        st.rerun()

    separate_set = new_checked
    return selected_main, separate_set
