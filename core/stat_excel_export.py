from __future__ import annotations

import copy
import csv
import io
import re
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence
from xml.etree import ElementTree as ET


_TEMPLATE_NAME = "stat_template.xlsx"
_EXPECTED_HEADERS = [
    "time",
    "P0.5",
    "P2.5",
    "P5",
    "P25",
    "P50",
    "P75",
    "P95",
    "P97.5",
    "P99.5",
    "Pmax",
    "Pmax_datetime",
    "S0.5",
    "S2.5",
    "S5",
    "S25",
    "S50",
    "S75",
    "S95",
    "S97.5",
    "S99.5",
    "Smax",
    "Smax_datetime",
]
_MAX_DATA_ROWS = 288

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_C16_NS = "http://schemas.microsoft.com/office/drawing/2014/chart"
_C16R2_NS = "http://schemas.microsoft.com/office/drawing/2015/06/chart"
_IGNORABLE_NAMESPACES = {
    "x14ac": "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac",
    "xr": "http://schemas.microsoft.com/office/spreadsheetml/2014/revision",
    "xr2": "http://schemas.microsoft.com/office/spreadsheetml/2015/revision2",
    "xr3": "http://schemas.microsoft.com/office/spreadsheetml/2016/revision3",
}
ET.register_namespace("", _NS)
ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
ET.register_namespace("mc", "http://schemas.openxmlformats.org/markup-compatibility/2006")
ET.register_namespace("x14ac", "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac")
ET.register_namespace("xr", "http://schemas.microsoft.com/office/spreadsheetml/2014/revision")
ET.register_namespace("xr2", "http://schemas.microsoft.com/office/spreadsheetml/2015/revision2")
ET.register_namespace("xr3", "http://schemas.microsoft.com/office/spreadsheetml/2016/revision3")
ET.register_namespace("c", _C_NS)
ET.register_namespace("a", _A_NS)
ET.register_namespace("c16", _C16_NS)
ET.register_namespace("c16r2", _C16R2_NS)


_PROTECTION_PASSWORD = "Monitoring1399"
_EDITABLE_STAT_CELLS = {
    # Режим мощности. C4:F4 — одна объединённая видимая ячейка.
    "C4", "D4", "E4", "F4",
    # Увеличение мощности.
    "J4",
    # Значения порогов и их Вкл/Выкл.
    "B6", "C6", "E6", "F6", "H6", "I6", "K6", "L6", "M6", "O6",
    # Медиана / 50 / 90 / 99 / Максимум.
    "B8", "D8", "F8", "H8", "J8",
    # Ручные границы оси Excel.
    "C10", "G10",
}


def _legacy_excel_password_hash(password: str) -> str:
    """Возвращает совместимый с Excel legacy-хэш для защиты листа/структуры."""
    value_hash = 0
    for idx, char in enumerate(password, 1):
        value = ord(char) << idx
        rotated = value >> 15
        value &= 0x7FFF
        value_hash ^= value | rotated
    value_hash ^= len(password)
    value_hash ^= 0xCE4B
    return f"{value_hash:X}"


def _protected_style_id(
    styles_root: ET.Element,
    style_id: int,
    *,
    locked: bool,
    hidden: bool,
    cache: dict[tuple[int, bool, bool], int],
) -> int:
    """Клонирует исходный cellXf, меняя только защиту ячейки."""
    key = (style_id, locked, hidden)
    cached = cache.get(key)
    if cached is not None:
        return cached

    cell_xfs = styles_root.find(f"{{{_NS}}}cellXfs")
    if cell_xfs is None:
        raise ValueError("В шаблоне Excel отсутствует cellXfs.")
    source_xfs = list(cell_xfs)
    if not 0 <= style_id < len(source_xfs):
        raise ValueError(f"Некорректный индекс стиля Excel: {style_id}.")

    clone = copy.deepcopy(source_xfs[style_id])
    for child in list(clone):
        if child.tag == f"{{{_NS}}}protection":
            clone.remove(child)
    protection = ET.Element(
        f"{{{_NS}}}protection",
        {"locked": "1" if locked else "0", "hidden": "1" if hidden else "0"},
    )
    # В CT_Xf protection идёт после alignment и до extLst.
    ext_list = clone.find(f"{{{_NS}}}extLst")
    if ext_list is None:
        clone.append(protection)
    else:
        clone.insert(list(clone).index(ext_list), protection)
    clone.set("applyProtection", "1")
    cell_xfs.append(clone)
    cell_xfs.set("count", str(len(cell_xfs)))
    new_id = len(cell_xfs) - 1
    cache[key] = new_id
    return new_id


def _apply_cell_protection_styles(
    styles_root: ET.Element,
    sheet1: ET.Element,
    sheet2: ET.Element,
) -> None:
    """Разблокирует только элементы формы и скрывает формулы остальных ячеек."""
    style_cache: dict[tuple[int, bool, bool], int] = {}
    for sheet_root, editable in ((sheet1, _EDITABLE_STAT_CELLS), (sheet2, set())):
        _, _, cells = _sheet_cells(sheet_root)
        for ref, cell in cells.items():
            formula = cell.find(f"{{{_NS}}}f")
            is_editable = ref in editable
            if not is_editable and formula is None:
                # Стандартное состояние Excel — locked=1; отдельный стиль не нужен.
                continue
            style_id = int(cell.attrib.get("s", "0"))
            new_style_id = _protected_style_id(
                styles_root,
                style_id,
                locked=not is_editable,
                hidden=(formula is not None and not is_editable),
                cache=style_cache,
            )
            cell.set("s", str(new_style_id))


def _set_sheet_protection(
    root: ET.Element,
    *,
    password_hash: str,
    allow_unlocked_selection: bool,
) -> None:
    """Включает максимально жёсткую защиту листа, оставляя ввод в unlocked-ячейках."""
    for old in root.findall(f"{{{_NS}}}sheetProtection"):
        root.remove(old)

    protection = ET.Element(
        f"{{{_NS}}}sheetProtection",
        {
            "password": password_hash,
            "sheet": "1",
            "objects": "1",
            "scenarios": "1",
            "formatCells": "1",
            "formatColumns": "1",
            "formatRows": "1",
            "insertColumns": "1",
            "insertRows": "1",
            "insertHyperlinks": "1",
            "deleteColumns": "1",
            "deleteRows": "1",
            "selectLockedCells": "1",
            "selectUnlockedCells": "0" if allow_unlocked_selection else "1",
            "sort": "1",
            "autoFilter": "1",
            "pivotTables": "1",
        },
    )

    children = list(root)
    insert_at = 0
    for idx, child in enumerate(children):
        local = child.tag.rsplit("}", 1)[-1]
        if local in {"sheetData", "sheetCalcPr"}:
            insert_at = idx + 1
    root.insert(insert_at, protection)


def _protect_workbook_structure(workbook_xml: bytes, password_hash: str) -> bytes:
    """Делает лист «Данные» VeryHidden и блокирует структуру книги паролем."""
    text = workbook_xml.decode("utf-8")

    sheet_pattern = r'(<sheet\b(?=[^>]*\bname="Данные")[^>]*?)\s+state="[^"]*"([^>]*/>)'
    text, count = re.subn(sheet_pattern, r'\1 state="veryHidden"\2', text, count=1)
    if count != 1:
        raise ValueError("Не удалось перевести лист «Данные» в VeryHidden.")

    text = re.sub(r'<workbookProtection\b[^>]*/>', '', text, count=1)
    protection = (
        f'<workbookProtection workbookPassword="{password_hash}" lockStructure="1"/>'
    )
    marker = "<bookViews>"
    if marker not in text:
        raise ValueError("В workbook.xml отсутствует bookViews.")
    text = text.replace(marker, protection + marker, 1)
    return text.encode("utf-8")


def _template_path() -> Path:
    return Path(__file__).resolve().parent.parent / _TEMPLATE_NAME


def _column_number(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch) - ord("A") + 1)
    return value


def _parse_csv(text: str) -> list[list[str | Decimal | None]]:
    raw = (text or "").lstrip("\ufeff").strip()
    if not raw:
        return []

    first_line = raw.splitlines()[0]
    delimiter = ";" if ";" in first_line else ","
    rows = list(csv.reader(io.StringIO(raw), delimiter=delimiter))
    if not rows:
        return []

    headers = [str(v).strip().lstrip("\ufeff") for v in rows[0]]
    if headers != _EXPECTED_HEADERS:
        raise ValueError("Неверная структура статистического CSV: ожидается 23 стандартных поля.")

    if len(rows) - 1 > _MAX_DATA_ROWS:
        raise ValueError(f"В статистическом CSV больше {_MAX_DATA_ROWS} строк данных.")

    out: list[list[str | Decimal | None]] = [headers]
    text_columns = {0, 11, 22}
    for src in rows[1:]:
        if len(src) != len(_EXPECTED_HEADERS):
            raise ValueError("Неверное количество полей в строке статистического CSV.")
        dst: list[str | Decimal | None] = []
        for idx, value in enumerate(src):
            value = str(value).strip()
            if idx in text_columns:
                dst.append(value)
                continue
            if value == "":
                dst.append(None)
                continue
            normalized = value.replace(" ", "").replace(",", ".")
            try:
                dst.append(Decimal(normalized))
            except InvalidOperation as exc:
                raise ValueError(f"Некорректное числовое значение в статистическом CSV: {value}") from exc
        out.append(dst)
    return out


def _sheet_cells(root: ET.Element) -> tuple[ET.Element, dict[int, ET.Element], dict[str, ET.Element]]:
    sheet_data = root.find(f"{{{_NS}}}sheetData")
    if sheet_data is None:
        raise ValueError("В шаблоне Excel отсутствует sheetData.")
    rows = {int(r.attrib["r"]): r for r in sheet_data.findall(f"{{{_NS}}}row") if "r" in r.attrib}
    cells: dict[str, ET.Element] = {}
    for row in rows.values():
        for cell in row.findall(f"{{{_NS}}}c"):
            ref = cell.attrib.get("r")
            if ref:
                cells[ref] = cell
    return sheet_data, rows, cells


def _ensure_cell(
    sheet_data: ET.Element,
    rows: dict[int, ET.Element],
    cells: dict[str, ET.Element],
    ref: str,
) -> ET.Element:
    cell = cells.get(ref)
    if cell is not None:
        return cell

    match = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    if not match:
        raise ValueError(f"Некорректный адрес ячейки: {ref}")
    row_no = int(match.group(2))
    row = rows.get(row_no)
    if row is None:
        row = ET.Element(f"{{{_NS}}}row", {"r": str(row_no)})
        inserted = False
        for pos, existing in enumerate(list(sheet_data)):
            existing_no = int(existing.attrib.get("r", "0"))
            if existing_no > row_no:
                sheet_data.insert(pos, row)
                inserted = True
                break
        if not inserted:
            sheet_data.append(row)
        rows[row_no] = row

    cell = ET.Element(f"{{{_NS}}}c", {"r": ref})
    col_no = _column_number(ref)
    inserted = False
    for pos, existing in enumerate(list(row)):
        existing_ref = existing.attrib.get("r", "")
        if existing_ref and _column_number(existing_ref) > col_no:
            row.insert(pos, cell)
            inserted = True
            break
    if not inserted:
        row.append(cell)
    cells[ref] = cell
    return cell


def _clear_cell_value(cell: ET.Element) -> None:
    for child in list(cell):
        if child.tag in {f"{{{_NS}}}v", f"{{{_NS}}}is", f"{{{_NS}}}f"}:
            cell.remove(child)
    cell.attrib.pop("t", None)


def _set_cell(cell: ET.Element, value: str | float | int | Decimal | None) -> None:
    _clear_cell_value(cell)
    if value is None:
        return
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, (int, float, Decimal)):
        v = ET.SubElement(cell, f"{{{_NS}}}v")
        v.text = str(value) if isinstance(value, Decimal) else repr(value)
        return

    cell.set("t", "inlineStr")
    is_node = ET.SubElement(cell, f"{{{_NS}}}is")
    t_node = ET.SubElement(is_node, f"{{{_NS}}}t")
    text = str(value)
    if text[:1].isspace() or text[-1:].isspace():
        t_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t_node.text = text


def _set_values(root: ET.Element, values: dict[str, str | float | int | Decimal | None]) -> None:
    sheet_data, rows, cells = _sheet_cells(root)
    for ref, value in values.items():
        _set_cell(_ensure_cell(sheet_data, rows, cells, ref), value)


def _set_formula_cache(cell: ET.Element, value: str | float | int) -> None:
    formula = cell.find(f"{{{_NS}}}f")
    if formula is None:
        raise ValueError(f"Ожидалась формула в ячейке {cell.attrib.get('r', '?')}.")
    for child in list(cell):
        if child.tag == f"{{{_NS}}}v":
            cell.remove(child)
    if value == "#N/A":
        cell.set("t", "e")
    elif isinstance(value, str):
        cell.set("t", "str")
    else:
        cell.attrib.pop("t", None)
    v = ET.SubElement(cell, f"{{{_NS}}}v")
    v.text = value if isinstance(value, str) else repr(float(value))


def _set_formula_caches(root: ET.Element, values: dict[str, str | float | int]) -> None:
    sheet_data, rows, cells = _sheet_cells(root)
    for ref, value in values.items():
        _set_formula_cache(_ensure_cell(sheet_data, rows, cells, ref), value)


def _write_csv_block(root: ET.Element, start_col: int, rows_data: Sequence[Sequence[str | Decimal | None]]) -> None:
    sheet_data, rows, cells = _sheet_cells(root)

    def col_letters(number: int) -> str:
        out = ""
        n = number
        while n:
            n, rem = divmod(n - 1, 26)
            out = chr(ord("A") + rem) + out
        return out

    for row_no in range(1, _MAX_DATA_ROWS + 2):
        for offset in range(len(_EXPECTED_HEADERS)):
            ref = f"{col_letters(start_col + offset)}{row_no}"
            value: str | Decimal | None = None
            if row_no <= len(rows_data):
                value = rows_data[row_no - 1][offset]
            _set_cell(_ensure_cell(sheet_data, rows, cells, ref), value)


def _stat_helper_values(
    rows_data: Sequence[Sequence[str | Decimal | None]],
    *,
    active_power: bool,
    shift_power: int,
    thresholds: Sequence[tuple[bool, int]],
    show_median: bool,
    show_50: bool,
    show_90: bool,
    show_99: bool,
    show_max: bool,
    y_axis_min: float,
    y_axis_max: float,
    weekend: bool,
) -> dict[str, list[str | float]]:
    """Вычисляет те же значения, что формулы служебных колонок листа «Данные»."""
    span = max(float(y_axis_max) - float(y_axis_min), 0.000001)
    shift = float(shift_power)
    source = {
        "q005": 1 if active_power else 12,
        "q05": 3 if active_power else 14,
        "q25": 4 if active_power else 15,
        "q50": 5 if active_power else 16,
        "q75": 6 if active_power else 17,
        "q95": 7 if active_power else 18,
        "q995": 9 if active_power else 20,
        "qmax": 10 if active_power else 21,
    }

    area_cols = ["BT", "BU", "BV", "BW", "BX", "BY", "BZ", "CA"] if weekend else [
        "AW", "AX", "AY", "AZ", "BA", "BB", "BC", "BD"
    ]
    line_cols = ["CB", "CC", "CD", "CE", "CF", "CG", "CH", "CI"] if weekend else [
        "BE", "BF", "BG", "BH", "BI", "BJ", "BK", "BL"
    ]
    threshold_cols = ["CJ", "CK", "CL", "CM", "CN"] if weekend else ["BM", "BN", "BO", "BP", "BQ"]
    constant_col = "CO" if weekend else "BR"
    result: dict[str, list[str | float]] = {col: [] for col in area_cols + line_cols + threshold_cols + [constant_col]}

    def raw_value(row: Sequence[str | Decimal | None], idx: int) -> float:
        if idx >= len(row) or row[idx] is None or row[idx] == "":
            # В арифметике Excel пустая числовая ячейка трактуется как 0.
            return 0.0
        return float(row[idx])

    def normalized(row: Sequence[str | Decimal | None], key: str) -> float:
        return (raw_value(row, source[key]) + shift - float(y_axis_min)) / span

    data_rows = list(rows_data[1:]) if rows_data else []
    for row_idx in range(_MAX_DATA_ROWS):
        row = data_rows[row_idx] if row_idx < len(data_rows) else []
        time_value = str(row[0]).strip() if row and row[0] is not None else ""
        if not time_value:
            for col in area_cols:
                result[col].append("")
            for col in line_cols + threshold_cols + [constant_col]:
                result[col].append("#N/A")
            continue

        q005 = max(0.0, min(1.0, normalized(row, "q005")))
        q05 = max(0.0, min(1.0, normalized(row, "q05")))
        q25 = max(0.0, min(1.0, normalized(row, "q25")))
        q50 = max(0.0, min(1.0, normalized(row, "q50")))
        q75 = max(0.0, min(1.0, normalized(row, "q75")))
        q95 = max(0.0, min(1.0, normalized(row, "q95")))
        q995 = max(0.0, min(1.0, normalized(row, "q995")))
        areas = [
            q005,
            max(0.0, q05 - q005),
            max(0.0, q25 - q05),
            max(0.0, q50 - q25),
            max(0.0, q75 - q50),
            max(0.0, q95 - q75),
            max(0.0, q995 - q95),
            max(0.0, 1.0 - q995),
        ]
        for col, value in zip(area_cols, areas):
            result[col].append(value)

        line_values: list[str | float] = [
            round(raw_value(row, source["q50"]) + shift, 1) if show_median else "#N/A",
            round(raw_value(row, source["q25"]) + shift, 1) if show_50 else "#N/A",
            round(raw_value(row, source["q75"]) + shift, 1) if show_50 else "#N/A",
            round(raw_value(row, source["q05"]) + shift, 1) if show_90 else "#N/A",
            round(raw_value(row, source["q95"]) + shift, 1) if show_90 else "#N/A",
            round(raw_value(row, source["q005"]) + shift, 1) if show_99 else "#N/A",
            round(raw_value(row, source["q995"]) + shift, 1) if show_99 else "#N/A",
            round(raw_value(row, source["qmax"]) + shift, 1) if show_max else "#N/A",
        ]
        for col, value in zip(line_cols, line_values):
            result[col].append(value)

        for col, (enabled, threshold) in zip(threshold_cols, thresholds):
            if bool(enabled) and int(threshold) > 0:
                result[col].append(round(float(threshold), 1))
            else:
                result[col].append("#N/A")
        result[constant_col].append(float(y_axis_max))

    return result


def _set_helper_formula_caches(root: ET.Element, values: dict[str, list[str | float]]) -> None:
    _, _, cells = _sheet_cells(root)
    for col, column_values in values.items():
        if len(column_values) != _MAX_DATA_ROWS:
            raise ValueError(f"Неверный размер кэша служебной колонки {col}.")
        for offset, value in enumerate(column_values, start=2):
            ref = f"{col}{offset}"
            cell = cells.get(ref)
            if cell is None:
                raise ValueError(f"В шаблоне отсутствует служебная ячейка {ref}.")
            _set_formula_cache(cell, value)


def _set_real_line_formulas(root: ET.Element, *, weekend: bool) -> None:
    """Переводит формулы линий/порогов в реальные единицы мощности.

    Серые stacked-area диапазоны остаются нормализованными 0..1 на отдельном
    слое диаграммы. Линейный слой использует реальные кВт/кВА и собственную
    реальную ось Y, поэтому подсказка Excel совпадает с видимой шкалой.
    """
    _, _, cells = _sheet_cells(root)
    if weekend:
        time_col = "Y"
        source = {
            "q005": ("Z", "AK"),
            "q05": ("AB", "AM"),
            "q25": ("AC", "AN"),
            "q50": ("AD", "AO"),
            "q75": ("AE", "AP"),
            "q95": ("AF", "AQ"),
            "q995": ("AH", "AS"),
            "qmax": ("AI", "AT"),
        }
        line_cols = ["CB", "CC", "CD", "CE", "CF", "CG", "CH", "CI"]
        threshold_cols = ["CJ", "CK", "CL", "CM", "CN"]
        constant_col = "CO"
    else:
        time_col = "A"
        source = {
            "q005": ("B", "M"),
            "q05": ("D", "O"),
            "q25": ("E", "P"),
            "q50": ("F", "Q"),
            "q75": ("G", "R"),
            "q95": ("H", "S"),
            "q995": ("J", "U"),
            "qmax": ("K", "V"),
        }
        line_cols = ["BE", "BF", "BG", "BH", "BI", "BJ", "BK", "BL"]
        threshold_cols = ["BM", "BN", "BO", "BP", "BQ"]
        constant_col = "BR"

    line_specs = [
        (line_cols[0], "$B$8", "q50"),
        (line_cols[1], "$D$8", "q25"),
        (line_cols[2], "$D$8", "q75"),
        (line_cols[3], "$F$8", "q05"),
        (line_cols[4], "$F$8", "q95"),
        (line_cols[5], "$H$8", "q005"),
        (line_cols[6], "$H$8", "q995"),
        (line_cols[7], "$J$8", "qmax"),
    ]
    threshold_specs = [
        (threshold_cols[0], "$C$6", "$B$6"),
        (threshold_cols[1], "$F$6", "$E$6"),
        (threshold_cols[2], "$I$6", "$H$6"),
        (threshold_cols[3], "$L$6", "$K$6"),
        (threshold_cols[4], "$M$6", "$O$6"),
    ]

    def set_formula(ref: str, text: str) -> None:
        cell = cells.get(ref)
        if cell is None:
            raise ValueError(f"В шаблоне отсутствует служебная ячейка {ref}.")
        formula = cell.find(f"{{{_NS}}}f")
        if formula is None:
            raise ValueError(f"Ожидалась формула в служебной ячейке {ref}.")
        # Эти формулы записываются поштучно. Если исходная ячейка была частью
        # shared-formula, нельзя оставлять t="shared"/si/ref и одновременно
        # записывать собственный текст формулы: Excel считает такую структуру
        # повреждённой и удаляет формулы при восстановлении книги.
        formula.attrib.clear()
        formula.text = text

    for row_no in range(2, _MAX_DATA_ROWS + 2):
        def power_expr(key: str) -> str:
            active_col, apparent_col = source[key]
            return (
                f'ROUND(IF(Статистика!$C$4="Параллельный режим (активная мощность)",'
                f'{active_col}{row_no},{apparent_col}{row_no})+Статистика!$J$4,1)'
            )

        for col, state_ref, key in line_specs:
            set_formula(
                f"{col}{row_no}",
                f'IF({time_col}{row_no}="",NA(),IF(Статистика!{state_ref}="Вкл",{power_expr(key)},NA()))',
            )

        for col, state_ref, value_ref in threshold_specs:
            set_formula(
                f"{col}{row_no}",
                f'IF(AND({time_col}{row_no}<>"",Статистика!{state_ref}="Вкл",Статистика!{value_ref}>0),'
                f'ROUND(Статистика!{value_ref},1),NA())',
            )

        set_formula(
            f"{constant_col}{row_no}",
            f'IF({time_col}{row_no}="",NA(),Статистика!$G$10)',
        )


def _set_chart_real_y_axis(root: ET.Element, y_axis_min: float, y_axis_max: float) -> None:
    """Задаёт реальный масштаб Y линейному слою диаграммы Excel."""
    if y_axis_max <= y_axis_min:
        raise ValueError("Верхняя граница оси должна быть больше нижней.")
    axes = root.findall(f".//{{{_C_NS}}}valAx")
    if not axes:
        raise ValueError("В диаграмме Excel не найдена ось значений Y.")

    major_unit = (float(y_axis_max) - float(y_axis_min)) / 5.0
    for axis in axes:
        scaling = axis.find(f"{{{_C_NS}}}scaling")
        if scaling is None:
            raise ValueError("В диаграмме Excel отсутствует scaling оси Y.")
        min_node = scaling.find(f"{{{_C_NS}}}min")
        max_node = scaling.find(f"{{{_C_NS}}}max")
        if min_node is None or max_node is None:
            raise ValueError("В диаграмме Excel отсутствуют фиксированные min/max оси Y.")
        min_node.set("val", repr(float(y_axis_min)))
        max_node.set("val", repr(float(y_axis_max)))

        major_node = axis.find(f"{{{_C_NS}}}majorUnit")
        if major_node is None:
            major_node = ET.SubElement(axis, f"{{{_C_NS}}}majorUnit")
        major_node.set("val", repr(float(major_unit)))


def _chart_formula_column(formula: str) -> str | None:
    match = re.fullmatch(r"(?:'Данные'|Данные)!\$([A-Z]+)\$2:\$\1\$289", (formula or "").strip())
    return match.group(1) if match else None


def _replace_chart_cache(cache: ET.Element, values: Sequence[str | float]) -> None:
    for child in list(cache):
        local_name = child.tag.rsplit("}", 1)[-1]
        if local_name in {"ptCount", "pt"}:
            cache.remove(child)
    ET.SubElement(cache, f"{{{_C_NS}}}ptCount", {"val": str(len(values))})
    for idx, value in enumerate(values):
        point = ET.SubElement(cache, f"{{{_C_NS}}}pt", {"idx": str(idx)})
        node = ET.SubElement(point, f"{{{_C_NS}}}v")
        if isinstance(value, str):
            node.text = value
        else:
            node.text = repr(float(value))


def _update_chart_caches(
    chart_xml: bytes,
    *,
    weekday_times: Sequence[str],
    weekend_times: Sequence[str],
    helper_values: dict[str, list[str | float]],
    real_y_axis: tuple[float, float] | None = None,
) -> bytes:
    root = ET.fromstring(chart_xml)
    for series in root.findall(f".//{{{_C_NS}}}ser"):
        str_ref = series.find(f"{{{_C_NS}}}cat/{{{_C_NS}}}strRef")
        if str_ref is not None:
            formula_node = str_ref.find(f"{{{_C_NS}}}f")
            cache = str_ref.find(f"{{{_C_NS}}}strCache")
            if formula_node is not None and cache is not None:
                column = _chart_formula_column(formula_node.text or "")
                if column == "A":
                    _replace_chart_cache(cache, weekday_times)
                elif column == "Y":
                    _replace_chart_cache(cache, weekend_times)

        num_ref = series.find(f"{{{_C_NS}}}val/{{{_C_NS}}}numRef")
        if num_ref is None:
            continue
        formula_node = num_ref.find(f"{{{_C_NS}}}f")
        cache = num_ref.find(f"{{{_C_NS}}}numCache")
        if formula_node is None or cache is None:
            continue
        column = _chart_formula_column(formula_node.text or "")
        if column and column in helper_values:
            _replace_chart_cache(cache, helper_values[column])

    if real_y_axis is not None:
        _set_chart_real_y_axis(root, real_y_axis[0], real_y_axis[1])

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _time_cache(rows_data: Sequence[Sequence[str | Decimal | None]]) -> list[str]:
    rows = list(rows_data[1:]) if rows_data else []
    result: list[str] = []
    for idx in range(_MAX_DATA_ROWS):
        if idx < len(rows) and rows[idx] and rows[idx][0] is not None:
            result.append(str(rows[idx][0]))
        else:
            result.append("")
    return result


def _namespace_is_used(root: ET.Element, uri: str) -> bool:
    marker = f"{{{uri}}}"
    for elem in root.iter():
        if isinstance(elem.tag, str) and elem.tag.startswith(marker):
            return True
        if any(str(name).startswith(marker) for name in elem.attrib):
            return True
    return False


def _preserve_ignorable_namespaces(root: ET.Element) -> None:
    # ElementTree выбрасывает неиспользуемые xmlns-декларации. Excel требует,
    # чтобы все префиксы из mc:Ignorable оставались объявленными.
    ignorable = root.attrib.get(f"{{{_MC_NS}}}Ignorable", "")
    for prefix in ignorable.split():
        uri = _IGNORABLE_NAMESPACES.get(prefix)
        if uri and not _namespace_is_used(root, uri):
            root.set(f"xmlns:{prefix}", uri)


def _serialize_xml(root: ET.Element) -> bytes:
    _preserve_ignorable_namespaces(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _force_recalculation(workbook_xml: bytes) -> bytes:
    text = workbook_xml.decode("utf-8")
    match = re.search(r"<calcPr\b([^>]*)/>", text)
    if not match:
        return workbook_xml

    attrs = match.group(1)
    attrs = re.sub(r'\s+(?:calcMode|fullCalcOnLoad|forceFullCalc)="[^"]*"', "", attrs)
    replacement = f'<calcPr{attrs} calcMode="auto" fullCalcOnLoad="1" forceFullCalc="1"/>'
    return (text[: match.start()] + replacement + text[match.end() :]).encode("utf-8")


def _remove_calc_chain_relationship(rels_xml: bytes) -> bytes:
    """Удаляет ссылку workbook -> calcChain при изменении формул.

    Старая цепочка вычислений шаблона становится недостоверной после замены
    формул служебных колонок. Excel сам построит новую цепочку при открытии.
    """
    text = rels_xml.decode("utf-8")
    pattern = (
        r'<Relationship\b(?=[^>]*\bType="'
        r'http://schemas\.openxmlformats\.org/officeDocument/2006/relationships/calcChain")'
        r'[^>]*/>'
    )
    return re.sub(pattern, "", text).encode("utf-8")


def _remove_calc_chain_content_type(content_types_xml: bytes) -> bytes:
    """Удаляет Content Types запись calcChain после удаления самого part."""
    text = content_types_xml.decode("utf-8")
    pattern = r'<Override\b(?=[^>]*\bPartName="/xl/calcChain\.xml")[^>]*/>'
    return re.sub(pattern, "", text).encode("utf-8")


def build_statistical_workbook(
    *,
    weekday_csv: str,
    weekend_csv: str,
    object_title: str,
    measurement_period: str,
    power_mode: str,
    shift_power: int,
    thresholds: Sequence[tuple[bool, int]],
    show_median: bool,
    show_50: bool,
    show_90: bool,
    show_99: bool,
    show_max: bool,
    y_axis_min: float,
    y_axis_max: float,
) -> bytes:
    """Создаёт заполненную копию Excel-шаблона статистики, не меняя исходный шаблон."""
    if len(thresholds) != 5:
        raise ValueError("Для экспорта требуется ровно 5 порогов мощности.")
    if y_axis_max <= y_axis_min:
        raise ValueError("Верхняя граница оси должна быть больше нижней.")

    template_path = _template_path()
    if not template_path.is_file():
        raise FileNotFoundError(f"Не найден шаблон Excel: {template_path}")

    weekday_rows = _parse_csv(weekday_csv)
    weekend_rows = _parse_csv(weekend_csv)
    if not weekday_rows and not weekend_rows:
        raise ValueError("Нет данных weekday/weekend для экспорта.")

    with zipfile.ZipFile(template_path, "r") as src:
        sheet1 = ET.fromstring(src.read("xl/worksheets/sheet1.xml"))
        sheet2 = ET.fromstring(src.read("xl/worksheets/sheet2.xml"))
        styles = ET.fromstring(src.read("xl/styles.xml"))

        threshold_values = [int(item[1]) for item in thresholds]
        threshold_states = ["Вкл" if bool(item[0]) else "Выкл" for item in thresholds]

        _set_values(
            sheet1,
            {
                "C1": object_title or "",
                "C2": measurement_period or "",
                "C4": power_mode,
                "J4": int(shift_power),
                "B6": threshold_values[0],
                "C6": threshold_states[0],
                "E6": threshold_values[1],
                "F6": threshold_states[1],
                "H6": threshold_values[2],
                "I6": threshold_states[2],
                "K6": threshold_values[3],
                "L6": threshold_states[3],
                "O6": threshold_values[4],
                "M6": threshold_states[4],
                "B8": "Вкл" if show_median else "Выкл",
                "D8": "Вкл" if show_50 else "Выкл",
                "F8": "Вкл" if show_90 else "Выкл",
                "H8": "Вкл" if show_99 else "Выкл",
                "J8": "Вкл" if show_max else "Выкл",
                "C10": float(y_axis_min),
                "G10": float(y_axis_max),
            },
        )

        is_active = power_mode == "Параллельный режим (активная мощность)"
        unit = "кВт" if is_active else "кВА"
        power_name = "Активная мощность, кВт" if is_active else "Полная мощность, кВА"
        axis_range = float(y_axis_max) - float(y_axis_min)
        ticks = [float(y_axis_min) + factor * axis_range for factor in (1.0, 0.8, 0.6, 0.4, 0.2, 0.0)]
        _set_formula_caches(
            sheet1,
            {
                "K4": unit,
                "P6": unit,
                "D10": unit,
                "H10": unit,
                "I13": f"Будние дни — {power_name}",
                "I38": f"Выходные/праздничные дни — {power_name}",
                "A14": ticks[0],
                "A18": ticks[1],
                "A22": ticks[2],
                "A26": ticks[3],
                "A30": ticks[4],
                "A34": ticks[5],
                "A39": ticks[0],
                "A43": ticks[1],
                "A47": ticks[2],
                "A51": ticks[3],
                "A55": ticks[4],
                "A59": ticks[5],
            },
        )

        if weekday_rows:
            _write_csv_block(sheet2, 1, weekday_rows)   # A:W
        else:
            _write_csv_block(sheet2, 1, [_EXPECTED_HEADERS])
        if weekend_rows:
            _write_csv_block(sheet2, 25, weekend_rows)  # Y:AU
        else:
            _write_csv_block(sheet2, 25, [_EXPECTED_HEADERS])

        weekday_helpers = _stat_helper_values(
            weekday_rows or [_EXPECTED_HEADERS],
            active_power=is_active,
            shift_power=shift_power,
            thresholds=thresholds,
            show_median=show_median,
            show_50=show_50,
            show_90=show_90,
            show_99=show_99,
            show_max=show_max,
            y_axis_min=y_axis_min,
            y_axis_max=y_axis_max,
            weekend=False,
        )
        weekend_helpers = _stat_helper_values(
            weekend_rows or [_EXPECTED_HEADERS],
            active_power=is_active,
            shift_power=shift_power,
            thresholds=thresholds,
            show_median=show_median,
            show_50=show_50,
            show_90=show_90,
            show_99=show_99,
            show_max=show_max,
            y_axis_min=y_axis_min,
            y_axis_max=y_axis_max,
            weekend=True,
        )
        helper_values = {**weekday_helpers, **weekend_helpers}
        _set_real_line_formulas(sheet2, weekend=False)
        _set_real_line_formulas(sheet2, weekend=True)
        _set_helper_formula_caches(sheet2, helper_values)

        password_hash = _legacy_excel_password_hash(_PROTECTION_PASSWORD)
        _apply_cell_protection_styles(styles, sheet1, sheet2)
        _set_sheet_protection(
            sheet1,
            password_hash=password_hash,
            allow_unlocked_selection=True,
        )
        _set_sheet_protection(
            sheet2,
            password_hash=password_hash,
            allow_unlocked_selection=False,
        )

        weekday_times = _time_cache(weekday_rows or [_EXPECTED_HEADERS])
        weekend_times = _time_cache(weekend_rows or [_EXPECTED_HEADERS])
        replacements = {
            "xl/worksheets/sheet1.xml": _serialize_xml(sheet1),
            "xl/worksheets/sheet2.xml": _serialize_xml(sheet2),
            "xl/styles.xml": _serialize_xml(styles),
            "xl/workbook.xml": _protect_workbook_structure(
                _force_recalculation(src.read("xl/workbook.xml")),
                password_hash,
            ),
            "xl/_rels/workbook.xml.rels": _remove_calc_chain_relationship(
                src.read("xl/_rels/workbook.xml.rels")
            ),
            "[Content_Types].xml": _remove_calc_chain_content_type(
                src.read("[Content_Types].xml")
            ),
        }
        for chart_name in ("chart1.xml", "chart2.xml", "chart3.xml", "chart4.xml"):
            path = f"xl/charts/{chart_name}"
            replacements[path] = _update_chart_caches(
                src.read(path),
                weekday_times=weekday_times,
                weekend_times=weekend_times,
                helper_values=helper_values,
                real_y_axis=(float(y_axis_min), float(y_axis_max))
                if chart_name in {"chart2.xml", "chart4.xml"}
                else None,
            )

        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as dst:
            for info in src.infolist():
                if info.filename == "xl/calcChain.xml":
                    continue
                payload = replacements.get(info.filename)
                if payload is None:
                    payload = src.read(info.filename)
                dst.writestr(info, payload)

    return out.getvalue()
