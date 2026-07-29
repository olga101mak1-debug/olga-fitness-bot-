import json
from app.services.ai.claude_client import call_tool

PARSER_SYSTEM = """Ты — модуль извлечения структурированных данных из дневниковой записи пользователя о своём дне.
Извлекай ТОЛЬКО то, что явно упомянуто в тексте. Ничего не придумывай и не оценивай "по умолчанию".
Если что-то не упомянуто — оставляй поле пустым (null / не включай в массив).
Настроение, энергию, стресс оценивай по шкале 1–10, если пользователь дал качественное описание
("устала", "отличное настроение") — переведи в разумное число по шкале; если сомневаешься — оставь null.
Единицы: вес в кг, замеры в см, сон в часах, вода в литрах, белок в граммах, работа в часах, шаги — целое число.

Отдельное правило про еду: если пользователь описал, что съел или выпил — заполни массив meals.
Здесь оценка нутриентов не только разрешена, но и обязательна: посчитай калории и БЖУ разумной средней
оценкой по описанию, на всю съеденную порцию (это ожидаемая оценка, а не выдумка). Если размер порции
не назван — считай обычную бытовую порцию. Каждое блюдо/напиток — отдельным элементом массива.
Напитки без калорий (вода, чёрный кофе, чай без сахара) в meals не добавляй.
Если про еду в сообщении ничего нет — оставь meals пустым."""

EXTRACT_TOOL = {
    "name": "extract_life_data",
    "description": "Извлечь структурированные данные о дне пользователя из свободного текста",
    "input_schema": {
        "type": "object",
        "properties": {
            "weight": {"type": "number", "description": "Вес в кг"},
            "waist": {"type": "number", "description": "Талия в см"},
            "belly": {"type": "number", "description": "Живот в см"},
            "hips": {"type": "number", "description": "Бёдра в см"},
            "neck": {"type": "number", "description": "Шея в см"},
            "chest": {"type": "number", "description": "Грудь в см"},
            "sleep_hours": {"type": "number"},
            "sleep_quality": {"type": "integer", "minimum": 1, "maximum": 10},
            "energy": {"type": "integer", "minimum": 1, "maximum": 10},
            "mood": {"type": "integer", "minimum": 1, "maximum": 10},
            "stress": {"type": "integer", "minimum": 1, "maximum": 10},
            "work_hours": {"type": "number"},
            "work_load": {"type": "string", "description": "Краткая характеристика нагрузки: высокая/средняя/низкая или своими словами"},
            "steps": {"type": "integer"},
            "water_liters": {"type": "number"},
            "protein_g": {"type": "number"},
            "alcohol": {"type": "string", "description": "Что и сколько выпито, если упомянуто"},
            "nutrition_event": {"type": "string", "description": "Особое событие в питании (праздник, срыв, гости и т.п.)"},
            "training": {"type": "string", "description": "Краткая сводка активности одной строкой, если не влезает в activities"},
            "comment": {"type": "string", "description": "Любая другая заметка о дне, не попавшая в другие поля"},
            "meals": {
                "type": "array",
                "description": "Съеденное и выпитое, названное в сообщении. Нутриенты — на всю съеденную порцию",
                "items": {
                    "type": "object",
                    "properties": {
                        "dish": {"type": "string", "description": "Что съедено, с размером порции если назван"},
                        "calories": {"type": "number"},
                        "protein": {"type": "number", "description": "г"},
                        "fat": {"type": "number", "description": "г"},
                        "carbs": {"type": "number", "description": "г"},
                        "calcium": {"type": "number", "description": "мг"},
                        "fiber": {"type": "number", "description": "г"},
                    },
                    "required": ["dish"],
                },
            },
            "activities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "description": "йога/силовая/бадминтон/плавание/кардио/прогулка/другое"},
                        "minutes": {"type": "integer"},
                        "comment": {"type": "string"},
                    },
                    "required": ["type"],
                },
            },
            "medications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"drug": {"type": "string"}, "dosage": {"type": "string"}},
                    "required": ["drug"],
                },
            },
            "context_tags": {
                "type": "array",
                "description": "Теги контекста дня: болезнь/отпуск/путешествие/стресс/праздник/гости/ремонт/дедлайн/командировка",
                "items": {
                    "type": "object",
                    "properties": {"event_type": {"type": "string"}, "description": {"type": "string"}},
                    "required": ["event_type"],
                },
            },
            "illness": {
                "type": "object",
                "description": "Заполнять, только если явно упомянута болезнь/симптомы, начавшиеся сегодня",
                "properties": {
                    "diagnosis": {"type": "string"},
                    "symptoms": {"type": "string"},
                },
            },
            "illness_resolved": {"type": "boolean", "description": "true, если пользователь сообщил, что выздоровела/болезнь прошла"},
        },
    },
}


async def parse(text: str) -> dict:
    return await call_tool(PARSER_SYSTEM, text, EXTRACT_TOOL, max_tokens=1500)


MEAL_CORRECTION_SYSTEM = """Пользователь недавно получил разбор фото еды (описание и нутриенты — даны ниже).
Определи, является ли ЕГО НОВОЕ сообщение поправкой/уточнением к этому конкретному приёму пищи
(например называет другой ингредиент, уточняет вес порции, говорит "это не то", "на самом деле...")
— или это не связано с едой вовсе (тогда is_correction=false, остальные поля не заполняй).
Если это поправка — пересчитай нутриенты с учётом новой информации (сохрани то, что не меняется,
пересчитай то, что затронуто поправкой) и верни обновлённые цифры на всю порцию."""

MEAL_CORRECTION_TOOL = {
    "name": "meal_correction",
    "description": "Определить, является ли сообщение поправкой к последнему приёму пищи, и пересчитать нутриенты",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_correction": {"type": "boolean"},
            "dish": {"type": "string"},
            "calories": {"type": "number"},
            "protein": {"type": "number"},
            "fat": {"type": "number"},
            "carbs": {"type": "number"},
            "calcium": {"type": "number"},
            "fiber": {"type": "number"},
        },
        "required": ["is_correction"],
    },
}


async def detect_meal_correction(text: str, previous_meal: dict) -> dict:
    prompt = f"Предыдущий разбор блюда: {json.dumps(previous_meal, ensure_ascii=False)}\n\nНовое сообщение пользователя: \"{text}\""
    return await call_tool(MEAL_CORRECTION_SYSTEM, prompt, MEAL_CORRECTION_TOOL, max_tokens=400)
