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
- при включённом RECOVER_CT_FAILURES до суммирования восстанавливается только
  аномально заниженная фаза каждого входного файла;
- структура и порядок колонок сохраняются как в исходном CSV.

Восстановление по умолчанию отключено. Служебный параметр --stats-out пишет
JSON-статистику для управляющего workflow и не изменяет структуру итогового CSV.

Запуск:
    python aggregate_object_csv.py --out object.csv cell1.csv cell2.csv cell3.csv cell4.csv

Для управляющего workflow можно дополнительно указать --stats-out stats.json.

Если запустить без аргументов, откроются стандартные окна выбора файлов Windows.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd


EXPECTED_COLUMNS = [
    "timestamp", "uptime", "temp", "pf_total", "pf_L1", "pf_L2", "pf_L3",
    "U_L1_L2", "U_L2_L3", "U_L3_L1", "Irms_L1", "Irms_L2", "Irms_L3",
    "S_total", "S_L1", "S_L2", "S_L3", "P_total", "P_L1", "P_L2", "P_L3",
    "Q_total", "Q_L1", "Q_L2", "Q_L3", "N_total", "N_L1", "N_L2", "N_L3",
    "frequency", "Urms_L1", "Urms_L2", "Urms_L3", "angle_L1_L2", "angle_L2_L3", "angle_L3_L1",
]
NUMERIC_COLUMNS = [column for column in EXPECTED_COLUMNS if column != "timestamp"]

PHASES = ["L1", "L2", "L3"]
RECOVER_CT_FAILURES = True
CT_CURRENT_DEVIATION_THRESHOLD_PERCENT = 90.0
MIN_HEALTHY_PAIR_CURRENT_A = 1.0
PAIR_SELECTION_TIE_TOLERANCE = 1e-12

PHASE_PAIRS = [
    ("L1", "L2", "L3"),
    ("L1", "L3", "L2"),
    ("L2", "L3", "L1"),
]
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

RecoveryStats = Dict[str, object]


def empty_recovery_stats() -> RecoveryStats:
    """Создаёт пустую статистику восстановления для одного входного файла."""
    return {
        "recovered": {phase: 0 for phase in PHASES},
        "total_recovered": 0,
        "not_recovered": 0,
        "missing_data_rows": 0,
    }


def count_missing_data_rows(df: pd.DataFrame) -> int:
    """Считает строки, содержащие хотя бы одно пустое или бесконечное значение."""
    finite_values = df[NUMERIC_COLUMNS].apply(
        lambda column: column.map(lambda value: math.isfinite(float(value)))
    )
    return int((~finite_values.all(axis=1)).sum())


def align_common_timestamps(frames: List[pd.DataFrame]) -> List[pd.DataFrame]:
    """Возвращает копии четырёх таблиц, ограниченные общими временными метками."""
    if len(frames) != 4:
        raise ValueError("Нужно ровно 4 входных CSV-файла.")

    common_index = frames[0].index
    for df in frames[1:]:
        common_index = common_index.intersection(df.index)

    common_index = common_index.sort_values()
    if len(common_index) == 0:
        raise ValueError("Нет ни одной общей секунды во всех 4 файлах.")

    return [df.loc[common_index].copy() for df in frames]


def pair_relative_difference(first_current: float, second_current: float) -> float:
    """Вычисляет симметричное относительное расхождение токов пары в процентах."""
    pair_mean = first_current / 2.0 + second_current / 2.0
    if pair_mean == 0.0:
        return 0.0
    return abs(first_current - second_current) / pair_mean * 100.0


def has_potential_failure(
    currents: Dict[str, float],
    pair: tuple[str, str, str],
) -> bool:
    """Проверяет, может ли вариант исправной пары означать превышение порога."""
    first_phase, second_phase, suspect_phase = pair
    pair_mean = currents[first_phase] / 2.0 + currents[second_phase] / 2.0
    suspect_current = currents[suspect_phase]

    if pair_mean <= MIN_HEALTHY_PAIR_CURRENT_A:
        return (
            abs(suspect_current - pair_mean)
            > pair_mean * CT_CURRENT_DEVIATION_THRESHOLD_PERCENT / 100.0
        )

    if suspect_current >= pair_mean:
        return False

    deviation = (pair_mean - suspect_current) / pair_mean * 100.0
    return deviation > CT_CURRENT_DEVIATION_THRESHOLD_PERCENT


def recover_ct_failures(df: pd.DataFrame) -> tuple[pd.DataFrame, RecoveryStats]:
    """
    Восстанавливает отказ одной фазы по двум наиболее близким токам.

    Исходная таблица не изменяется. Для найденной заниженной фазы атомарно
    пересчитываются только P, Q, S, N, pf и Irms; общие поля не затрагиваются.
    """
    result = df.copy()
    stats = empty_recovery_stats()
    recovered = stats["recovered"]
    prepared_phases = set()

    for index, row in df.iterrows():
        currents = {phase: float(row[f"Irms_{phase}"]) for phase in PHASES}
        if any(not math.isfinite(value) or value < 0.0 for value in currents.values()):
            stats["not_recovered"] += 1
            continue

        differences = {
            pair: pair_relative_difference(currents[pair[0]], currents[pair[1]])
            for pair in PHASE_PAIRS
        }
        minimum_difference = min(differences.values())
        closest_pairs = [
            pair
            for pair, difference in differences.items()
            if abs(difference - minimum_difference) <= PAIR_SELECTION_TIE_TOLERANCE
        ]

        if len(closest_pairs) != 1:
            if any(has_potential_failure(currents, pair) for pair in closest_pairs):
                stats["not_recovered"] += 1
            continue

        healthy_first, healthy_second, suspect_phase = closest_pairs[0]
        pair_mean = (
            currents[healthy_first] / 2.0 + currents[healthy_second] / 2.0
        )
        suspect_current = currents[suspect_phase]

        if pair_mean <= MIN_HEALTHY_PAIR_CURRENT_A:
            if has_potential_failure(currents, closest_pairs[0]):
                stats["not_recovered"] += 1
            continue

        if suspect_current >= pair_mean:
            continue

        deviation = (pair_mean - suspect_current) / pair_mean * 100.0
        if deviation <= CT_CURRENT_DEVIATION_THRESHOLD_PERCENT:
            continue

        healthy_values = [
            float(row[f"{parameter}_{phase}"])
            for parameter in ("P", "Q")
            for phase in (healthy_first, healthy_second)
        ]
        target_urms = float(row[f"Urms_{suspect_phase}"])
        if (
            any(not math.isfinite(value) for value in healthy_values)
            or not math.isfinite(target_urms)
            or target_urms <= 0.0
        ):
            stats["not_recovered"] += 1
            continue

        p_value = healthy_values[0] / 2.0 + healthy_values[1] / 2.0
        q_value = healthy_values[2] / 2.0 + healthy_values[3] / 2.0
        s_value = math.hypot(p_value, q_value)
        n_value = abs(q_value)
        pf_value = p_value / s_value if s_value != 0.0 else 0.0
        irms_value = abs(s_value * 1000.0 / target_urms)
        restored_values = [
            p_value,
            q_value,
            s_value,
            n_value,
            pf_value,
            irms_value,
        ]
        if any(not math.isfinite(value) for value in restored_values):
            stats["not_recovered"] += 1
            continue

        target_columns = [
            f"P_{suspect_phase}",
            f"Q_{suspect_phase}",
            f"S_{suspect_phase}",
            f"N_{suspect_phase}",
            f"pf_{suspect_phase}",
            f"Irms_{suspect_phase}",
        ]
        if suspect_phase not in prepared_phases:
            result[target_columns] = result[target_columns].astype(float)
            prepared_phases.add(suspect_phase)
        result.loc[index, target_columns] = restored_values
        recovered[suspect_phase] += 1
        stats["total_recovered"] += 1

    return result, stats


def ensure_finite_result(df: pd.DataFrame) -> None:
    """Разрешает полностью пустые строки, но запрещает частичные NaN и inf."""
    blank_rows = df[NUMERIC_COLUMNS].isna().all(axis=1)
    for column in NUMERIC_COLUMNS:
        invalid_mask = ~df[column].map(lambda value: math.isfinite(float(value)))
        invalid_mask &= ~blank_rows
        if invalid_mask.any():
            row_number = int(invalid_mask[invalid_mask].index[0]) + 1
            raise ValueError(
                "Итоговый CSV не записан: обнаружено NaN или inf "
                f"в колонке {column}, строка данных {row_number}."
            )


def print_recovery_stats(path: Path, stats: RecoveryStats) -> None:
    """Выводит краткую статистику восстановления одного входного файла."""
    recovered = stats["recovered"]
    print(f"Файл: {path}")
    print(
        "Восстановлено: "
        f"L1={recovered['L1']}, L2={recovered['L2']}, L3={recovered['L3']}, "
        f"всего={stats['total_recovered']}"
    )
    print(
        "Не восстановлено из-за некорректных или неоднозначных "
        f"данных: {stats['not_recovered']}"
    )
    print(f"Обнаружены пропуски данных, строк: {stats['missing_data_rows']}")


def write_recovery_stats(
    path: Path,
    files: List[Path],
    statistics: List[RecoveryStats],
) -> None:
    """Записывает машинную JSON-статистику в порядке входных файлов."""
    payload = {
        "recovery_enabled": RECOVER_CT_FAILURES,
        "files": [
            {"path": str(file_path), **stats}
            for file_path, stats in zip(files, statistics)
        ],
    }
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")


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
    incomplete_rows = pd.Series(False, index=common_index)
    for df in frames:
        frame_is_finite = df[NUMERIC_COLUMNS].apply(
            lambda column: column.map(lambda value: math.isfinite(float(value)))
        )
        incomplete_rows |= ~frame_is_finite.all(axis=1)

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

    # Если хотя бы один исходный файл содержит неполную строку, сохраняем
    # её timestamp, но не подменяем отсутствующие данные расчётными значениями.
    out.loc[incomplete_rows, NUMERIC_COLUMNS] = math.nan

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


def parse_args(argv: Iterable[str]) -> tuple[List[Path], Path, Path | None]:
    """Разбирает пути четырёх входных CSV, результата и служебной статистики."""
    parser = argparse.ArgumentParser(
        description="Собрать 4 CSV ячеек в один CSV по объекту без изменения структуры колонок."
    )
    parser.add_argument("files", nargs="*", help="4 входных CSV-файла")
    parser.add_argument("--out", "-o", required=False, help="Итоговый CSV-файл")
    parser.add_argument(
        "--stats-out",
        required=False,
        help="Служебный JSON-файл статистики восстановления",
    )
    args = parser.parse_args(list(argv))

    if not args.files and not args.out and not args.stats_out:
        files, output = choose_files_gui()
        return files, output, None

    files = [Path(p) for p in args.files]
    if len(files) != 4:
        parser.error("Нужно передать ровно 4 входных CSV-файла.")
    if not args.out:
        parser.error("Нужно указать --out итоговый_файл.csv")

    stats_output = Path(args.stats_out) if args.stats_out else None
    return files, Path(args.out), stats_output


def main(argv: Iterable[str] | None = None) -> int:
    """Читает файлы, при необходимости восстанавливает данные и пишет результат."""
    try:
        files, output, stats_output = parse_args(sys.argv[1:] if argv is None else argv)
        frames = [read_csv_file(path) for path in files]
        missing_data_counts = [count_missing_data_rows(frame) for frame in frames]

        if RECOVER_CT_FAILURES:
            frames = align_common_timestamps(frames)
            processed_frames = []
            statistics = []
            for path, frame, missing_count in zip(files, frames, missing_data_counts):
                processed_frame, frame_stats = recover_ct_failures(frame)
                frame_stats["missing_data_rows"] = missing_count
                processed_frames.append(processed_frame)
                statistics.append(frame_stats)
                print_recovery_stats(path, frame_stats)
            frames = processed_frames
        else:
            print("Восстановление данных при отказе ТТ отключено")
            statistics = [empty_recovery_stats() for _ in files]
            for frame_stats, missing_count in zip(statistics, missing_data_counts):
                frame_stats["missing_data_rows"] = missing_count

        result = aggregate_frames(frames)
        if RECOVER_CT_FAILURES:
            ensure_finite_result(result)
        write_csv_file(result, output)
        if stats_output is not None:
            write_recovery_stats(stats_output, files, statistics)
        print(f"Готово: {output}")
        print(f"Строк записано: {len(result)}")
        print(f"Период: {result['timestamp'].iloc[0]} ... {result['timestamp'].iloc[-1]}")
        return 0
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
