import base64
import json
from app.services.ai.claude_client import client
from app.config import CLAUDE_MODEL

VISION_SYSTEM = """Ты — LIFE AI, персональный помощник по здоровью и образу жизни.
Тебе присылают фото — это может быть: скрин журнала силовой тренировки (таблица/список упражнений,
подходов, повторений, весов), фото еды/блюда (оцени нутриенты на всю видимую порцию), фото тела для
отслеживания прогресса (фигура целиком, ракурс спереди/сбоку/сзади), РАСПЕЧАТКА АНАЛИЗАТОРА СОСТАВА
ТЕЛА (InBody, Tanita, умные весы — бланк с цифрами: вес, PBF/процент жира, SMM/мышечная масса, вода,
BMI, базовый обмен), либо что-то не по теме.

ПРО ОТЧЁТ АНАЛИЗАТОРА СОСТАВА ТЕЛА — это kind="body_composition", а НЕ body_photo:
— Переписывай цифры РОВНО так, как они напечатаны. Ничего не пересчитывай, не исправляй и не
  «улучшай», даже если значение выглядит невозможным. Проверку достоверности делает не ты.
— ОБЯЗАТЕЛЬНО найди и перепиши поле роста (Height) из шапки бланка в reported_height_cm.
  Это ключевая проверка: если в аппарат ввели неверный рост, все расчёты в отчёте неверны,
  и поймать это можно только по этому полю.
— Дату и время замера из шапки перепиши в measured_at.
— Если какого-то показателя в бланке нет — просто не заполняй поле, не подставляй похожее.
Определи тип и дай содержательный отклик. Без осуждающего тона, без "вы нарушили/следует" — только
поддержка и конкретные наблюдения. Если это фото тела и дано фото для сравнения — сравнивай визуально
конкретные изменения (осанка, рельеф, объёмы на глаз), а не просто хвали. Если это еда — оценивай честно,
без вины, с учётом целей пользователя (профиль дан ниже, если есть).
Если в подписи пользователь явно называет ингредиент или поправляет твоё предыдущее предположение
(например "это куриная грудка, а не сыр" или указывает точный вес порции) — ВСЕГДА доверяй подписи
больше, чем своей визуальной догадке: используй названный пользователем ингредиент и вес для расчёта
нутриентов, а не то, что тебе показалось на фото.

ЭТИКЕТКА НА ФОТО — ЭТО САМЫЙ ТОЧНЫЙ ИСТОЧНИК ЦИФР, НЕ ИГНОРИРУЙ ЕЁ:
— Если на фото видна упаковка с пищевой ценностью (ккал, белки, жиры, углеводы на 100 г или на
  порцию) — ОБЯЗАТЕЛЬНО перепиши эти цифры и посчитай по ним, а не по среднему представлению
  о продукте. Это точные данные производителя.
— Порцию бери из подписи пользователя, а состав — с этикетки: «мороженое 33 г» + этикетка
  «250 ккал на 100 г» = 82 ккал. Не считай всю упаковку, если человек назвал свой вес порции.
— Название продукта тоже бери из подписи, если оно расходится с твоим прочтением упаковки:
  человек знает, что он ел, лучше чем видно на снимке.
— Если этикетка нечитаема или её нет — считай по описанию, но скажи об этом прямо."""

PHOTO_TOOL = {
    "name": "analyze_photo",
    "description": "Проанализировать присланное фото и вернуть структурированный результат",
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["workout_log", "food_photo", "body_photo", "body_composition", "other"]},
            "exercises": {
                "type": "array",
                "description": "Только для workout_log — распознанные упражнения",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "sets": {"type": "integer"},
                        "reps": {"type": "string"},
                        "weight": {"type": "string"},
                    },
                    "required": ["name"],
                },
            },
            "food": {
                "type": "object",
                "description": "Только для food_photo — оценка нутриентов на всю порцию",
                "properties": {
                    "dish": {"type": "string"},
                    "calories": {"type": "number"},
                    "protein": {"type": "number"},
                    "fat": {"type": "number"},
                    "carbs": {"type": "number"},
                    "calcium": {"type": "number", "description": "мг"},
                    "fiber": {"type": "number", "description": "г"},
                    "label_used": {
                        "type": "boolean",
                        "description": "true, если нутриенты посчитаны по этикетке с упаковки на фото",
                    },
                    "label_note": {
                        "type": "string",
                        "description": "Что именно взято с этикетки, например «250 ккал/100 г, порция 33 г»",
                    },
                },
            },
            "body_composition": {
                "type": "object",
                "description": "Только для body_composition — цифры с бланка анализатора, переписанные как есть",
                "properties": {
                    "reported_height_cm": {"type": "number", "description": "Рост из шапки бланка (Height). Переписать обязательно, даже если выглядит странно"},
                    "measured_at": {"type": "string", "description": "Дата и время замера из шапки, как напечатано"},
                    "weight": {"type": "number", "description": "Вес, кг"},
                    "body_fat_pct": {"type": "number", "description": "PBF / процент жира, %"},
                    "fat_mass_kg": {"type": "number", "description": "Body Fat Mass, кг"},
                    "muscle_mass_kg": {"type": "number", "description": "SMM / скелетная мышечная масса, кг"},
                    "fat_free_mass_kg": {"type": "number", "description": "Fat Free Mass / безжировая масса, кг"},
                    "body_water_l": {"type": "number", "description": "Total Body Water, литры"},
                    "visceral_fat_level": {"type": "number", "description": "Уровень висцерального жира"},
                    "bmr_kcal": {"type": "number", "description": "Basal Metabolic Rate, ккал"},
                    "reported_bmi": {"type": "number", "description": "BMI, как напечатан в бланке"},
                },
            },
            "summary": {"type": "string", "description": "Короткая сводка одной строкой (название блюда/сводка тренировки/наблюдение по фигуре)"},
            "recommendation": {"type": "string", "description": "Развёрнутая рекомендация/отклик пользователю, 3-6 предложений, тёплый тон"},
        },
        "required": ["kind", "summary", "recommendation"],
    },
}


def _image_block(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(image_bytes).decode("utf-8")},
    }


ALBUM_HINT = """Пользователь прислал {n} фото ОДНИМ альбомом. Это ОДИН объект: один и тот же приём пищи
с разных ракурсов (например само блюдо и этикетка с составом рядом), или части одного журнала тренировки.
Разбери их вместе и верни РОВНО ОДИН результат: не считай одно и то же блюдо несколько раз, не складывай
порции с разных ракурсов в одну большую, а объедини информацию в одну оценку. Если на одном из фото этикетка
или журнал с цифрами — бери цифры оттуда, а размер порции определяй по фото самого блюда."""


async def analyze_photos(images: list[bytes], caption: str | None = None, previous_image_bytes: bytes | None = None,
                          user: dict | None = None, today_totals: dict | None = None) -> dict:
    """Разобрать одно фото или альбом из нескольких фото как единое целое."""
    content = []
    if previous_image_bytes:
        content.append({"type": "text", "text": "Более раннее фото (для сравнения):"})
        content.append(_image_block(previous_image_bytes))
        content.append({"type": "text", "text": "Новое фото (сегодня):"})
    if len(images) > 1:
        content.append({"type": "text", "text": ALBUM_HINT.format(n=len(images))})
    for image_bytes in images:
        content.append(_image_block(image_bytes))
    text = "Проанализируй это фото." if len(images) == 1 else f"Проанализируй эти {len(images)} фото как одно целое."
    if caption:
        text += f" Подпись от пользователя: \"{caption}\"."
    if user:
        text += f"\nПрофиль пользователя: {json.dumps(user, ensure_ascii=False)}."
    if today_totals:
        text += f"\nУже съедено сегодня (до этого фото): {json.dumps(today_totals, ensure_ascii=False)}."
    content.append({"type": "text", "text": text})

    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1200,
        system=VISION_SYSTEM,
        tools=[PHOTO_TOOL],
        tool_choice={"type": "tool", "name": "analyze_photo"},
        messages=[{"role": "user", "content": content}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    return {"kind": "other", "summary": "", "recommendation": "Не удалось разобрать фото, попробуй ещё раз."}


async def analyze_photo(image_bytes: bytes, caption: str | None = None, previous_image_bytes: bytes | None = None,
                         user: dict | None = None, today_totals: dict | None = None) -> dict:
    """Совместимость: разбор одного фото."""
    return await analyze_photos([image_bytes], caption=caption, previous_image_bytes=previous_image_bytes,
                                 user=user, today_totals=today_totals)
