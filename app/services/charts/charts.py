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


def weight_chart(history: list[dict], user: dict | None = None) -> bytes:
    """Вес с линией цели и линией тренда — иначе по точкам не видно, куда всё идёт."""
    points = [(datetime.fromisoformat(d["date"]), d["weight"])
              for d in history if d.get("weight") is not None]
    if not points:
        return _line_chart([d["date"] for d in history], {"Вес, кг": []}, "Вес", "кг")

    xs, ys = zip(*points)
    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=140)
    ax.plot(xs, ys, marker="o", markersize=3.5, linewidth=1.8, color="#2563eb", label="Вес, кг")

    target = (user or {}).get("target_weight_kg")
    if target:
        ax.axhline(target, color="#16a34a", linestyle="--", linewidth=1.4,
                   label=f"Цель {target:g} кг")

    # Тренд по последним 30 замерам: одна прямая честнее, чем глаз по зубцам.
    tail = points[-30:]
    if len(tail) >= 3:
        base = tail[0][0].toordinal()
        tx = [p[0].toordinal() - base for p in tail]
        ty = [p[1] for p in tail]
        mx, my = sum(tx) / len(tx), sum(ty) / len(ty)
        var = sum((x - mx) ** 2 for x in tx)
        if var:
            slope = sum((x - mx) * (y - my) for x, y in zip(tx, ty)) / var
            ax.plot([p[0] for p in tail], [my + slope * (x - mx) for x in tx],
                    color="#dc2626", linewidth=1.6, linestyle=":",
                    label=f"Тренд {slope * 7:+.2f} кг/нед")

    ax.set_title("Вес", fontsize=13)
    ax.set_ylabel("кг")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9)
    fig.autofmt_xdate()
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def nutrition_chart(meal_days: list[dict], user: dict | None = None) -> bytes:
    """Калории и белок по дням против норм. Питания на графиках не было вообще."""
    if not meal_days:
        raise ValueError("нет данных о питании")
    xs = [datetime.fromisoformat(d["date"]) for d in meal_days]
    cals = [d.get("calories") or 0 for d in meal_days]
    prots = [d.get("protein") or 0 for d in meal_days]
    goals = user or {}

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6.4), dpi=140, sharex=True)
    ax1.bar(xs, cals, width=0.7, color="#f59e0b", label="Калории")
    if goals.get("calories_goal_kcal"):
        ax1.axhline(goals["calories_goal_kcal"], color="#16a34a", linestyle="--", linewidth=1.4,
                    label=f"Норма {goals['calories_goal_kcal']:.0f}")
    ax1.set_ylabel("ккал")
    ax1.set_title("Питание по дням (только дни, за которые еда записана)", fontsize=12)
    ax1.grid(alpha=0.2, axis="y")
    ax1.legend(fontsize=9)

    ax2.bar(xs, prots, width=0.7, color="#8b5cf6", label="Белок")
    if goals.get("protein_goal_g"):
        ax2.axhline(goals["protein_goal_g"], color="#16a34a", linestyle="--", linewidth=1.4,
                    label=f"Норма {goals['protein_goal_g']:.0f} г")
    ax2.set_ylabel("г белка")
    ax2.grid(alpha=0.2, axis="y")
    ax2.legend(fontsize=9)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))

    fig.autofmt_xdate()
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


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
