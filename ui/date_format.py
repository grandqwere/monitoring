from __future__ import annotations

from datetime import date, datetime


DATE_INPUT_FORMAT = "DD.MM.YYYY"


def format_date_ru(value: date | datetime | None) -> str:
    """Форматирует дату для отображения в интерфейсе."""
    if value is None:
        return ""
    try:
        return value.strftime("%d.%m.%Y")
    except Exception:
        return ""


def format_datetime_ru(value: date | datetime | None) -> str:
    """Форматирует дату и время для отображения в интерфейсе."""
    if value is None:
        return ""
    try:
        return value.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return ""


def format_date_hour_ru(value: date | datetime | None, hour: int) -> str:
    """Форматирует дату и час для сообщений интерфейса."""
    day = format_date_ru(value)
    if not day:
        return ""
    return f"{day} {int(hour):02d}:00"


def format_date_minute_ru(value: date | datetime | None, hour: int, minute: int) -> str:
    """Форматирует дату, час и минуту для сообщений интерфейса."""
    day = format_date_ru(value)
    if not day:
        return ""
    return f"{day} {int(hour):02d}:{int(minute):02d}"
