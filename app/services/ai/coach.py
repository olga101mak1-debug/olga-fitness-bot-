import json
from app.services.ai.claude_client import call_text
from app.config import MAX_CLARIFYING_QUESTIONS

# Сколько дней истории отдаём модели. Раньше было 14 дней и 11 полей — из-за этого бот
# не видел ни еды за прошлые дни, ни тренировок, ни половины показателей, и на вопрос
# про статистику отвечал, что данных нет.
HISTORY_DAYS_IN_CONTEXT = 45


def _build_system(user: dict) -> str:
    return f"""Ты — LIFE AI, персональный аналитик здоровья и требовательный тренер {user.get('name', 'пользователя')}.

Профиль: рост {user.get('height_cm')} см, возраст {user.get('age')}, целевой вес {user.get('target_weight_kg')} кг,
норма {user.get('calories_goal_kcal')} ккал и {user.get('protein_goal_g')} г белка в день,
лекарства: {user.get('medications') or 'нет'}.

ТВОЙ ХАРАКТЕР — это главное, что в тебе изменилось. Ты не утешитель и не группа поддержки.
Ты тренер, который на её стороне ровно настолько, чтобы говорить правду в лицо.
Она попросила держать её в узде и давать реальную картину, а не гладить по головке.

Как это выглядит на практике:
— НАЧИНАЙ С ЦИФРЫ И ФАКТА, а не с эмоции. Не «умница, что записала», а «1450 ккал, белок 64 при норме 135».
— Называй вещи своими именами: плато — это плато, срыв — это срыв, две недели без замеров — это две недели
  без замеров. Не смягчай формулировку, чтобы было приятнее.
— Каждый ответ заканчивай ОДНИМ конкретным требованием на ближайший день. Не списком, не «попробуй»,
  а одним понятным действием: «завтра взвешивание утром» или «добери 70 г белка».
— Хвали ТОЛЬКО за результат, подтверждённый цифрами. За намерение, попытку и сам факт записи — не хвали.
— Если данных не хватает, чтобы сделать вывод — так и скажи и потребуй их. Не додумывай и не утешай
  вместо анализа. Отсутствие данных — это тоже вывод, и он про дисциплину.
— Если видишь ухудшение или застой — скажи об этом первым делом, до всего остального, и назови
  вероятную причину ИЗ ДАННЫХ (мало белка, нет тренировок, три дня без записей), а не абстрактно.

ЗАПРЕЩЕНО:
— Фразы-пустышки: «ничего страшного», «бывает», «главное — ты стараешься», «молодец, что призналась»,
  «не вини себя», «в целом всё хорошо». Ни одной из них быть не должно.
— Хвалить за день, который по цифрам провален.
— Смягчать вывод, чтобы не расстроить. Она просила обратного.

ГРАНИЦЫ (строгость — это про факты, а не про личность):
— Никаких оценок её как человека, никакого стыда за тело, никакой вины. Критикуешь режим и цифры, не её.
— Не ставишь диагнозов и не отменяешь назначения врача. Про лекарства — только фиксация, не рекомендации.
— Не выдумываешь цифры. Любое число в твоём ответе должно быть взято из контекста ниже. Если числа нет
  в контексте — не называй его вообще.
— Не объясняешь физиологию домыслами («тело держит воду от стресса», «метаболизм замедлился»,
  «организм в режиме экономии»). Связывай наблюдаемые цифры между собой — мало белка и вес стоит,
  тренировок не было и объёмы не двигаются — и честно говори «причина по данным не видна»,
  если её действительно не видно.

РАБОТА С КОНТЕКСТОМ:
— Ниже дана ПОЛНАЯ СТАТИСТИКА по всей накопленной истории и история по дням. Это твоя база данных.
  Никогда не говори, что у тебя нет данных или нет доступа к истории — данные перед тобой.
— Если она просит статистику, динамику, сравнение периодов или «как у меня дела» — отвечай развёрнуто,
  конкретными цифрами из блока статистики, с выводом что именно они значат.
— Ты ведёшь один непрерывный разговор в течение дня. Не повторяй то, что уже сказала сегодня,
  не задавай вопрос, на который уже получила ответ, учитывай текущее время суток.
— СВЕРЯЙ ДАТЫ. Не называй запись «вчерашней» или «позавчерашней», не посчитав по датам в истории.
  Если последний замер веса был 5 дней назад — так и говори: «замер пятидневной давности».
  Пропущенные дни в истории — это дни без записей, а не дни с нулевыми показателями.
  Не преувеличивай сроки: «плато третий месяц» можно сказать, только если это видно по датам.
— Обращайся на «ты», всегда. Никакого «вы» и безличных формулировок.

ПРО ЗАПИСИ В ДНЕВНИКЕ:
— Ты не редактируешь записи сама. Всё, что изменено, перечислено в блоке «Только что изменено в записях».
  Если блока нет — значит ничего не менялось.
— Никогда не пиши «уберу», «удалю», «перенесу», «исправлю», «пересчитаю» про записи: это обещания,
  которые ты не можешь выполнить, и цифры потом расходятся с дневником.
— Никогда не называй итог за день, отличный от «Итого по еде за сегодня». Если кажется, что там дубль —
  спроси: «Похоже, вот это задвоилось — убрать?», а не пересчитывай молча.

Если не хватает важной информации за сегодня — задай не более {MAX_CLARIFYING_QUESTIONS} коротких вопросов,
и только про то, чего действительно нет в записях.
Отвечай по-русски, плотно, без воды: 3-6 предложений на обычное сообщение, развёрнуто — на запрос аналитики."""


def _format_dialog(dialog: list[dict]) -> str:
    lines = []
    for m in dialog:
        who = "Она" if m.get("role") == "user" else "Ты"
        time = (m.get("created_at") or "")[11:16]
        lines.append(f"[{time}] {who}: {m.get('text', '')}")
    return "\n".join(lines)


def _compact_history(history: list[dict], meal_days: list[dict],
                     activities_by_day: dict[str, list]) -> list[dict]:
    """История по дням со всеми показателями, едой и тренировками в одной строке на день.

    Раньше сюда попадали только 11 полей и ни одной калории за прошлые дни.
    """
    meals_by_date = {m["date"]: m for m in (meal_days or [])}
    rows = []
    for day in history[-HISTORY_DAYS_IN_CONTEXT:]:
        date = day.get("date")
        row = {"date": date}
        for field in ("weight", "waist", "belly", "hips", "neck", "chest", "sleep_hours",
                      "sleep_quality", "energy", "mood", "stress", "work_hours", "steps",
                      "water_liters", "alcohol", "nutrition_event", "training", "comment"):
            value = day.get(field)
            if value is not None:
                row[field] = value
        food = meals_by_date.get(date)
        if food:
            row["ккал"] = round(food.get("calories") or 0)
            row["белок_г"] = round(food.get("protein") or 0)
            row["приёмов_пищи"] = food.get("count")
        acts = activities_by_day.get(date)
        if acts:
            row["тренировки"] = acts
        rows.append(row)
    return rows


def _format_context(today: dict, history: list[dict], goal: dict | None, insights: list[dict],
                     baseline: dict | None = None, now: str | None = None,
                     meals: list[dict] | None = None, meal_totals: dict | None = None,
                     activities: list[dict] | None = None, dialog: list[dict] | None = None,
                     applied_edits: list[str] | None = None, weight_warning: str | None = None,
                     overview: dict | None = None, meal_days: list[dict] | None = None,
                     period_activities: list[dict] | None = None) -> str:
    known = {k: v for k, v in today.items() if v is not None and k != "date"}
    lines = []
    if now:
        lines.append(f"Сейчас: {now}. Ориентируйся на это время суток.")
    if applied_edits:
        lines.append("Только что изменено в записях (это уже сделано, можешь на это опираться): "
                     + "; ".join(applied_edits)
                     + ". Не обещай сделать это ещё раз и не предлагай «убрать» то, что уже убрано.")
    if weight_warning:
        lines.append("Вес из последнего сообщения НЕ записан, пользователю уже показано предупреждение: "
                     + weight_warning + " Не повторяй это предупреждение своими словами.")

    if overview:
        lines.append(
            "ПОЛНАЯ СТАТИСТИКА по всей истории (посчитана из базы, это точные числа — "
            "используй именно их, не пересчитывай в уме и не округляй по-своему):\n"
            + json.dumps(overview, ensure_ascii=False)
        )

    lines.append(f"Сегодня ({today.get('date')}), уже известно за сегодня: {json.dumps(known, ensure_ascii=False)}")
    if meals:
        lines.append(f"Приёмы пищи, уже записанные за сегодня: {json.dumps(meals, ensure_ascii=False)}")
    if meal_totals and meal_totals.get("count"):
        lines.append(f"Итого по еде за сегодня: {json.dumps(meal_totals, ensure_ascii=False)}")
    elif not meals:
        lines.append("Приёмов пищи за сегодня пока не записано (это не значит, что она не ела — "
                     "возможно просто не присылала).")
    if activities:
        lines.append(f"Активности и тренировки, уже записанные за сегодня: {json.dumps(activities, ensure_ascii=False)}")
    if baseline:
        lines.append(
            "Точка старта наблюдений (используй ТОЛЬКО эту дату и эти цифры для любых формулировок "
            f"«с начала»/«всего прогресс», не путай с окном ниже): {json.dumps(baseline, ensure_ascii=False)}"
        )
    if history:
        activities_by_day: dict[str, list] = {}
        for act in (period_activities or []):
            entry = act.get("type") or "тренировка"
            if act.get("minutes"):
                entry += f" {act['minutes']}м"
            activities_by_day.setdefault(act.get("date"), []).append(entry)
        trend = _compact_history(history, meal_days or [], activities_by_day)
        lines.append("История по дням (показатели, еда и тренировки; дни без записей отсутствуют — "
                     f"это пропуски в дневнике, а не нули): {json.dumps(trend, ensure_ascii=False)}")
    if goal:
        lines.append(f"Активная цель: {json.dumps(goal, ensure_ascii=False)}")
    if insights:
        lines.append(f"Ранее замеченные закономерности: {json.dumps(insights, ensure_ascii=False)}")
    if dialog:
        lines.append("Переписка за сегодня (сверху старые, снизу свежие; «Ты» — это твои же прошлые ответы):\n"
                     + _format_dialog(dialog))
    return "\n\n".join(lines)


async def generate_reply(today: dict, history: list[dict], goal: dict | None,
                          insights: list[dict], user: dict, user_message: str,
                          baseline: dict | None = None, now: str | None = None,
                          meals: list[dict] | None = None, meal_totals: dict | None = None,
                          activities: list[dict] | None = None, dialog: list[dict] | None = None,
                          applied_edits: list[str] | None = None,
                          weight_warning: str | None = None,
                          overview: dict | None = None, meal_days: list[dict] | None = None,
                          period_activities: list[dict] | None = None) -> str:
    context = _format_context(today, history, goal, insights, baseline, now=now, meals=meals,
                               meal_totals=meal_totals, activities=activities, dialog=dialog,
                               applied_edits=applied_edits, weight_warning=weight_warning,
                               overview=overview, meal_days=meal_days,
                               period_activities=period_activities)
    prompt = f"{context}\n\nСообщение пользователя только что: \"{user_message}\"\n\nНапиши ответ."
    return await call_text(_build_system(user), prompt, max_tokens=2000)
