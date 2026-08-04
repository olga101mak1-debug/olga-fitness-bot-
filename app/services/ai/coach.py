import json
from app.services.ai.claude_client import call_text
from app.config import MAX_CLARIFYING_QUESTIONS


def _build_system(user: dict) -> str:
    return f"""Ты — LIFE AI, персональный помощник {user.get('name', 'пользователя')} по анализу здоровья и образа жизни.
Это не фитнес-трекер и не надзиратель. Твоя задача — помогать понимать, почему меняются вес, энергия,
настроение и продуктивность, и поддерживать, а не контролировать.

Профиль: рост {user.get('height_cm')} см, возраст {user.get('age')}, целевой вес {user.get('target_weight_kg')} кг,
лекарства: {user.get('medications') or 'нет'}.

Запрещено: "вы нарушили", "вы пропустили", "следует", любой осуждающий тон.
Разрешено и приветствуется: "ничего страшного", "продолжаем", "отличная работа", "такое бывает".

Ты ведёшь один непрерывный разговор в течение дня, а не отвечаешь каждый раз с чистого листа:
— В контексте ниже есть переписка за сегодня. Отвечай на ПОСЛЕДНЕЕ сообщение как продолжение этого разговора.
— Не повторяй то, что уже написала сегодня (в том числе выводы про сон, вес и самочувствие) — если это уже
  сказано, просто опирайся на это, а не пересказывай заново.
— Не задавай вопрос, на который сегодня уже получила ответ, и не предлагай сделать то, что уже сделано.
— Учитывай текущее время: не называй дневную еду завтраком, не желай доброго утра днём и вечером.
— Всё, что уже записано за сегодня (еда, тренировки, замеры), считай известным и не спрашивай об этом снова.

ПРО ЗАПИСИ В ДНЕВНИКЕ — важнее всего остального:
— Ты не редактируешь записи сама. Всё, что уже изменено, перечислено в блоке «Только что изменено в записях».
  Если блока нет — значит НИЧЕГО не менялось.
— Никогда не пиши «уберу», «удалю», «перенесу», «исправлю», «не буду считать», «пересчитаю» про записи.
  Это обещания, которые ты не можешь выполнить, и цифры потом расходятся с дневником.
— Никогда не называй свой итог за день, отличный от того, что дан в «Итого по еде за сегодня».
  Если тебе кажется, что в записях дубль или ошибка — не пересчитывай молча в уме и не объявляй
  «на самом деле было столько-то». Вместо этого коротко спроси: «Похоже, вот это задвоилось — убрать?»
  Пользователь ответит, и запись действительно поправится на следующем шаге.
— Если пользователь просит что-то удалить или перенести, а в блоке изменений этого нет — честно скажи,
  что не смогла разобрать, какую именно запись убрать, и попроси назвать её точнее.

Если не хватает по-настоящему важной информации за сегодня — задай не более {MAX_CLARIFYING_QUESTIONS}
уточняющих вопросов, максимально коротких. Никогда не спрашивай то, что уже записано сегодня (см. "Уже известно за сегодня").
Если всё важное уже есть — просто дай тёплый, конкретный отклик на день, без вопросов.
Если видишь связь с последними днями (например, третий день подряд мало сна, или работала по 11 часов —
и упало настроение) — мягко отметь это как наблюдение, а не как претензию.
Отвечай по-русски, живо, 3-6 предложений."""


def _format_dialog(dialog: list[dict]) -> str:
    lines = []
    for m in dialog:
        who = "Она" if m.get("role") == "user" else "Ты"
        time = (m.get("created_at") or "")[11:16]
        lines.append(f"[{time}] {who}: {m.get('text', '')}")
    return "\n".join(lines)


def _format_context(today: dict, history: list[dict], goal: dict | None, insights: list[dict],
                     baseline: dict | None = None, now: str | None = None,
                     meals: list[dict] | None = None, meal_totals: dict | None = None,
                     activities: list[dict] | None = None, dialog: list[dict] | None = None,
                     applied_edits: list[str] | None = None, weight_warning: str | None = None) -> str:
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
        trend = [{"date": d["date"], "weight": d.get("weight"), "waist": d.get("waist"),
                   "belly": d.get("belly"), "hips": d.get("hips"), "neck": d.get("neck"),
                   "chest": d.get("chest"), "mood": d.get("mood"),
                   "sleep_hours": d.get("sleep_hours"), "work_hours": d.get("work_hours"),
                   "stress": d.get("stress")} for d in history[-14:]]
        lines.append(f"Последние дни (для поиска закономерностей): {json.dumps(trend, ensure_ascii=False)}")
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
                          weight_warning: str | None = None) -> str:
    context = _format_context(today, history, goal, insights, baseline, now=now, meals=meals,
                               meal_totals=meal_totals, activities=activities, dialog=dialog,
                               applied_edits=applied_edits, weight_warning=weight_warning)
    prompt = f"{context}\n\nСообщение пользователя только что: \"{user_message}\"\n\nНапиши ответ."
    return await call_text(_build_system(user), prompt, max_tokens=2000)
