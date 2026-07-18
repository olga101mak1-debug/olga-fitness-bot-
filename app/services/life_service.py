from datetime import timedelta, datetime

from app.repositories import daily_log_repo, event_repos, user_repo, meal_repo
from app.services.ai import parser as ai_parser
from app.services.ai import coach as ai_coach
from app.services.ai import weekly_analyst
from app.services.analytics import stats
from app.utils import today_local, now_local

DAILY_LOG_KEYS = {
    "weight", "waist", "belly", "hips", "neck", "chest", "sleep_hours", "sleep_quality",
    "energy", "mood", "stress", "work_hours", "work_load", "steps", "water_liters",
    "protein_g", "alcohol", "nutrition_event", "training", "comment",
}

MEAL_CORRECTION_WINDOW_MINUTES = 20


async def _try_meal_correction(text: str, today: str) -> str | None:
    """Если недавно был записан приём пищи и сообщение похоже на поправку к нему — обновить его.
    Возвращает текст ответа, если это была поправка, иначе None."""
    recent_meal = meal_repo.get_latest_meal(today)
    if not recent_meal:
        return None
    try:
        meal_time = datetime.fromisoformat(recent_meal["created_at"])
    except (ValueError, TypeError):
        return None
    if (now_local() - meal_time).total_seconds() > MEAL_CORRECTION_WINDOW_MINUTES * 60:
        return None

    correction = await ai_parser.detect_meal_correction(text, recent_meal)
    if not correction.get("is_correction"):
        return None

    meal_repo.update_meal(
        recent_meal["id"],
        description=correction.get("dish"), calories=correction.get("calories"),
        protein=correction.get("protein"), fat=correction.get("fat"),
        carbs=correction.get("carbs"), calcium=correction.get("calcium"), fiber=correction.get("fiber"),
    )
    updated_meal = meal_repo.get_latest_meal(today) or recent_meal
    totals = meal_repo.get_today_totals(today)
    user = user_repo.get_user() or {}
    line = f"Обновила: {updated_meal['description']} — {updated_meal['calories']:.0f} ккал, {updated_meal['protein']:.0f}г белка."
    totals_line = f"Итого за день: {totals['calories']:.0f}"
    if user.get("calories_goal_kcal"):
        totals_line += f"/{user['calories_goal_kcal']:.0f}"
    totals_line += f" ккал, белок {totals['protein']:.0f}"
    if user.get("protein_goal_g"):
        totals_line += f"/{user['protein_goal_g']:.0f}"
    totals_line += "г"
    return f"{line}\n{totals_line}"


async def process_message(text: str) -> str:
    today = today_local().isoformat()

    correction_reply = await _try_meal_correction(text, today)
    if correction_reply:
        return correction_reply

    parsed = await ai_parser.parse(text)

    daily_fields = {k: v for k, v in parsed.items() if k in DAILY_LOG_KEYS}
    daily_log_repo.upsert(today, **daily_fields)

    for act in parsed.get("activities") or []:
        event_repos.add_activity(today, act.get("type"), act.get("minutes"), act.get("comment"))

    for med in parsed.get("medications") or []:
        event_repos.add_medication(today, med.get("drug"), med.get("dosage"))

    for ctx in parsed.get("context_tags") or []:
        event_repos.add_context(today, ctx.get("event_type"), ctx.get("description"))

    illness = parsed.get("illness")
    if illness and (illness.get("diagnosis") or illness.get("symptoms")):
        event_repos.add_illness(today, illness.get("diagnosis"), illness.get("symptoms"))

    if parsed.get("illness_resolved"):
        event_repos.close_open_illness(today)

    today_state = daily_log_repo.get_by_date(today) or {"date": today}
    history = daily_log_repo.get_history(limit=30)
    baseline = daily_log_repo.get_first_entry()
    goal = event_repos.get_active_goal()
    insights = event_repos.get_recent_insights(limit=5)
    user = user_repo.get_user() or {}

    reply = await ai_coach.generate_reply(today_state, history, goal, insights, user, text, baseline)
    return reply


def today_summary() -> str:
    today = today_local().isoformat()
    row = daily_log_repo.get_by_date(today)
    meal_totals = meal_repo.get_today_totals(today)
    has_daily = row and any(v is not None for k, v in row.items() if k != "date")
    has_meals = meal_totals["count"] > 0

    if not has_daily and not has_meals:
        return "За сегодня пока ничего не записано — просто напиши или скажи, как проходит день."

    lines = [f"📝 Сегодня, {today}:"]
    if has_daily:
        labels = {
            "weight": "Вес", "waist": "Талия", "belly": "Живот", "hips": "Бёдра", "neck": "Шея", "chest": "Грудь",
            "sleep_hours": "Сон, ч", "sleep_quality": "Качество сна", "energy": "Энергия", "mood": "Настроение",
            "stress": "Стресс", "work_hours": "Работа, ч", "work_load": "Нагрузка", "steps": "Шаги",
            "water_liters": "Вода, л", "protein_g": "Белок, г", "alcohol": "Алкоголь",
            "nutrition_event": "Событие в питании", "training": "Активность", "comment": "Заметка",
        }
        for key, label in labels.items():
            val = row.get(key)
            if val is not None:
                lines.append(f"• {label}: {val}")
    if has_meals:
        user = user_repo.get_user() or {}
        cal_line = f"• Еда: {meal_totals['calories']:.0f}"
        if user.get("calories_goal_kcal"):
            cal_line += f"/{user['calories_goal_kcal']:.0f}"
        cal_line += f" ккал, белок {meal_totals['protein']:.0f}"
        if user.get("protein_goal_g"):
            cal_line += f"/{user['protein_goal_g']:.0f}"
        cal_line += f"г ({meal_totals['count']} приёмов пищи)"
        lines.append(cal_line)
    return "\n".join(lines)


async def weekly_report() -> str:
    today = today_local()
    start = (today - timedelta(days=6)).isoformat()
    end = today.isoformat()
    days = daily_log_repo.get_range(start, end)
    activities = event_repos.get_activities_range(start, end)
    summary = stats.weekly_summary(days, activities)
    user = user_repo.get_user() or {}
    text = await weekly_analyst.generate_weekly_report(summary, user)

    lines = [f"📅 Итог недели {start} — {end}"]
    if summary["weight_delta"] is not None:
        lines.append(f"⚖️ Вес: {summary['weight_delta']:+.1f} кг")
    if summary["waist_delta"] is not None:
        lines.append(f"📏 Талия: {summary['waist_delta']:+.1f} см")
    if summary["avg_sleep_hours"] is not None:
        lines.append(f"😴 Средний сон: {summary['avg_sleep_hours']:.1f} ч")
    if summary["total_work_hours"] is not None:
        lines.append(f"💼 Работа: {summary['total_work_hours']:.0f} ч")
    if summary["avg_stress"] is not None:
        lines.append(f"😰 Средний стресс: {summary['avg_stress']:.1f}/10")
    for act_type, count in summary["activity_counts"].items():
        lines.append(f"🏃 {act_type}: {count}")
    lines.append("")
    lines.append(text)
    return "\n".join(lines)
