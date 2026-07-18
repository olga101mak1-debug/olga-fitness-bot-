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

Если не хватает по-настоящему важной информации за сегодня — задай не более {MAX_CLARIFYING_QUESTIONS}
уточняющих вопросов, максимально коротких. Никогда не спрашивай то, что уже записано сегодня (см. "Уже известно за сегодня").
Если всё важное уже есть — просто дай тёплый, конкретный отклик на день, без вопросов.
Если видишь связь с последними днями (например, третий день подряд мало сна, или работала по 11 часов —
и упало настроение) — мягко отметь это как наблюдение, а не как претензию.
Отвечай по-русски, живо, 3-6 предложений."""


def _format_context(today: dict, history: list[dict], goal: dict | None, insights: list[dict],
                     baseline: dict | None = None) -> str:
    known = {k: v for k, v in today.items() if v is not None and k != "date"}
    lines = [
        f"Сегодня ({today.get('date')}), уже известно за сегодня: {json.dumps(known, ensure_ascii=False)}",
    ]
    if baseline:
        lines.append(
            "Точка старта наблюдений (используй ТОЛЬКО эту дату и эти цифры для любых формулировок "
            f"«с начала»/«всего прогресс», не путай с окном ниже): {json.dumps(baseline, ensure_ascii=False)}"
        )
    if history:
        trend = [{"date": d["date"], "weight": d.get("weight"), "mood": d.get("mood"),
                   "sleep_hours": d.get("sleep_hours"), "work_hours": d.get("work_hours"),
                   "stress": d.get("stress")} for d in history[-14:]]
        lines.append(f"Последние дни (для поиска закономерностей): {json.dumps(trend, ensure_ascii=False)}")
    if goal:
        lines.append(f"Активная цель: {json.dumps(goal, ensure_ascii=False)}")
    if insights:
        lines.append(f"Ранее замеченные закономерности: {json.dumps(insights, ensure_ascii=False)}")
    return "\n\n".join(lines)


async def generate_reply(today: dict, history: list[dict], goal: dict | None,
                          insights: list[dict], user: dict, user_message: str,
                          baseline: dict | None = None) -> str:
    context = _format_context(today, history, goal, insights, baseline)
    prompt = f"{context}\n\nСообщение пользователя только что: \"{user_message}\"\n\nНапиши ответ."
    return await call_text(_build_system(user), prompt, max_tokens=500)
