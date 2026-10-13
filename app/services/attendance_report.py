"""Turns raw attendance counts into percentages and warning flags (no database needed)."""
from typing import Optional

from app.validation import attendance_flag, attendance_percentage

FLAG_LABELS = {
    "ok": "OK",
    "below_threshold": "Below threshold (warning)",
    "no_data": "No sessions yet",
}


def build_attendance_report(rows: list, threshold: float) -> list:
    """rows need 'attended' and 'total_held'. Adds 'percentage' (None if no sessions) and 'flag'."""
    report = []
    for row in rows:
        pct = attendance_percentage(row["attended"], row["total_held"])
        report.append({**row, "percentage": pct, "flag": attendance_flag(pct, threshold)})
    return report


def summarize_report(report: list) -> dict:
    with_data = [r["percentage"] for r in report if r["percentage"] is not None]
    average: Optional[float] = sum(with_data) / len(with_data) if with_data else None
    return {
        "students": len(report),
        "students_with_data": len(with_data),
        "average_percentage": average,
        "below_threshold": sum(1 for r in report if r["flag"] == "below_threshold"),
    }
