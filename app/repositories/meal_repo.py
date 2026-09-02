from app.database.engine import session_scope
from app.database.models import Meal
from app.utils import now_local

MEAL_FIELDS = ["description", "calories", "protein", "fat", "carbs", "calcium", "fiber",
               "meal_type", "eaten_at"]

MEAL_TYPES = ["завтрак", "обед", "ужин", "перекус"]

# Границы приёмов пищи по времени — запасной вариант, когда тип не назван словами
# (например, еда пришла фотографией без подписи).
_MEAL_BY_HOUR = ((5, "завтрак"), (11, "обед"), (16, "ужин"), (22, "перекус"))


def guess_meal_type(hhmm: str | None = None) -> str:
    """Определить приём пищи по времени. Ночная еда считается перекусом."""
    try:
        hour = int((hhmm or now_local().strftime("%H:%M")).split(":")[0])
    except (ValueError, AttributeError, IndexError):
        hour = now_local().hour
    result = "перекус"
    for start, name in _MEAL_BY_HOUR:
        if hour >= start:
            result = name
    return result


def _to_dict(row: Meal) -> dict:
    return {"id": row.id, "date": row.date, "created_at": row.created_at,
            "photo_unique_id": row.photo_unique_id,
            **{f: getattr(row, f) for f in MEAL_FIELDS}}


def add_meal(date: str, description: str, calories: float = 0, protein: float = 0,
             fat: float = 0, carbs: float = 0, calcium: float = 0, fiber: float = 0,
             photo_unique_id: str | None = None, meal_type: str | None = None,
             eaten_at: str | None = None) -> int:
    now = now_local()
    if meal_type not in MEAL_TYPES:
        meal_type = guess_meal_type(eaten_at)
    # eaten_at заполняем ТОЛЬКО когда время еды известно со слов пользователя.
    # Подставлять сюда текущее время нельзя: она описывает завтрак вечером, и тогда
    # у завтрака оказывалось время 17:58. Момент записи и так хранится в created_at.
    with session_scope() as s:
        meal = Meal(date=date, description=description, calories=calories, protein=protein,
                     fat=fat, carbs=carbs, calcium=calcium, fiber=fiber,
                     meal_type=meal_type, eaten_at=eaten_at or now.strftime("%H:%M"),
                     created_at=now.isoformat(timespec="seconds"), photo_unique_id=photo_unique_id)
        s.add(meal)
        s.flush()
        return meal.id


def get_totals_by_meal_type(date: str) -> list[dict]:
    """Итоги дня в разбивке по приёмам пищи — вместо одной общей суммы за день."""
    order = {name: i for i, name in enumerate(MEAL_TYPES)}
    grouped: dict[str, dict] = {}
    with session_scope() as s:
        rows = s.query(Meal).filter(Meal.date == date).order_by(Meal.id).all()
        for m in rows:
            key = m.meal_type if m.meal_type in MEAL_TYPES else "перекус"
            block = grouped.setdefault(key, {"meal_type": key, "calories": 0.0, "protein": 0.0,
                                              "count": 0, "dishes": [], "first_time": m.eaten_at})
            block["calories"] += m.calories or 0
            block["protein"] += m.protein or 0
            block["count"] += 1
            block["dishes"].append(m.description or "без названия")
            if m.eaten_at and (not block["first_time"] or m.eaten_at < block["first_time"]):
                block["first_time"] = m.eaten_at
    return sorted(grouped.values(), key=lambda b: order.get(b["meal_type"], 99))


def update_meal(meal_id: int, **fields):
    fields = {k: v for k, v in fields.items() if k in MEAL_FIELDS and v is not None}
    with session_scope() as s:
        row = s.get(Meal, meal_id)
        if row:
            for k, v in fields.items():
                setattr(row, k, v)


def delete_meal(meal_id: int) -> dict | None:
    """Удалить приём пищи. Возвращает удалённую запись, чтобы можно было честно отчитаться."""
    with session_scope() as s:
        row = s.get(Meal, meal_id)
        if not row:
            return None
        data = _to_dict(row)
        s.delete(row)
        return data


def move_meal(meal_id: int, new_date: str) -> dict | None:
    """Перенести приём пищи на другую дату (например, «это я ела вчера»)."""
    with session_scope() as s:
        row = s.get(Meal, meal_id)
        if not row:
            return None
        row.date = new_date
        s.flush()
        return _to_dict(row)


def get_meals_full(date: str) -> list[dict]:
    """Полные записи с id — нужны там, где записи надо править, а не только показывать."""
    with session_scope() as s:
        rows = s.query(Meal).filter(Meal.date == date).order_by(Meal.id).all()
        return [_to_dict(r) for r in rows]


def get_meal_by_photo(date: str, photo_unique_id: str | None) -> dict | None:
    if not photo_unique_id:
        return None
    with session_scope() as s:
        row = (
            s.query(Meal)
            .filter(Meal.date == date, Meal.photo_unique_id == photo_unique_id)
            .order_by(Meal.id.desc())
            .first()
        )
        return _to_dict(row) if row else None


def get_meal_by_id(meal_id: int) -> dict | None:
    with session_scope() as s:
        row = s.get(Meal, meal_id)
        return _to_dict(row) if row else None


def get_latest_meal(date: str) -> dict | None:
    with session_scope() as s:
        row = s.query(Meal).filter(Meal.date == date).order_by(Meal.id.desc()).first()
        return _to_dict(row) if row else None


def get_today_totals(date: str) -> dict:
    with session_scope() as s:
        meals = s.query(Meal).filter(Meal.date == date).all()
        return {
            "calories": sum(m.calories or 0 for m in meals),
            "protein": sum(m.protein or 0 for m in meals),
            "fat": sum(m.fat or 0 for m in meals),
            "carbs": sum(m.carbs or 0 for m in meals),
            "calcium": sum(m.calcium or 0 for m in meals),
            "fiber": sum(m.fiber or 0 for m in meals),
            "count": len(meals),
        }


def get_today_meals(date: str) -> list[dict]:
    with session_scope() as s:
        meals = s.query(Meal).filter(Meal.date == date).order_by(Meal.created_at).all()
        return [{"description": m.description, "calories": m.calories, "protein": m.protein,
                  "fat": m.fat, "carbs": m.carbs,
                  "приём": m.meal_type, "время": m.eaten_at} for m in meals]


def get_daily_totals_range(start_date: str, end_date: str) -> list[dict]:
    """Итоги по еде по дням за период — основа для аналитики питания и графиков.

    Раньше калории существовали только «за сегодня», поэтому бот не мог ответить
    ни на один вопрос про питание за прошлые дни.
    """
    by_date: dict[str, dict] = {}
    # Агрегируем внутри сессии: после её закрытия объекты Meal отсоединяются
    # и обращение к их полям падает с DetachedInstanceError.
    with session_scope() as s:
        rows = (
            s.query(Meal)
            .filter(Meal.date >= start_date, Meal.date <= end_date)
            .order_by(Meal.date)
            .all()
        )
        for m in rows:
            day = by_date.setdefault(m.date, {"date": m.date, "calories": 0.0, "protein": 0.0,
                                               "fat": 0.0, "carbs": 0.0, "calcium": 0.0,
                                               "fiber": 0.0, "count": 0})
            day["calories"] += m.calories or 0
            day["protein"] += m.protein or 0
            day["fat"] += m.fat or 0
            day["carbs"] += m.carbs or 0
            day["calcium"] += m.calcium or 0
            day["fiber"] += m.fiber or 0
            day["count"] += 1
    return [by_date[d] for d in sorted(by_date)]


def get_meals_range(start_date: str, end_date: str) -> list[dict]:
    with session_scope() as s:
        rows = (
            s.query(Meal)
            .filter(Meal.date >= start_date, Meal.date <= end_date)
            .order_by(Meal.date, Meal.id)
            .all()
        )
        return [_to_dict(r) for r in rows]
