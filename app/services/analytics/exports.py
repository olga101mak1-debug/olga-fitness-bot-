"""Выгрузка первички в таблицы: всё, что накоплено в базе, в открытом виде.

CSV пишется с BOM (utf-8-sig) — иначе Excel на Windows показывает кириллицу кракозябрами.
Разделитель — точка с запятой, потому что в русской локали Excel понимает именно его.
"""
import csv
import io

DAY_COLUMNS = [
    ("date", "Дата"), ("weight", "Вес, кг"), ("waist", "Талия, см"), ("belly", "Живот, см"),
    ("hips", "Бёдра, см"), ("neck", "Шея, см"), ("chest", "Грудь, см"),
    ("calories", "Калории"), ("protein", "Белок, г"), ("fat", "Жиры, г"), ("carbs", "Углеводы, г"),
    ("meals_count", "Приёмов пищи"), ("training", "Активность"),
    ("sleep_hours", "Сон, ч"), ("sleep_quality", "Качество сна"), ("energy", "Энергия"),
    ("mood", "Настроение"), ("stress", "Стресс"), ("work_hours", "Работа, ч"),
    ("work_load", "Нагрузка"), ("steps", "Шаги"), ("water_liters", "Вода, л"),
    ("alcohol", "Алкоголь"), ("nutrition_event", "Событие в питании"), ("comment", "Заметка"),
]

MEAL_COLUMNS = [
    ("date", "Дата"), ("meal_type", "Приём пищи"), ("eaten_at", "Время еды"),
    ("description", "Блюдо"), ("calories", "Калории"), ("protein", "Белок, г"),
    ("fat", "Жиры, г"), ("carbs", "Углеводы, г"), ("fiber", "Клетчатка, г"),
    ("calcium", "Кальций, мг"), ("created_at", "Записано"),
]


def _write(rows: list[dict], columns: list[tuple[str, str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow([title for _, title in columns])
    for row in rows:
        writer.writerow(["" if row.get(key) is None else row.get(key) for key, _ in columns])
    return buf.getvalue().encode("utf-8-sig")


def days_csv(history: list[dict], meal_days: list[dict], activities: list[dict]) -> bytes:
    """Один день — одна строка: показатели, итоги по еде и тренировки вместе."""
    meals_by_date = {m["date"]: m for m in meal_days}
    acts_by_date: dict[str, list[str]] = {}
    for act in activities:
        label = act.get("type") or "тренировка"
        if act.get("minutes"):
            label += f" {act['minutes']}м"
        acts_by_date.setdefault(act.get("date"), []).append(label)

    rows = []
    for day in history:
        food = meals_by_date.get(day["date"]) or {}
        row = dict(day)
        row["calories"] = round(food["calories"]) if food.get("calories") is not None else None
        row["protein"] = round(food["protein"]) if food.get("protein") is not None else None
        row["fat"] = round(food["fat"]) if food.get("fat") is not None else None
        row["carbs"] = round(food["carbs"]) if food.get("carbs") is not None else None
        row["meals_count"] = food.get("count")
        # Тренировки из отдельной таблицы важнее строки training в дневнике: она заполняется редко.
        acts = acts_by_date.get(day["date"])
        if acts:
            row["training"] = ", ".join(acts)
        rows.append(row)
    return _write(rows, DAY_COLUMNS)


def meals_csv(meals: list[dict]) -> bytes:
    """Каждый приём пищи отдельной строкой — первичка, из которой считаются все итоги."""
    return _write(meals, MEAL_COLUMNS)
