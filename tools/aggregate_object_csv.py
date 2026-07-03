# -*- coding: utf-8 -*-
"""
Агрегатор 4 CSV-файлов ячеек в один CSV "виртуального прибора" по объекту.

Математика:
- знак P/Q в исходных файлах уже приведен к правилу:
  + = поток в сторону объекта, - = поток из объекта;
- P/Q по фазам суммируются по 4 файлам;
- P_total/Q_total считаются из фаз;
- S по фазам считается из P/Q, S_total = сумма S фаз;
- PF считается заново;
- Irms считается заново из Sфазы и Urmsфазы;
- U, частота, температура, углы — медиана по 4 файлам;
- uptime — максимум из 4 файлов;
- строки пишутся только для секунд, которые есть во всех 4 файлах;
- структура и порядок колонок сохраняются как в исходном CSV.

Запуск:
    python aggregate_object_csv.py --out object.csv cell1.csv cell2.csv cell3.csv cell4.csv

Если запустить без аргументов, откроются стандартные окна выбора файлов Windows.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Iterable, List

import pandas as pd


EXPECTED_COLUMNS = [
    "timestamp", "uptime", "temp", "pf_total", "pf_L1", "pf_L2", "pf_L3",
    "U_L1_L2", "U_L2_L3", "U_L3_L1", "Irms_L1", "Irms_L2", "Irms_L3",
    "S_total", "S_L1", "S_L2", "S_L3", "P_total", "P_L1", "P_L2", "P_L3",
    "Q_total", "Q_L1", "Q_L2", "Q_L3", "N_total", "N_L1", "N_L2", "N_L3",
    "frequency", "Urms_L1", "Urms_L2", "Urms_L3", "angle_L1_L2", "angle_L2_L3", "angle_L3_L1",
]

PHASES = ["L1", "L2", "L3"]
MEDIAN_COLUMNS = [
    "temp",
    "U_L1_L2", "U_L2_L3", "U_L3_L1",
    "frequency",
    "Urms_L1", "Urms_L2", "Urms_L3",
    "angle_L1_L2", "angle_L2_L3", "angle_L3_L1",
]

DECIMALS = {
    "temp": 1,
    "pf_total": 3, "pf_L1": 3, "pf_L2": 3, "pf_L3": 3,
    "U_L1_L2": 2, "U_L2_L3": 2, "U_L3_L1": 2,
    "Irms_L1": 2, "Irms_L2": 2, "Irms_L3": 2,
    "S_total": 2, "S_L1": 2, "S_L2": 2, "S_L3": 2,
    "P_total": 2, "P_L1": 2, "P_L2": 2, "P_L3": 2,
    "Q_total": 2, "Q_L1": 2, "Q_L2": 2, "Q_L3": 2,
    "N_total": 2, "N_L1": 2, "N_L2": 2, "N_L3": 2,
    "frequency": 3,
    "Urms_L1": 2, "Urms_L2": 2, "Urms_L3": 2,
    "angle_L1_L2": 1, "angle_L2_L3": 1, "angle_L3_L1": 1,
}


def read_csv_file(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    df = pd.read_csv(path, sep=";", decimal=",", encoding="utf-8-sig")
    columns = list(df.columns)
    if columns != EXPECTED_COLUMNS:
        missing = [c for c in EXPECTED_COLUMNS if c not in columns]
        extra = [c for c in columns if c not in EXPECTED_COLUMNS]
        raise ValueError(
            f"Неверная структура колонок в файле {path}\n"
            f"Нет колонок: {missing}\n"
            f"Лишние колонки: {extra}\n"
            f"Порядок колонок должен быть 1 в 1 как в исходном файле."
        )

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="raise")
    if df["timestamp"].duplicated().any():
        dup = df.loc[df["timestamp"].duplicated(), "timestamp"].iloc[0]
        raise ValueError(f"В файле {path} есть повтор timestamp: {dup}")

    for col in EXPECTED_COLUMNS:
        if col != "timestamp":
            df[col] = pd.to_numeric(df[col], errors="raise")

    return df.sort_values("timestamp").set_index("timestamp")


def safe_pf(p: pd.Series, s: pd.Series) -> pd.Series:
    result = p / s
    result = result.where(s != 0, 0.0)
    result = result.replace([math.inf, -math.inf], 0.0).fillna(0.0)
    return result


def aggregate_frames(frames: List[pd.DataFrame]) -> pd.DataFrame:
    if len(frames) != 4:
        raise ValueError("Нужно ровно 4 входных CSV-файла.")

    common_index = frames[0].index
    for df in frames[1:]:
        common_index = common_index.intersection(df.index)

    common_index = common_index.sort_values()
    if len(common_index) == 0:
        raise ValueError("Нет ни одной общей секунды во всех 4 файлах.")

    frames = [df.loc[common_index].copy() for df in frames]
    out = pd.DataFrame(index=common_index)

    out["uptime"] = pd.concat([df["uptime"] for df in frames], axis=1).max(axis=1)

    for col in MEDIAN_COLUMNS:
        out[col] = pd.concat([df[col] for df in frames], axis=1).median(axis=1)

    for ph in PHASES:
        out[f"P_{ph}"] = sum(df[f"P_{ph}"] for df in frames)
        out[f"Q_{ph}"] = sum(df[f"Q_{ph}"] for df in frames)
        out[f"S_{ph}"] = (out[f"P_{ph}"] ** 2 + out[f"Q_{ph}"] ** 2) ** 0.5
        out[f"N_{ph}"] = out[f"Q_{ph}"].abs()
        out[f"pf_{ph}"] = safe_pf(out[f"P_{ph}"], out[f"S_{ph}"])
        out[f"Irms_{ph}"] = (out[f"S_{ph}"] * 1000.0 / out[f"Urms_{ph}"]).abs()

    out["P_total"] = out[["P_L1", "P_L2", "P_L3"]].sum(axis=1)
    out["Q_total"] = out[["Q_L1", "Q_L2", "Q_L3"]].sum(axis=1)
    out["S_total"] = out[["S_L1", "S_L2", "S_L3"]].sum(axis=1)
    out["N_total"] = out[["N_L1", "N_L2", "N_L3"]].sum(axis=1)
    out["pf_total"] = safe_pf(out["P_total"], out["S_total"])

    out = out.reset_index()
    out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return out[EXPECTED_COLUMNS]


def format_value(value, col: str) -> str:
    if pd.isna(value):
        return ""
    if col == "timestamp":
        return str(value)
    if col == "uptime":
        return str(int(round(float(value))))

    decimals = DECIMALS.get(col, 3)
    text = f"{float(value):.{decimals}f}"
    text = text.rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return text.replace(".", ",")


def write_csv_file(df: pd.DataFrame, path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        f.write(";".join(EXPECTED_COLUMNS) + "\n")
        for _, row in df.iterrows():
            f.write(";".join(format_value(row[col], col) for col in EXPECTED_COLUMNS) + "\n")


def choose_files_gui() -> tuple[List[Path], Path]:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.withdraw()

    selected = filedialog.askopenfilenames(
        title="Выберите 4 CSV-файла ячеек",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
    )
    files = [Path(p) for p in selected]
    if len(files) != 4:
        messagebox.showerror("Ошибка", "Нужно выбрать ровно 4 CSV-файла.")
        raise SystemExit(2)

    output = filedialog.asksaveasfilename(
        title="Куда сохранить итоговый CSV",
        defaultextension=".csv",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
    )
    if not output:
        raise SystemExit(2)

    return files, Path(output)


def parse_args(argv: Iterable[str]) -> tuple[List[Path], Path]:
    parser = argparse.ArgumentParser(
        description="Собрать 4 CSV ячеек в один CSV по объекту без изменения структуры колонок."
    )
    parser.add_argument("files", nargs="*", help="4 входных CSV-файла")
    parser.add_argument("--out", "-o", required=False, help="Итоговый CSV-файл")
    args = parser.parse_args(list(argv))

    if not args.files and not args.out:
        return choose_files_gui()

    files = [Path(p) for p in args.files]
    if len(files) != 4:
        parser.error("Нужно передать ровно 4 входных CSV-файла.")
    if not args.out:
        parser.error("Нужно указать --out итоговый_файл.csv")

    return files, Path(args.out)


def main(argv: Iterable[str] | None = None) -> int:
    try:
        files, output = parse_args(sys.argv[1:] if argv is None else argv)
        frames = [read_csv_file(path) for path in files]
        result = aggregate_frames(frames)
        write_csv_file(result, output)
        print(f"Готово: {output}")
        print(f"Строк записано: {len(result)}")
        print(f"Период: {result['timestamp'].iloc[0]} ... {result['timestamp'].iloc[-1]}")
        return 0
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
