from __future__ import annotations

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
    if isinstance(value, str):
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

        replacements = {
            "xl/worksheets/sheet1.xml": _serialize_xml(sheet1),
            "xl/worksheets/sheet2.xml": _serialize_xml(sheet2),
            "xl/workbook.xml": _force_recalculation(src.read("xl/workbook.xml")),
        }

        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as dst:
            for info in src.infolist():
                payload = replacements.get(info.filename)
                if payload is None:
                    payload = src.read(info.filename)
                dst.writestr(info, payload)

    return out.getvalue()
