from __future__ import annotations

# Колонка времени во входных CSV
TIME_COL = "timestamp"

# Колонки, которые никогда не показываем
HIDE_ALWAYS = {"uptime"}

# Группы (по имени колонок в CSV)
GROUPS = {
    "P_total/S_total/Q_total": ["P_total", "S_total", "Q_total"],
    "Irms_L1–L3": ["Irms_L1", "Irms_L2", "Irms_L3"],
    "Urms_L1–L3": ["Urms_L1", "Urms_L2", "Urms_L3"],
    "U_L12/L23/L31": ["U_L1_L2", "U_L2_L3", "U_L3_L1"],
    "PF_total/L1–L3": ["pf_total", "pf_L1", "pf_L2", "pf_L3"],
    "Angles": ["angle_L1_L2", "angle_L2_L3", "angle_L3_L1"],
}

# Что показывать на сводном графике по умолчанию
DEFAULT_PRESET = ["P_total", "S_total", "Q_total"]

# Лимиты точек (прореживание)
MAX_POINTS_MAIN = 5000
MAX_POINTS_GROUP = 5000

# Фиксированная высота всех графиков (px)
PLOT_HEIGHT = 500

# Маппинг меток осей (используется ui.axis_selector)
AXIS_LABELS = {
    "A1": "A1 — базовая шкала",
    "A2": "A2 — отдельная шкала слева",
}
