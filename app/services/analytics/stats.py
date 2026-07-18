from statistics import mean
from collections import Counter


def _avg(values: list) -> float | None:
    clean = [v for v in values if v is not None]
    return round(mean(clean), 2) if clean else None


def _delta(values: list) -> float | None:
    clean = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(clean) < 2:
        return None
    return round(clean[-1][1] - clean[0][1], 2)


def weekly_summary(days: list[dict], activities: list[dict]) -> dict:
    """days — daily_log записи за период, отсортированные по дате возрастанию."""
    activity_counts = Counter(a["type"] for a in activities if a.get("type"))
    work_values = [d.get("work_hours") for d in days if d.get("work_hours") is not None]
    return {
        "period_start": days[0]["date"] if days else None,
        "period_end": days[-1]["date"] if days else None,
        "weight_delta": _delta([d.get("weight") for d in days]),
        "waist_delta": _delta([d.get("waist") for d in days]),
        "hips_delta": _delta([d.get("hips") for d in days]),
        "avg_sleep_hours": _avg([d.get("sleep_hours") for d in days]),
        "avg_energy": _avg([d.get("energy") for d in days]),
        "avg_mood": _avg([d.get("mood") for d in days]),
        "avg_stress": _avg([d.get("stress") for d in days]),
        "total_work_hours": sum(work_values) if work_values else None,
        "activity_counts": dict(activity_counts),
        "days_logged": len([d for d in days if any(v is not None for k, v in d.items() if k != "date")]),
    }
