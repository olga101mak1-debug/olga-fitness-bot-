from app.database.engine import session_scope
from app.database.models import DailyLog


def get_by_date(date: str) -> dict | None:
    with session_scope() as s:
        row = s.get(DailyLog, date)
        if not row:
            return None
        return {"date": row.date, **{f: getattr(row, f) for f in DailyLog.FIELDS}}


def upsert(date: str, **fields) -> dict:
    fields = {k: v for k, v in fields.items() if k in DailyLog.FIELDS and v is not None}
    with session_scope() as s:
        row = s.get(DailyLog, date)
        if row is None:
            row = DailyLog(date=date, **fields)
            s.add(row)
        else:
            for k, v in fields.items():
                setattr(row, k, v)
        s.flush()
        return {"date": row.date, **{f: getattr(row, f) for f in DailyLog.FIELDS}}


def get_first_entry() -> dict | None:
    with session_scope() as s:
        row = (
            s.query(DailyLog)
            .filter(DailyLog.weight.isnot(None))
            .order_by(DailyLog.date.asc())
            .first()
        )
        if not row:
            return None
        return {"date": row.date, "weight": row.weight, "waist": row.waist, "hips": row.hips, "neck": row.neck}


def get_history(limit: int = 90) -> list[dict]:
    with session_scope() as s:
        rows = s.query(DailyLog).order_by(DailyLog.date.desc()).limit(limit).all()
        return [{"date": r.date, **{f: getattr(r, f) for f in DailyLog.FIELDS}} for r in reversed(rows)]


def get_range(start_date: str, end_date: str) -> list[dict]:
    with session_scope() as s:
        rows = (
            s.query(DailyLog)
            .filter(DailyLog.date >= start_date, DailyLog.date <= end_date)
            .order_by(DailyLog.date.asc())
            .all()
        )
        return [{"date": r.date, **{f: getattr(r, f) for f in DailyLog.FIELDS}} for r in rows]
