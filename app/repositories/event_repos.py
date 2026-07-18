"""Репозитории для событийных таблиц: activities, illness, medication, context, ai_insights, goals, photos."""
from app.database.engine import session_scope
from app.database.models import Activity, Illness, Medication, DayContext, AIInsight, Goal, Photo


def add_activity(date: str, type: str, minutes: int | None = None, comment: str | None = None):
    with session_scope() as s:
        s.add(Activity(date=date, type=type, minutes=minutes, comment=comment))


def get_activities_range(start_date: str, end_date: str) -> list[dict]:
    with session_scope() as s:
        rows = s.query(Activity).filter(Activity.date >= start_date, Activity.date <= end_date).all()
        return [{"date": r.date, "type": r.type, "minutes": r.minutes, "comment": r.comment} for r in rows]


def add_medication(date: str, drug: str, dosage: str | None = None):
    with session_scope() as s:
        s.add(Medication(date=date, drug=drug, dosage=dosage))


def get_active_medications(as_of_date: str) -> list[dict]:
    with session_scope() as s:
        rows = s.query(Medication).filter(Medication.date <= as_of_date).order_by(Medication.date.desc()).all()
        return [{"date": r.date, "drug": r.drug, "dosage": r.dosage} for r in rows]


def add_illness(start_date: str, diagnosis: str | None = None, symptoms: str | None = None,
                 end_date: str | None = None, comment: str | None = None):
    with session_scope() as s:
        s.add(Illness(start_date=start_date, end_date=end_date, diagnosis=diagnosis,
                       symptoms=symptoms, comment=comment))


def close_open_illness(end_date: str):
    with session_scope() as s:
        row = s.query(Illness).filter(Illness.end_date.is_(None)).order_by(Illness.start_date.desc()).first()
        if row:
            row.end_date = end_date


def get_illness_range(start_date: str, end_date: str) -> list[dict]:
    with session_scope() as s:
        rows = s.query(Illness).filter(
            (Illness.start_date <= end_date) & ((Illness.end_date.is_(None)) | (Illness.end_date >= start_date))
        ).all()
        return [{"start_date": r.start_date, "end_date": r.end_date, "diagnosis": r.diagnosis,
                  "symptoms": r.symptoms, "comment": r.comment} for r in rows]


def add_context(start_date: str, event_type: str, description: str | None = None, end_date: str | None = None):
    with session_scope() as s:
        s.add(DayContext(start_date=start_date, end_date=end_date, event_type=event_type, description=description))


def get_context_range(start_date: str, end_date: str) -> list[dict]:
    with session_scope() as s:
        rows = s.query(DayContext).filter(
            (DayContext.start_date <= end_date) & ((DayContext.end_date.is_(None)) | (DayContext.end_date >= start_date))
        ).all()
        return [{"start_date": r.start_date, "end_date": r.end_date, "event_type": r.event_type,
                  "description": r.description} for r in rows]


def add_insight(date: str, category: str, observation: str, confidence: str = "medium"):
    with session_scope() as s:
        s.add(AIInsight(date=date, category=category, observation=observation, confidence=confidence))


def get_recent_insights(limit: int = 10) -> list[dict]:
    with session_scope() as s:
        rows = s.query(AIInsight).order_by(AIInsight.date.desc()).limit(limit).all()
        return [{"date": r.date, "category": r.category, "observation": r.observation,
                  "confidence": r.confidence} for r in rows]


def get_active_goal() -> dict | None:
    with session_scope() as s:
        row = s.query(Goal).filter(Goal.status == "active").order_by(Goal.start_date.desc()).first()
        if not row:
            return None
        return {"goal": row.goal, "start_date": row.start_date, "end_date": row.end_date, "status": row.status}


def set_goal(goal: str, start_date: str, end_date: str | None = None, status: str = "active"):
    with session_scope() as s:
        s.add(Goal(goal=goal, start_date=start_date, end_date=end_date, status=status))


def add_photo(date: str, kind: str, file_id: str, angle: str | None = None, note: str | None = None):
    with session_scope() as s:
        s.add(Photo(date=date, kind=kind, angle=angle, file_id=file_id, note=note))


def get_last_photo(kind: str, before_date: str, angle: str | None = None) -> dict | None:
    with session_scope() as s:
        q = s.query(Photo).filter(Photo.kind == kind, Photo.date < before_date)
        if angle:
            q = q.filter(Photo.angle == angle)
        row = q.order_by(Photo.date.desc()).first()
        if not row:
            return None
        return {"date": row.date, "kind": row.kind, "angle": row.angle, "file_id": row.file_id, "note": row.note}
