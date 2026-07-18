from app.database.engine import session_scope
from app.database.models import Meal
from app.utils import now_local

MEAL_FIELDS = ["description", "calories", "protein", "fat", "carbs", "calcium", "fiber"]


def _to_dict(row: Meal) -> dict:
    return {"id": row.id, "date": row.date, "created_at": row.created_at,
            "photo_unique_id": row.photo_unique_id,
            **{f: getattr(row, f) for f in MEAL_FIELDS}}


def add_meal(date: str, description: str, calories: float = 0, protein: float = 0,
             fat: float = 0, carbs: float = 0, calcium: float = 0, fiber: float = 0,
             photo_unique_id: str | None = None) -> int:
    with session_scope() as s:
        meal = Meal(date=date, description=description, calories=calories, protein=protein,
                     fat=fat, carbs=carbs, calcium=calcium, fiber=fiber,
                     created_at=now_local().isoformat(timespec="seconds"), photo_unique_id=photo_unique_id)
        s.add(meal)
        s.flush()
        return meal.id


def update_meal(meal_id: int, **fields):
    fields = {k: v for k, v in fields.items() if k in MEAL_FIELDS and v is not None}
    with session_scope() as s:
        row = s.get(Meal, meal_id)
        if row:
            for k, v in fields.items():
                setattr(row, k, v)


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
                  "fat": m.fat, "carbs": m.carbs} for m in meals]
