import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from app.repositories import user_repo, daily_log_repo, event_repos
from app.services.ai import insight_generator
from app.services import life_service
from app.utils import today_local
from app.config import (
    TIMEZONE, MORNING_HOUR, MORNING_MINUTE, EVENING_HOUR, EVENING_MINUTE,
    WEEKLY_REPORT_WEEKDAY, WEEKLY_REPORT_HOUR, WEEKLY_REPORT_MINUTE,
)

logger = logging.getLogger(__name__)


async def morning_job(bot):
    user = user_repo.get_user()
    if not user or not user.get("chat_id"):
        return
    today = today_local().isoformat()
    row = daily_log_repo.get_by_date(today)
    if row and row.get("weight") is not None:
        text = f"☀️ Доброе утро, {user.get('name', '')}! Как спалось?"
    else:
        text = f"☀️ Доброе утро, {user.get('name', '')}! Вес сегодня?"
    await bot.send_message(user["chat_id"], text)


EVENING_CHECKLIST = (
    "🌙 Как прошёл день?\n\n"
    "Можно кратко затронуть:\n"
    "⚖️ вес (если мерили)\n"
    "😴 сон\n"
    "💼 работа\n"
    "🏋️ тренировка\n"
    "😊 настроение/стресс\n"
    "💧 еда/вода\n"
    "💊 лекарства\n\n"
    "Пиши/говори одним сообщением — что не упомянешь, я потом сама спрошу."
)


async def evening_job(bot):
    user = user_repo.get_user()
    if not user or not user.get("chat_id"):
        return
    await bot.send_message(user["chat_id"], EVENING_CHECKLIST)


async def weekly_job(bot):
    user = user_repo.get_user()
    if not user or not user.get("chat_id"):
        return
    text = await life_service.weekly_report()
    await bot.send_message(user["chat_id"], text)

    history = daily_log_repo.get_history(limit=60)
    if len(history) >= 7:
        insights = await insight_generator.generate_insights(history)
        today = today_local().isoformat()
        for ins in insights:
            event_repos.add_insight(today, ins.get("category", "другое"), ins.get("observation", ""),
                                     ins.get("confidence", "medium"))


def start_scheduler(bot) -> AsyncIOScheduler:
    tz = pytz.timezone(TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)

    scheduler.add_job(morning_job, CronTrigger(hour=MORNING_HOUR, minute=MORNING_MINUTE, timezone=tz),
                       args=[bot], id="morning")
    scheduler.add_job(evening_job, CronTrigger(hour=EVENING_HOUR, minute=EVENING_MINUTE, timezone=tz),
                       args=[bot], id="evening")
    scheduler.add_job(weekly_job, CronTrigger(day_of_week=WEEKLY_REPORT_WEEKDAY, hour=WEEKLY_REPORT_HOUR,
                                               minute=WEEKLY_REPORT_MINUTE, timezone=tz),
                       args=[bot], id="weekly")

    scheduler.start()
    logger.info("Scheduler started (tz=%s)", TIMEZONE)
    return scheduler
