from __future__ import annotations

# Колонка времени во входных CSV
TIME_COL = "timestamp"

# Колонки, которые никогда не показываем
HIDE_ALWAYS = {"uptime"}

# Группы для нижних панелей
GROUPS = {
    "Мощности (общие)": ["P_total", "S_total", "Q_total"],
    "Токи L1–L3": ["Irms_L1", "Irms_L2", "Irms_L3"],
    "Напряжения фазы": ["Urms_L1", "Urms_L2", "Urms_L3"],
    "Линейные U": ["U_L1_L2", "U_L2_L3", "U_L3_L1"],
    "PF": ["pf_total", "pf_L1", "pf_L2", "pf_L3"],
    "Углы": ["angle_L1_L2", "angle_L2_L3", "angle_L3_L1"],
}

# Что предлагать по умолчанию в верхнем графике
DEFAULT_PRESET = ["P_total", "S_total", "Q_total"]

# Лимиты точек (для прореживания перед отрисовкой)
MAX_POINTS_MAIN = 5000
MAX_POINTS_GROUP = 5000

# Подписи доступных осей для верхнего графика
AXIS_LABELS = {"A1": "A1 (слева)", "A2": "A2 (справа)"}
