import math
import anthropic
from datetime import datetime, timedelta
from config import ANTHROPIC_API_KEY, USER

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = f"""Ты персональный врач-нутрициолог и спортивный тренер Ольги, 46 лет, Нячанг, Вьетнам.
Параметры: рост {USER['height_cm']}см, старт {USER['weight_kg']}кг, цель {USER['goal_weight_kg']}кг.

МЕДИЦИНСКИЙ КОНТЕКСТ (учитывай в каждом анализе):
- Оземпик (семаглутид): снижен аппетит, замедлено опорожнение желудка → риск дефицита белка, кальция, потери мышц
- Предменопауза: повышенный кортизол, инсулинорезистентность, ускоренная потеря костной массы → кальций критически важен
- Приоритет №1: мышцы (белок {USER['protein_goal_g']}г/день + силовые)
- Приоритет №2: кости (кальций {USER['calcium_goal_mg']}мг/день + Омега-3)
- Приоритет №3: висцеральный жир — талия главный маркер

ПРОГРАММА: Физикл (Зингилевский) — дефицит 300-500 ккал, высокий белок, силовые 3x/нед
АКТИВНОСТЬ: силовые 3x, бадминтон 2x, плавание 1x

СТИЛЬ: Прямо, экспертно, с цифрами. Объясняй ПОЧЕМУ. Без воды. Русский язык."""


MONTHS_RU = {
    1: "январь", 2: "февраль", 3: "март", 4: "апрель",
    5: "май", 6: "июнь", 7: "июль", 8: "август",
    9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
}


def calculate_body_fat_navy(height_cm: float, waist_cm: float, hips_cm: float, neck_cm: float) -> float:
    """Процент жира — метод ВМС США (для женщин)"""
    h  = height_cm / 2.54
    w  = waist_cm  / 2.54
    hi = hips_cm   / 2.54
    n  = neck_cm   / 2.54
    try:
        bf = 163.205 * math.log10(w + hi - n) - 97.684 * math.log10(h) - 78.387
        return round(max(10.0, min(55.0, bf)), 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def calculate_forecast(history: list[dict], goal_weight: float) -> dict:
    """Прогноз по истории замеров"""
    points = []
    for h in history:
        if h.get("weight"):
            try:
                d = datetime.strptime(h["date"], "%Y-%m-%d")
                points.append((d, float(h["weight"])))
            except (ValueError, KeyError):
                continue

    if len(points) < 2:
        return {"status": "need_more_data", "data_points": len(points)}

    points.sort(key=lambda x: x[0])
    first_date, first_weight = points[0]
    last_date,  last_weight  = points[-1]

    days_elapsed = (last_date - first_date).days
    if days_elapsed == 0:
        return {"status": "need_more_data", "data_points": 1}

    total_loss     = first_weight - last_weight
    avg_weekly_rate = total_loss / (days_elapsed / 7)

    recent_pts = points[-4:] if len(points) >= 4 else points
    r_days = (recent_pts[-1][0] - recent_pts[0][0]).days
    if r_days > 0:
        recent_loss = recent_pts[0][1] - recent_pts[-1][1]
        recent_rate = recent_loss / (r_days / 7)
    else:
        recent_rate = avg_weekly_rate

    kg_to_goal = last_weight - goal_weight

    def to_date_str(rate):
        if rate > 0.05:
            d = last_date + timedelta(weeks=kg_to_goal / rate)
            return f"{MONTHS_RU[d.month]} {d.year}", round(kg_to_goal / rate)
        return None, None

    goal_date_recent, weeks_recent = to_date_str(recent_rate)
    goal_date_avg,    weeks_avg    = to_date_str(avg_weekly_rate)

    return {
        "status": "ok",
        "data_points":         len(points),
        "days_tracked":        days_elapsed,
        "total_loss":          round(total_loss, 1),
        "avg_weekly_rate":     round(avg_weekly_rate, 2),
        "recent_weekly_rate":  round(recent_rate, 2),
        "kg_to_goal":          round(kg_to_goal, 1),
        "weeks_to_goal_recent": weeks_recent,
        "goal_date_recent":     goal_date_recent,
        "weeks_to_goal_avg":    weeks_avg,
        "goal_date_avg":        goal_date_avg,
        "current_weight":       last_weight,
        "start_weight":         first_weight,
    }


async def analyze_weekly_measurements(current: dict, previous: dict | None) -> str:
    prev_text = ""
    if previous:
        weight_diff = current.get("weight", 0) - previous.get("weight", 0)
        waist_diff  = (current.get("waist") or 0) - (previous.get("waist") or 0)
        prev_text = (
            f"\nПрошлая неделя: вес {previous.get('weight')}кг, "
            f"талия {previous.get('waist')}см\n"
            f"Изменения: вес {weight_diff:+.1f}кг, талия {waist_diff:+.1f}см"
        )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"""Замеры Ольги:
Вес: {current.get('weight')}кг | Талия: {current.get('waist')}см | Бёдра: {current.get('hips')}см
{prev_text}

Экспертный анализ (4-5 предложений):
1. Что реально произошло с телом (жир/вода/мышцы — объясни почему)
2. Прогресс зоны талии — важен при предменопаузе и Оземпике
3. Конкретные рекомендации на неделю (с цифрами)
4. Честный финал"""
        }]
    )
    return response.content[0].text


async def analyze_body_photos(photos_b64: list[str], measurements: dict | None = None) -> str:
    content = []
    labels = ["спереди", "сзади", "сбоку"]
    for i, photo_b64 in enumerate(photos_b64):
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": photo_b64}
        })

    meas_text = ""
    if measurements:
        bf_line = ""
        if measurements.get("neck") and measurements.get("waist") and measurements.get("hips"):
            bf = calculate_body_fat_navy(
                USER["height_cm"],
                measurements["waist"],
                measurements["hips"],
                measurements["neck"]
            )
            bf_line = f", жир ~{bf}%"
        meas_text = (
            f"\nЗамеры: вес {measurements.get('weight')}кг, "
            f"талия {measurements.get('waist')}см, бёдра {measurements.get('hips')}см{bf_line}"
        )

    content.append({
        "type": "text",
        "text": f"""Фото тела Ольги для анализа прогресса.{meas_text}

Визуальный анализ как спортивный врач:
1. Общее: соотношение жира и мышц визуально
2. Проблемные зоны: где больше всего жира сейчас?
3. Мышцы: видны ли? Есть признаки потери мышечной массы?
4. Висцеральный жир: форма живота — выпирает вперёд = висцеральный?
5. Конкретно: какие упражнения и нутриенты дадут максимум именно для этих зон

Честно и точно, как специалист."""
    })

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=700,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}]
    )
    return response.content[0].text


async def generate_weekly_report(
    measurements: dict,
    prev_measurements: dict | None,
    avg_protein: float,
    avg_calories: float,
    workouts_done: int,
    forecast: dict | None = None,
    avg_calcium: float = 0,
    avg_fiber: float = 0,
    omega3_days: int = 0,
    avg_steps: float = 0,
) -> str:
    """Полный еженедельный отчёт"""

    # Процент жира если есть все замеры
    bf_line = ""
    if measurements.get("neck") and measurements.get("waist") and measurements.get("hips"):
        bf = calculate_body_fat_navy(
            USER["height_cm"],
            measurements["waist"],
            measurements["hips"],
            measurements["neck"]
        )
        bf_line = f"\n- Процент жира (ВМС): {bf}%"

    # Сравнение с прошлой неделей
    prev_line = "- Первая неделя трекинга"
    if prev_measurements:
        w_diff  = round(measurements.get("weight", 0) - prev_measurements.get("weight", 0), 1)
        wt_diff = round((measurements.get("waist") or 0) - (prev_measurements.get("waist") or 0), 1)
        prev_line = (
            f"- Прошлая неделя: {prev_measurements.get('weight')}кг / талия {prev_measurements.get('waist')}см\n"
            f"- Изменение за неделю: вес {w_diff:+.1f}кг, талия {wt_diff:+.1f}см"
        )

    # Блок прогноза
    forecast_block = ""
    if forecast and forecast.get("status") == "ok":
        f = forecast
        forecast_block = (
            f"\nПРОГНОЗ:\n"
            f"- Всего потеряно: {f['total_loss']} кг за {f['days_tracked']} дней\n"
            f"- Средний темп: {f['avg_weekly_rate']:.2f} кг/нед | последние недели: {f['recent_weekly_rate']:.2f} кг/нед\n"
            f"- Осталось: {f['kg_to_goal']} кг"
        )
        if f.get("weeks_to_goal_recent"):
            forecast_block += f"\n- При текущем темпе: ~{f['weeks_to_goal_recent']} нед ({f['goal_date_recent']})"
    elif forecast and forecast.get("status") == "need_more_data":
        forecast_block = f"\nПРОГНОЗ: нужно ещё {3 - forecast.get('data_points', 0)} замера для точного расчёта."

    # Нутриенты за неделю
    calcium_goal = USER.get("calcium_goal_mg", 1200)
    fiber_goal   = USER.get("fiber_goal_g", 28)
    steps_goal   = USER.get("steps_goal", 8000)

    nutrients_block = (
        f"\nНУТРИЕНТЫ ЗА НЕДЕЛЮ (среднее/день):\n"
        f"- Белок: {avg_protein:.0f}г из {USER['protein_goal_g']}г ({avg_protein/USER['protein_goal_g']*100:.0f}%)\n"
        f"- Калории: {avg_calories:.0f} из {USER['calories_goal_kcal']} ккал ({avg_calories/USER['calories_goal_kcal']*100:.0f}%)\n"
        f"- Кальций: ~{avg_calcium:.0f} из {calcium_goal} мг ({avg_calcium/calcium_goal*100:.0f}%)\n"
        f"- Клетчатка: {avg_fiber:.0f} из {fiber_goal}г ({avg_fiber/fiber_goal*100:.0f}%)\n"
        f"- Омега-3: принята {omega3_days}/7 дней\n"
        f"- Шаги avg: {avg_steps:.0f}/{steps_goal}"
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=900,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"""Еженедельный отчёт Ольги:

ЗАМЕРЫ:
- Вес: {measurements.get('weight')}кг (цель {USER['goal_weight_kg']}кг)
- Талия: {measurements.get('waist')}см (цель < 80см)
- Бёдра: {measurements.get('hips')}см
- Шея: {measurements.get('neck') or '—'}см{bf_line}
{prev_line}
{nutrients_block}
ТРЕНИРОВКИ: {workouts_done} из 6 запланированных
{forecast_block}

Напиши глубокий экспертный отчёт:

1. ИТОГ НЕДЕЛИ — одним честным предложением что реально произошло с телом
2. РАЗБОР — почему такой результат? (белок/кальций/калории/тренировки/сон/Оземпик — конкретно)
3. НУТРИЕНТЫ — где были провалы и как они повлияли на результат (особенно белок и кальций)
4. ПРОГНОЗ — при текущем темпе когда цель? что изменить чтобы ускорить на 20%?
5. ПЛАН НА НЕДЕЛЮ — ровно 2 конкретных действия (не абстрактно, а: "добавь 2 яйца в завтрак + стакан кефира перед сном = +30г белка и +300мг кальция")
6. ЧЕСТНЫЙ ФИНАЛ — коротко"""
        }]
    )
    return response.content[0].text
