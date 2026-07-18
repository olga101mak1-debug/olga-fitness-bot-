from app.database.engine import session_scope
from app.database.models import User


def get_user() -> dict | None:
    with session_scope() as s:
        row = s.get(User, 1)
        if not row:
            return None
        return {
            "id": row.id, "chat_id": row.chat_id, "name": row.name, "height_cm": row.height_cm,
            "age": row.age, "gender": row.gender, "target_weight_kg": row.target_weight_kg,
            "start_date": row.start_date, "medications": row.medications, "timezone": row.timezone,
            "protein_goal_g": row.protein_goal_g, "calories_goal_kcal": row.calories_goal_kcal,
            "calcium_goal_mg": row.calcium_goal_mg, "fiber_goal_g": row.fiber_goal_g,
        }


def set_chat_id(chat_id: int):
    with session_scope() as s:
        row = s.get(User, 1)
        if row:
            row.chat_id = chat_id
