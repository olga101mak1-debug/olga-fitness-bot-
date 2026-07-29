"""Память диалога за день — чтобы бот не отвечал на вопрос, который уже закрыт, и не повторялся."""
from app.database.engine import session_scope
from app.database.models import ChatMessage
from app.utils import now_local, today_local

MAX_STORED_CHARS = 700


def add(role: str, text: str, date: str | None = None):
    """role: 'user' — сообщение пользователя, 'bot' — ответ бота."""
    text = (text or "").strip()
    if not text:
        return
    if len(text) > MAX_STORED_CHARS:
        text = text[:MAX_STORED_CHARS] + "…"
    with session_scope() as s:
        s.add(ChatMessage(
            date=date or today_local().isoformat(),
            created_at=now_local().isoformat(timespec="seconds"),
            role=role,
            text=text,
        ))


def get_today(date: str, limit: int = 20) -> list[dict]:
    """Последние сообщения за день, от старых к новым."""
    with session_scope() as s:
        rows = (
            s.query(ChatMessage)
            .filter(ChatMessage.date == date)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
            .all()
        )
        return [{"role": r.role, "created_at": r.created_at, "text": r.text} for r in reversed(rows)]
