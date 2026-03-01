import asyncio
import base64
import logging
import math
import re
from datetime import datetime, date, timedelta

import pytz
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

import database as db
import claude_ai as ai
import weekly_analysis as wa
from config import BOT_TOKEN, USER, TIMEZONE
from scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

VN_TZ = pytz.timezone(TIMEZONE)

# Сессии сбора фото тела {chat_id: {...}}
body_photo_sessions: dict[int, dict] = {}

# Онбординг {chat_id: {"step": ..., ...}}
onboarding_sessions: dict[int, dict] = {}

MONTHS_RU = {
    1: "январь", 2: "февраль", 3: "март", 4: "апрель",
    5: "май", 6: "июнь", 7: "июль", 8: "август",
    9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
}


# ── Вспомогательные функции ───────────────────────────────────────────────────

def now_vn():
    return datetime.now(VN_TZ).strftime("%H:%M")


def progress_bar(current, target, length=10) -> str:
    filled = int(min(current / target, 1.0) * length)
    return "█" * filled + "░" * (length - filled)


def parse_number(text: str) -> float | None:
    match = re.search(r'\d+(?:[.,]\d+)?', text)
    return float(match.group().replace(',', '.')) if match else None


def is_onboarding_trigger(text: str) -> bool:
    triggers = ["погнали худеть", "погнали", "хочу похудеть", "начать трекинг"]
    return any(t in text.lower().strip() for t in triggers)


def format_totals(totals: dict, log: dict | None = None) -> str:
    """Полный дашборд нутриентов за день"""
    p  = USER["protein_goal_g"]
    c  = USER["calories_goal_kcal"]
    ca = USER.get("calcium_goal_mg", 1200)
    fi = USER.get("fiber_goal_g", 28)
    lines = [
        "📊 Сегодня:",
        f"🥩 Белок:     {totals['protein']:.0f}/{p}г {progress_bar(totals['protein'], p)}",
        f"🔥 Калории:   {totals['calories']:.0f}/{c} {progress_bar(totals['calories'], c)}",
        f"🦴 Кальций:   ~{totals.get('calcium', 0):.0f}/{ca} мг",
        f"🌿 Клетчатка: {totals.get('fiber', 0):.0f}/{fi}г",
        f"🧈 Жиры: {totals['fat']:.0f}г   🍚 Углеводы: {totals['carbs']:.0f}г",
    ]
    if log is not None:
        lines.append(f"💊 Омега-3: {'✅' if log.get('omega3') else '❌'}")
        if log.get("steps"):
            lines.append(f"👟 Шаги: {log['steps']}/{USER.get('steps_goal', 8000)}")
        if log.get("workout"):
            lines.append(f"🏋️ Тренировка: {log['workout']}")
    return "\n".join(lines)


def format_daily_needs(totals: dict, log: dict) -> str:
    """Что нужно добрать до конца дня — без API-запросов"""
    needs = []
    workout = log.get("workout") or ""
    is_strength = "силовая" in workout.lower()
    is_cardio   = any(x in workout.lower() for x in ["бадминтон", "плавание"])

    # Белок — на тренировочные дни порог ниже (важнее добрать)
    protein_left  = USER["protein_goal_g"] - totals["protein"]
    protein_threshold = 10 if (is_strength or is_cardio) else 15
    if protein_left > protein_threshold:
        if protein_left > 70:
            hint = "150–200г куриной грудки + пачка творога"
        elif protein_left > 40:
            hint = "150г куриной грудки или пачка творога"
        elif protein_left > 20:
            hint = "3 яйца или стакан кефира + сыр"
        else:
            hint = "2 яйца или 100г рыбы"
        suffix = " ⚡ тренировочный день!" if (is_strength or is_cardio) else ""
        needs.append(f"🥩 Белок +{protein_left:.0f}г → {hint}{suffix}")

    # Кальций
    calcium_left = USER.get("calcium_goal_mg", 1200) - totals.get("calcium", 0)
    if calcium_left > 400:
        needs.append("🦴 Кальций: 2 порции молочки или рыбы (кефир, тофу, сардины)")
    elif calcium_left > 150:
        needs.append("🦴 Кальций: стакан кефира или 30г твёрдого сыра")

    # Омега-3
    if not log.get("omega3"):
        needs.append("💊 Омега-3: прими капсулу с едой (не натощак!)")

    # Клетчатка
    fiber_left = USER.get("fiber_goal_g", 28) - totals.get("fiber", 0)
    if fiber_left > 8:
        needs.append(f"🌿 Клетчатка +{fiber_left:.0f}г: добавь овощи к ужину (огурец, зелень, авокадо)")

    # Шаги
    steps      = log.get("steps") or 0
    steps_goal = USER.get("steps_goal", 8000)
    if steps < steps_goal * 0.5:
        needs.append(f"👟 Шаги: ещё {steps_goal - steps} до нормы")

    # Напомнить записать тренировку если нет
    if not workout:
        needs.append("🏋️ Была тренировка? Запиши: /workout силовая|бадминтон|плавание")

    if not needs:
        return "✅ Все нормы дня закрыты — молодец!"
    return "💡 До конца дня:\n" + "\n".join(f"• {n}" for n in needs)


# ── Онбординг ─────────────────────────────────────────────────────────────────

async def start_onboarding(message: Message):
    chat_id = message.chat.id
    onboarding_sessions[chat_id] = {"step": "weight"}
    await message.answer(
        "Отлично, начинаем! 🚀\n\n"
        "Зафиксируем точку старта — от неё буду строить прогноз.\n\n"
        "Шаг 1/4: Сколько весишь сейчас? (например: 85)"
    )


async def handle_onboarding_step(message: Message, text: str):
    chat_id = message.chat.id
    session = onboarding_sessions[chat_id]
    step = session["step"]
    value = parse_number(text)
    if not value:
        await message.answer("Напиши просто цифру, например: 85")
        return

    if step == "weight":
        session["weight"] = value
        session["step"] = "waist"
        await message.answer(f"Вес {value} кг ✅\n\nШаг 2/4: Талия (см)? Измерь на уровне пупка.")

    elif step == "waist":
        session["waist"] = value
        session["step"] = "hips"
        await message.answer(f"Талия {value} см ✅\n\nШаг 3/4: Бёдра (см)? Самая широкая часть.")

    elif step == "hips":
        session["hips"] = value
        session["step"] = "neck"
        await message.answer(f"Бёдра {value} см ✅\n\nШаг 4/4: Шея (см)? Измерь в самом узком месте.")

    elif step == "neck":
        session["neck"] = value
        del onboarding_sessions[chat_id]
        await complete_onboarding(message, session)


async def complete_onboarding(message: Message, session: dict):
    weight = session["weight"]
    waist  = session["waist"]
    hips   = session["hips"]
    neck   = session["neck"]

    await db.log_weight(weight, waist, hips, neck)
    await db.save_chat_id(message.chat.id)
    await db.set_setting("baseline_weight", str(weight))
    await db.set_setting("baseline_date", date.today().isoformat())

    goal = USER["goal_weight_kg"]
    kg_to_goal = round(weight - goal, 1)

    # Процент жира методом ВМС США
    bf = wa.calculate_body_fat_navy(USER["height_cm"], waist, hips, neck)
    bf_cat = (
        "норма" if bf < 32 else
        "выше нормы, есть куда снижать" if bf < 38 else
        "высокий — это главная цель"
    )

    def target_month(rate: float) -> str:
        d = date.today() + timedelta(weeks=kg_to_goal / rate)
        return f"{MONTHS_RU[d.month]} {d.year}"

    await message.answer(
        f"✅ Старт зафиксирован!\n\n"
        f"📊 Исходные данные:\n"
        f"⚖️ Вес: {weight} кг\n"
        f"📏 Талия: {waist} см  |  Бёдра: {hips} см  |  Шея: {neck} см\n"
        f"🔬 Процент жира (метод ВМС): {bf}% — {bf_cat}\n\n"
        f"🎯 Цель: {goal} кг (минус {kg_to_goal} кг)\n\n"
        f"📈 Предварительный прогноз:\n"
        f"• Оптимистично (−1 кг/нед): {target_month(1.0)}\n"
        f"• Реалистично (−0.7 кг/нед): {target_month(0.7)}\n"
        f"• Консервативно (−0.4 кг/нед): {target_month(0.4)}\n\n"
        f"На Оземпике первые 1-2 мес обычно идёт быстрее. "
        f"Через 3-4 замера дам персональный прогноз по твоему реальному темпу.\n\n"
        f"Каждый понедельник в 8:00 — замеры + фото. Поехали! 💪"
    )


# ── Команды ───────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await db.save_chat_id(message.chat.id)
    await message.answer(
        f"Привет, {USER['name']}! 👋\n\n"
        "Я твой фитнес-помощник:\n\n"
        "📸 Фото еды — КБЖУ + кальций + клетчатка\n"
        "💬 Напиши что съела — то же самое\n"
        "📋 /summary — итог дня (все нутриенты)\n"
        "⚖️ /weight 84.5 93 113 37 — вес + талия + бёдра + шея\n"
        "👟 /steps 8500 — записать шаги\n"
        "😴 /sleep 7.5 — сон\n"
        "💊 /omega — Омега-3\n"
        "🏋️ /workout силовая|бадминтон|плавание\n"
        "📊 /weekly — еженедельный отчёт + анализ фото\n\n"
        "Чтобы начать трекинг — напиши: Погнали худеть\n\n"
        f"Цель: белок {USER['protein_goal_g']}г, калории {USER['calories_goal_kcal']} ккал, "
        f"кальций {USER['calcium_goal_mg']} мг, клетчатка {USER['fiber_goal_g']}г 💪"
    )


@dp.message(Command("summary"))
async def cmd_summary(message: Message):
    totals, log = await asyncio.gather(db.get_today_totals(), db.get_today_log())
    text = format_totals(totals, log)
    text += f"\n\n😴 Сон: {log['sleep'] or '—'} ч"
    text += "\n\n" + format_daily_needs(totals, log)
    await message.answer(text)


@dp.message(Command("sleep"))
async def cmd_sleep(message: Message):
    try:
        hours = float(message.text.split()[1])
        await db.log_sleep(hours)
        if hours >= 7:
            comment = "Отлично 💪"
        elif hours >= 6:
            comment = "Неплохо, но старайся к 7-8ч — кортизол и белок зависят от сна."
        else:
            comment = "Маловато. Недосып повышает кортизол → задержка жира в талии и потеря мышц."
        await message.answer(f"Сон записан: {hours}ч\n{comment}")
    except (IndexError, ValueError):
        await message.answer("Напиши так: /sleep 7.5")


@dp.message(Command("omega"))
async def cmd_omega(message: Message):
    await db.log_omega3()
    await message.answer("Омега-3 ✅\nПринимай с едой — лучше всасывается и меньше нагрузка на ЖКТ (особенно на Оземпике).")


@dp.message(Command("steps"))
async def cmd_steps(message: Message):
    try:
        steps = int(message.text.split()[1])
        await db.log_steps(steps)
        goal = USER.get("steps_goal", 8000)
        pct = steps / goal * 100
        bar = progress_bar(steps, goal)
        if steps >= goal:
            comment = "Норма выполнена 🎉"
        elif steps >= goal * 0.7:
            comment = f"Ещё {goal - steps} шагов до нормы"
        else:
            comment = f"До нормы {goal - steps} шагов — прогулка 20-30 мин поможет"
        await message.answer(f"👟 Шаги: {steps}/{goal} {bar} ({pct:.0f}%)\n{comment}")
    except (IndexError, ValueError):
        await message.answer("Напиши: /steps 8500")


@dp.message(Command("workout"))
async def cmd_workout(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Напиши: /workout силовая  |  /workout бадминтон  |  /workout плавание")
        return
    workout = parts[1].strip().lower()
    mapping = {
        "силовая": "💪 Силовая",
        "бадминтон": "🏸 Бадминтон",
        "плавание": "🏊 Плавание",
    }
    label = mapping.get(workout, f"🏃 {workout.capitalize()}")
    await db.log_workout(label)

    totals = await db.get_today_totals()
    protein_now  = totals["protein"]
    protein_goal = USER["protein_goal_g"]
    protein_left = protein_goal - protein_now

    if workout == "силовая":
        advice = (
            "💪 Силовая записана!\n\n"
            "Окно восстановления — 1-2 часа после тренировки:\n"
            "• Белок сейчас обязателен — он идёт на восстановление мышц, а не в жир\n"
            "• На Оземпике аппетита может не быть — ешь всё равно\n\n"
        )
        if protein_left > 40:
            advice += (
                f"⚠️ Белок сегодня: {protein_now:.0f}/{protein_goal}г — нужно добрать {protein_left:.0f}г\n"
                "Сейчас: куриная грудка / яйца / творог 5% / рыба"
            )
        elif protein_left > 15:
            advice += (
                f"Белок: {protein_now:.0f}/{protein_goal}г — ещё {protein_left:.0f}г\n"
                "Стакан кефира или 2 яйца закроют остаток"
            )
        else:
            advice += f"Белок: {protein_now:.0f}/{protein_goal}г — норма закрыта ✅"

    elif workout == "бадминтон":
        advice = (
            "🏸 Бадминтон записан!\n\n"
            "После кардио:\n"
            "• Выпей воды или воды с электролитами (потеряла соль)\n"
            "• Белок + небольшие углеводы для восстановления\n\n"
            f"Белок сегодня: {protein_now:.0f}/{protein_goal}г"
        )
        if protein_left > 20:
            advice += f" — ещё {protein_left:.0f}г нужно добрать"

    elif workout == "плавание":
        advice = (
            "🏊 Плавание записано!\n\n"
            "После бассейна:\n"
            "• Обязательно выпей воду — в воде жажда не ощущается\n"
            "• Белок для восстановления мышц\n\n"
            f"Белок сегодня: {protein_now:.0f}/{protein_goal}г"
        )
        if protein_left > 20:
            advice += f" — ещё {protein_left:.0f}г нужно"

    else:
        advice = (
            f"{label} записана ✅\n\n"
            f"Белок сегодня: {protein_now:.0f}/{protein_goal}г"
        )
        if protein_left > 20:
            advice += f" — ещё {protein_left:.0f}г нужно добрать"

    await message.answer(advice)


@dp.message(Command("weight"))
async def cmd_weight(message: Message):
    parts = message.text.split()
    try:
        weight = float(parts[1])
        waist  = float(parts[2]) if len(parts) > 2 else None
        hips   = float(parts[3]) if len(parts) > 3 else None
        neck   = float(parts[4]) if len(parts) > 4 else None
        await db.log_weight(weight, waist, hips, neck)

        start_weight = USER["weight_kg"]
        goal = USER["goal_weight_kg"]
        lost = start_weight - weight
        to_go = weight - goal

        text = f"⚖️ Вес: {weight} кг\n"
        if lost > 0:
            text += f"🎉 Минус {lost:.1f} кг от старта!\n"
        text += f"До цели ({goal} кг): ещё {to_go:.1f} кг"
        if waist:
            text += f"\n📏 Талия: {waist} см"
        if hips:
            text += f"\n📏 Бёдра: {hips} см"
        if neck:
            text += f"\n📏 Шея: {neck} см"
        if neck and waist and hips:
            bf = wa.calculate_body_fat_navy(USER["height_cm"], waist, hips, neck)
            bf_cat = (
                "норма" if bf < 32 else
                "выше нормы" if bf < 38 else
                "высокий"
            )
            text += f"\n🔬 Жир: {bf}% ({bf_cat})"
        await message.answer(text)

        # Понедельничный чекин — переходим к фото
        weekly_pending = await db.get_setting("weekly_pending")
        if weekly_pending == "1":
            await db.set_setting("weekly_pending", "0")
            chat_id = message.chat.id
            previous  = await db.get_prev_week_weight()
            week_avg  = await db.get_week_avg()
            workouts  = await db.get_week_workouts()
            history   = await db.get_weight_history()
            forecast  = wa.calculate_forecast(history, USER["goal_weight_kg"])

            body_photo_sessions[chat_id] = {
                "photos": [],
                "current": {"weight": weight, "waist": waist, "hips": hips, "neck": neck},
                "previous": previous,
                "avg_protein":   week_avg["avg_protein"],
                "avg_calories":  week_avg["avg_calories"],
                "avg_calcium":   week_avg["avg_calcium"],
                "avg_fiber":     week_avg["avg_fiber"],
                "omega3_days":   week_avg["omega3_days"],
                "avg_steps":     week_avg["avg_steps"],
                "workouts":      workouts,
                "forecast":      forecast,
            }

            forecast_line = ""
            if forecast.get("status") == "ok" and forecast.get("weeks_to_goal_recent"):
                forecast_line = (
                    f"\n📈 Темп: {forecast['recent_weekly_rate']:.2f} кг/нед → "
                    f"цель через ~{forecast['weeks_to_goal_recent']:.0f} нед ({forecast['goal_date_recent']})"
                )

            await message.answer(
                f"Замеры недели зафиксированы.{forecast_line}\n\n"
                "Пришли фото тела (спереди / сзади / сбоку) для полного анализа.\n"
                "Или /skip_photos чтобы сразу получить текстовый отчёт."
            )

    except (IndexError, ValueError):
        await message.answer("Напиши: /weight 84.5  или  /weight 84.5 91 111 37")


# ── Еженедельный отчёт ────────────────────────────────────────────────────────

@dp.message(Command("weekly"))
async def cmd_weekly(message: Message):
    chat_id = message.chat.id
    current = await db.get_last_weight()
    if not current:
        await message.answer("Нет данных о весе. Запиши: /weight 84.5 91 111 37")
        return

    previous = await db.get_prev_week_weight()
    week_avg = await db.get_week_avg()
    workouts = await db.get_week_workouts()
    history  = await db.get_weight_history()
    forecast = wa.calculate_forecast(history, USER["goal_weight_kg"])

    body_photo_sessions[chat_id] = {
        "photos": [],
        "current": current,
        "previous": previous,
        "avg_protein":  week_avg["avg_protein"],
        "avg_calories": week_avg["avg_calories"],
        "avg_calcium":  week_avg["avg_calcium"],
        "avg_fiber":    week_avg["avg_fiber"],
        "omega3_days":  week_avg["omega3_days"],
        "avg_steps":    week_avg["avg_steps"],
        "workouts":     workouts,
        "forecast":     forecast,
    }

    forecast_line = ""
    if forecast.get("status") == "ok" and forecast.get("weeks_to_goal_recent"):
        forecast_line = (
            f"\n📈 Темп: {forecast['recent_weekly_rate']:.2f} кг/нед → "
            f"цель через ~{forecast['weeks_to_goal_recent']:.0f} нед ({forecast['goal_date_recent']})"
        )

    omega_line = f"\n💊 Омега-3 дней: {week_avg['omega3_days']}/7"
    await message.answer(
        f"📊 Данные недели:\n"
        f"⚖️ Вес: {current.get('weight')} кг\n"
        f"📏 Талия: {current.get('waist') or '—'} см\n"
        f"🥩 Белок avg: {week_avg['avg_protein']:.0f} г/день\n"
        f"🦴 Кальций avg: ~{week_avg['avg_calcium']:.0f} мг/день\n"
        f"🌿 Клетчатка avg: {week_avg['avg_fiber']:.0f} г/день"
        f"{omega_line}\n"
        f"🏋️ Тренировок: {workouts}{forecast_line}\n\n"
        "Пришли фото тела (спереди/сзади/сбоку) или /skip_photos для текстового отчёта."
    )


@dp.message(Command("done_photos"))
@dp.message(Command("skip_photos"))
async def cmd_done_photos(message: Message):
    chat_id = message.chat.id
    session = body_photo_sessions.get(chat_id)
    if not session or not isinstance(session, dict):
        await message.answer("Нет активной сессии. Начни с /weekly")
        return

    await message.answer("Анализирую данные... ⏳")
    photos  = session.get("photos", [])
    current = session["current"]

    try:
        report = await wa.generate_weekly_report(
            current,
            session["previous"],
            session["avg_protein"],
            session["avg_calories"],
            session["workouts"],
            forecast=session.get("forecast"),
            avg_calcium=session.get("avg_calcium", 0),
            avg_fiber=session.get("avg_fiber", 0),
            omega3_days=session.get("omega3_days", 0),
            avg_steps=session.get("avg_steps", 0),
        )
        await message.answer(f"📋 Еженедельный отчёт\n\n{report}")

        if photos:
            await message.answer("Анализирую фото тела... 📸")
            photo_analysis = await wa.analyze_body_photos(photos, current)
            await message.answer(f"📸 Анализ фото\n\n{photo_analysis}")
    except Exception as e:
        logging.error(f"Weekly report error: {e}")
        await message.answer("Ошибка. Попробуй /weekly ещё раз.")
    finally:
        body_photo_sessions.pop(chat_id, None)


# ── Фото (еда или тело) ───────────────────────────────────────────────────────

@dp.message(F.photo)
async def handle_photo(message: Message):
    chat_id = message.chat.id
    session = body_photo_sessions.get(chat_id)

    if session and isinstance(session, dict):
        photo = message.photo[-1]
        file  = await bot.get_file(photo.file_id)
        fb    = await bot.download_file(file.file_path)
        b64   = base64.standard_b64encode(fb.read()).decode("utf-8")
        session["photos"].append(b64)
        count = len(session["photos"])
        labels = ["спереди", "сзади", "сбоку"]
        label  = labels[count - 1] if count <= 3 else f"фото {count}"
        await message.answer(f"Фото {label} ✅ ({count}/3)")
        if count >= 3:
            await message.answer("Все фото получены. Генерирую отчёт...")
            await cmd_done_photos(message)
        return

    # Анализ еды
    await message.answer("Анализирую фото... 🔍")
    photo = message.photo[-1]
    file  = await bot.get_file(photo.file_id)
    fb    = await bot.download_file(file.file_path)
    result = await ai.analyze_food_photo(fb.read())

    await db.add_meal(
        result.get("text", "фото")[:100],
        result["calories"], result["protein"], result["fat"], result["carbs"],
        result.get("calcium", 0), result.get("fiber", 0),
    )

    totals, log = await asyncio.gather(db.get_today_totals(), db.get_today_log())
    text = result["text"] + "\n\n" + format_totals(totals) + "\n\n" + format_daily_needs(totals, log)
    await message.answer(text)


# ── Текст (еда, онбординг, триггер) ──────────────────────────────────────────

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text_food(message: Message):
    text    = message.text.strip()
    chat_id = message.chat.id

    if chat_id in onboarding_sessions:
        await handle_onboarding_step(message, text)
        return

    if is_onboarding_trigger(text):
        await start_onboarding(message)
        return

    if len(text) < 3:
        return

    await message.answer("Считаю... 🔢")
    result = await ai.analyze_food_text(text)
    await db.add_meal(
        text[:100],
        result["calories"], result["protein"], result["fat"], result["carbs"],
        result.get("calcium", 0), result.get("fiber", 0),
    )

    totals, log = await asyncio.gather(db.get_today_totals(), db.get_today_log())
    response = result["text"] + "\n\n" + format_totals(totals) + "\n\n" + format_daily_needs(totals, log)
    await message.answer(response)


# ── Запуск ────────────────────────────────────────────────────────────────────

async def main():
    await db.init_db()
    chat_id = await db.get_chat_id()
    if chat_id:
        await start_scheduler(bot, chat_id)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
