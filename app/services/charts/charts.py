import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

plt.rcParams["font.family"] = "DejaVu Sans"


def _line_chart(dates: list[str], series: dict[str, list], title: str, ylabel: str) -> bytes:
    x = [datetime.fromisoformat(d) for d in dates]
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=140)
    for label, values in series.items():
        points = [(xi, v) for xi, v in zip(x, values) if v is not None]
        if not points:
            continue
        xs, ys = zip(*points)
        ax.plot(xs, ys, marker="o", markersize=3, linewidth=2, label=label)
    ax.set_title(title, fontsize=13)
    ax.set_ylabel(ylabel)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.grid(alpha=0.25)
    if len(series) > 1:
        ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def weight_chart(history: list[dict]) -> bytes:
    dates = [d["date"] for d in history]
    return _line_chart(dates, {"Вес, кг": [d.get("weight") for d in history]}, "Вес", "кг")


def measurements_chart(history: list[dict]) -> bytes:
    dates = [d["date"] for d in history]
    series = {
        "Талия": [d.get("waist") for d in history],
        "Бёдра": [d.get("hips") for d in history],
        "Живот": [d.get("belly") for d in history],
    }
    return _line_chart(dates, series, "Замеры", "см")


def sleep_chart(history: list[dict]) -> bytes:
    dates = [d["date"] for d in history]
    return _line_chart(dates, {"Сон, ч": [d.get("sleep_hours") for d in history]}, "Сон", "часы")


def mood_energy_stress_chart(history: list[dict]) -> bytes:
    dates = [d["date"] for d in history]
    series = {
        "Настроение": [d.get("mood") for d in history],
        "Энергия": [d.get("energy") for d in history],
        "Стресс": [d.get("stress") for d in history],
    }
    return _line_chart(dates, series, "Настроение / Энергия / Стресс", "1–10")


def work_chart(history: list[dict]) -> bytes:
    dates = [d["date"] for d in history]
    return _line_chart(dates, {"Работа, ч": [d.get("work_hours") for d in history]}, "Рабочие часы", "часы")
