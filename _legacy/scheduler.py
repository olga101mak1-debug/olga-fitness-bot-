import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import database as db
import claude_ai as ai
from config import USER, TIMEZONE, MORNING_HOUR, EVENING_HOUR, MIDDAY_HOUR

VN_TZ = pytz.timezone(TIMEZONE)
logger = logging.getLogger(__name__)


async def morning_message(bot, chat_id: int):
    import datetime as dt
    log = await db.get_today_log()
    sleep = log.get("sleep")

    if sleep and sleep >= 7:
        sleep_text = f"Спала {sleep}ч — хорошо 💪"
    elif sleep:
        sleep_text = f"Спала {sleep}ч — маловато. Кортизол растёт → жир в талии задерживается."
    else:
        sleep_text = "Запиши сон вчера: /sleep 7.5"

    # Подсказка по тренировке в зависимости от дня недели
    weekday = dt.datetime.now(VN_TZ).weekday()  # 0=пн, 1=вт, ...
    # Силовые: пн/ср/пт, Бадминтон: вт/чт, Плавание: сб
    workout_hints = {
        0: "💪 Сегодня понедельник — силовая тренировка по плану. Не забудь /workout силовая после",
        1: "🏸 Сегодня вторник — бадминтон по плану. /workout бадминтон после игры",
        2: "💪 Сегодня среда — силовая тренировка по плану",
        3: "🏸 Сегодня четверг — бадминтон по плану",
        4: "💪 Сегодня пятница — силовая тренировка по плану",
        5: "🏊 Сегодня суббота — отличный день для плавания",
        6: "😴 Воскресенье — день отдыха и восстановления",
    }
    workout_hint = workout_hints.get(weekday, "")

    text = (
        f"☀️ Доброе утро, {USER['name']}!\n\n"
        f"{sleep_text}\n\n"
        f"⚖️ Взвесься и запиши: /weight 84.5\n\n"
        f"📋 Цели на сегодня:\n"
        f"🥩 Белок: {USER['protein_goal_g']}г\n"
        f"🔥 Калории: {USER['calories_goal_kcal']} ккал\n"
        f"🦴 Кальций: {USER['calcium_goal_mg']} мг (3 порции молочки/рыбы)\n"
        f"🌿 Клетчатка: {USER['fiber_goal_g']}г (овощи в каждый приём)\n"
        f"👟 Шаги: {USER['steps_goal']}\n"
        f"💊 Омега-3 с едой (не натощак)\n\n"
        f"{workout_hint}\n\n"
        f"📸 Фото или описание каждого приёма пищи — считаю в реальном времени 👀"
    )
    await bot.send_message(chat_id, text)


def _daily_needs_text(totals: dict, log: dict) -> str:
    """Что нужно добрать — локальный расчёт без API"""
    needs = []

    protein_left = USER["protein_goal_g"] - totals["protein"]
    if protein_left > 15:
        if protein_left > 70:
            hint = "150–200г куриной грудки + пачка творога"
        elif protein_left > 40:
            hint = "150г куриной грудки или пачка творога"
        elif protein_left > 20:
            hint = "3 яйца или стакан кефира + сыр"
        else:
            hint = "2 яйца или 100г рыбы"
        needs.append(f"🥩 Белок +{protein_left:.0f}г → {hint}")

    calcium_left = USER.get("calcium_goal_mg", 1200) - totals.get("calcium", 0)
    if calcium_left > 400:
        needs.append("🦴 Кальций: 2 порции молочки или рыбы (кефир, тофу, сардины)")
    elif calcium_left > 150:
        needs.append("🦴 Кальций: стакан кефира или 30г твёрдого сыра")

    if not log.get("omega3"):
        needs.append("💊 Омега-3: прими капсулу с едой (не натощак!)")

    fiber_left = USER.get("fiber_goal_g", 28) - totals.get("fiber", 0)
    if fiber_left > 8:
        needs.append(f"🌿 Клетчатка +{fiber_left:.0f}г: добавь овощи к обеду и ужину")

    if not needs:
        return "✅ Все нормы дня идут хорошо!"
    return "💡 До конца дня:\n" + "\n".join(f"• {n}" for n in needs)


async def midday_check(bot, chat_id: int):
    totals = await db.get_today_totals()
    log    = await db.get_today_log()

    protein_pct = totals["protein"] / USER["protein_goal_g"] * 100
    calcium_pct = totals.get("calcium", 0) / USER.get("calcium_goal_mg", 1200) * 100
    cal_pct     = totals["calories"] / USER["calories_goal_kcal"] * 100

    issues = []
    if protein_pct < 25:
        issues.append(f"🥩 Белок: всего {totals['protein']:.0f}г из {USER['protein_goal_g']}г — к обеду нужно минимум 30%")
    if calcium_pct < 15:
        issues.append("🦴 Кальций почти нулевой — добавь молочку или рыбу к обеду")
    if cal_pct < 20:
        issues.append(f"🔥 Калорий мало ({totals['calories']:.0f}) — не пропускай обед на Оземпике!")

    if not issues:
        return  # Всё норм, не отвлекаем

    needs = _daily_needs_text(totals, log)
    text = "⏰ Дневной чекин\n\n" + "\n".join(issues) + f"\n\n{needs}"
    await bot.send_message(chat_id, text)


async def evening_summary(bot, chat_id: int):
    totals, log = await db.get_today_totals(), await db.get_today_log()

    summary = await ai.generate_evening_summary(
        totals, log,
        USER["protein_goal_g"],
        USER["calories_goal_kcal"]
    )

    protein_left = USER["protein_goal_g"] - totals["protein"]

    text = f"🌙 Итог дня\n\n{summary}\n\n"

    if protein_left > 15:
        suggestion = await ai.get_protein_suggestion(totals["protein"], USER["protein_goal_g"])
        text += f"⚠️ Нужно добрать {protein_left:.0f}г белка:\n{suggestion}\n\n"

    if not log.get("omega3"):
        text += "💊 Омега-3 сегодня не принята\n"
    if not log.get("sleep"):
        text += "😴 Запиши сон утром: /sleep [часы]\n"
    if not log.get("steps"):
        text += "👟 Не забудь записать шаги: /steps [число]\n"

    await bot.send_message(chat_id, text)


async def weekly_reminder(bot, chat_id: int):
    await db.set_setting("weekly_pending", "1")

    last = await db.get_last_weight()
    if last and last.get("weight"):
        weight_line = f"Последний вес: {last['weight']} кг"
        if last.get("waist"):
            weight_line += f" | талия: {last['waist']} см"
    else:
        weight_line = "Первый замер — фиксируем точку старта!"

    text = (
        f"📅 Понедельник — недельный чекин!\n\n"
        f"{weight_line}\n\n"
        f"Что нужно сделать натощак:\n"
        f"1️⃣ Взвесься\n"
        f"2️⃣ Измерь талию (уровень пупка)\n"
        f"3️⃣ Измерь бёдра (самое широкое место)\n"
        f"4️⃣ Измерь шею (самое узкое место)\n"
        f"5️⃣ Отправь: /weight [вес] [талия] [бёдра] [шея]\n"
        f"   Пример: /weight 83.5 91 111 36\n\n"
        f"Шея нужна для расчёта процента жира по методу ВМС США 🔬\n\n"
        f"После — пришли фото тела (спереди/сзади/сбоку) — дам детальный анализ и план на неделю 📊"
    )
    await bot.send_message(chat_id, text)


async def start_scheduler(bot, chat_id: int):
    scheduler = AsyncIOScheduler(timezone=VN_TZ)

    scheduler.add_job(
        morning_message,
        CronTrigger(hour=MORNING_HOUR, minute=0, timezone=VN_TZ),
        args=[bot, chat_id],
        id="morning"
    )
    scheduler.add_job(
        midday_check,
        CronTrigger(hour=MIDDAY_HOUR, minute=0, timezone=VN_TZ),
        args=[bot, chat_id],
        id="midday"
    )
    scheduler.add_job(
        evening_summary,
        CronTrigger(hour=EVENING_HOUR, minute=0, timezone=VN_TZ),
        args=[bot, chat_id],
        id="evening"
    )
    scheduler.add_job(
        weekly_reminder,
        CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=VN_TZ),
        args=[bot, chat_id],
        id="weekly"
    )

    scheduler.start()
    logger.info(f"Scheduler started for chat_id={chat_id}")
