from datetime import date, datetime
import pytz
from app.config import TIMEZONE


def today_local() -> date:
    """Текущая дата в настроенном часовом поясе пользователя (не поясе сервера)."""
    return now_local().date()


def now_local() -> datetime:
    """Текущее время в настроенном часовом поясе пользователя (не поясе сервера)."""
    return datetime.now(pytz.timezone(TIMEZONE))
