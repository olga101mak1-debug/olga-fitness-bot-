import base64
import re
import anthropic
from config import ANTHROPIC_API_KEY, USER
from foods_nha_trang import get_high_protein_suggestions

client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = f"""Ты фитнес-ассистент для Ольги, 46 лет, Нячанг, Вьетнам.
Цели/день: белок {USER['protein_goal_g']}г, калории {USER['calories_goal_kcal']} ккал, кальций {USER['calcium_goal_mg']} мг, клетчатка {USER['fiber_goal_g']}г.
Оземпик (аппетит снижен — белок и кальций критически важны), предменопауза.
Не любит: субпродукты, внутренности, сладкое.
Стиль: честный, конкретный, без лишних слов. Русский язык."""


def parse_kbju(text: str) -> dict:
    """Парсит КБЖУ + кальций + клетчатку из ответа Claude"""
    result = {"calories": 0, "protein": 0, "fat": 0, "carbs": 0, "calcium": 0, "fiber": 0}
    patterns = {
        "calories": r"калори[ий][^\d]*(\d+(?:\.\d+)?)",
        "protein":  r"бело[кг][^\d]*(\d+(?:\.\d+)?)",
        "fat":      r"жир[ыа]?[^\d]*(\d+(?:\.\d+)?)",
        "carbs":    r"углевод[ыа]?[^\d]*(\d+(?:\.\d+)?)",
        "calcium":  r"кальци[йя][^\d]*(\d+(?:\.\d+)?)",
        "fiber":    r"клетчатк[аи][^\d]*(\d+(?:\.\d+)?)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text.lower())
        if match:
            result[key] = float(match.group(1))
    return result


_FOOD_FORMAT = (
    "Блюдо: [название]\n"
    "Калории: [число]\n"
    "Белок: [число]г\n"
    "Жиры: [число]г\n"
    "Углеводы: [число]г\n"
    "Кальций: [число] мг\n"
    "Клетчатка: [число]г\n"
    "Комментарий: [1 предложение — качество блюда для целей Ольги]"
)


async def analyze_food_photo(image_bytes: bytes) -> dict:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}
                },
                {
                    "type": "text",
                    "text": f"Что это за блюдо? Оцени нутриенты на всю порцию.\n\nОтветь строго в формате:\n{_FOOD_FORMAT}"
                }
            ]
        }]
    )
    text = response.content[0].text
    kbju = parse_kbju(text)
    return {"text": text, **kbju}


async def analyze_food_text(description: str) -> dict:
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=350,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Оцени нутриенты: {description}\n\nОтветь строго в формате:\n{_FOOD_FORMAT}"
        }]
    )
    text = response.content[0].text
    kbju = parse_kbju(text)
    return {"text": text, **kbju}


async def get_protein_suggestion(current_protein: float, target_protein: float) -> str:
    needed = target_protein - current_protein
    if needed <= 0:
        return "Белок выполнен!"

    foods = get_high_protein_suggestions(needed)
    foods_text = "\n".join(foods)

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Ольге нужно добрать ещё {needed:.0f}г белка. Она в Нячанге, на Оземпике (аппетит снижен).\n"
                       f"Топ продуктов здесь:\n{foods_text}\n\n"
                       "Порекомендуй 2-3 конкретных варианта. Коротко и по делу."
        }]
    )
    return response.content[0].text


async def generate_evening_summary(totals: dict, log: dict, target_protein: int, target_cal: int) -> str:
    protein_pct = (totals["protein"] / target_protein * 100) if target_protein else 0
    cal_pct = (totals["calories"] / target_cal * 100) if target_cal else 0
    calcium_goal = USER.get("calcium_goal_mg", 1200)
    fiber_goal = USER.get("fiber_goal_g", 28)
    steps_goal = USER.get("steps_goal", 8000)

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"""Итог дня Ольги:
- Калории: {totals['calories']:.0f}/{target_cal} ккал ({cal_pct:.0f}%)
- Белок: {totals['protein']:.0f}/{target_protein}г ({protein_pct:.0f}%)
- Жиры: {totals['fat']:.0f}г, Углеводы: {totals['carbs']:.0f}г
- Кальций: ~{totals.get('calcium', 0):.0f}/{calcium_goal} мг
- Клетчатка: {totals.get('fiber', 0):.0f}/{fiber_goal}г
- Шаги: {log.get('steps') or '—'}/{steps_goal}
- Сон вчера: {log['sleep'] or 'не записан'} ч
- Тренировка: {log['workout'] or 'не было'}
- Омега-3: {'принята' if log['omega3'] else 'не принята'}

Напиши честный итог дня (4-5 предложений). Акцентируй:
- если была силовая тренировка и белок < 90% — это критично: мышцы не восстановятся, объясни последствия
- если был бадминтон или плавание и белок < 80% — тоже важно
- если кальций < 600 мг — упомяни про риск для костей при Оземпике
- если сон < 7ч — скажи про кортизол и висцеральный жир
- если не было тренировки — мягко напомни о плане (силовые 3x, бадминтон 2x/нед)
В конце — одна мотивирующая фраза."""
        }]
    )
    return response.content[0].text
