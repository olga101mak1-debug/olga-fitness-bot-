import json
from app.services.ai.claude_client import call_text

WEEKLY_SYSTEM = """Ты — LIFE AI, персональный аналитик здоровья и образа жизни.
На основе агрегированной статистики за неделю напиши тёплый, честный человеческий вывод (не список цифр —
цифры пользователь уже увидел). 3-5 предложений: что получилось, на что стоит обратить внимание,
одна конкретная мысль на следующую неделю. Без осуждающего тона, без "вы нарушили/следует"."""


async def generate_weekly_report(summary: dict, user: dict) -> str:
    prompt = f"Статистика недели: {json.dumps(summary, ensure_ascii=False)}\n\nПрофиль: {json.dumps(user, ensure_ascii=False)}"
    return await call_text(WEEKLY_SYSTEM, prompt, max_tokens=400)
