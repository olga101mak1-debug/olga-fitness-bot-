"""Разбор сообщений, которые правят УЖЕ СУЩЕСТВУЮЩИЕ записи, а не добавляют новые.

Раньше бот умел только добавлять еду и править последнюю запись за день. Из-за этого:
— на просьбу «убери дубль» он отвечал «убрала», но в базе ничего не менялось;
— вопрос «откуда тут 1050 ккал?» парсер принимал за описание еды и создавал новый дубль.

Этот модуль отделяет «новая запись» от «правка» и от «вопрос» и возвращает список
конкретных операций над записями с известными id.
"""
import json

from app.services.ai.claude_client import call_tool

RECORD_EDITOR_SYSTEM = """Ты — модуль редактирования дневника питания и тренировок.
Ниже дан список УЖЕ СОХРАНЁННЫХ записей с их id и новое сообщение пользователя.

Твоя задача — понять, что пользователь хочет сделать, и вернуть message_kind и список операций.

message_kind:
— "new_entry" — пользователь сообщает о НОВОЙ еде/тренировке/показателе, которой ещё нет в списке;
— "edit_request" — пользователь правит уже сохранённую запись: это дубль, это было вчера,
  это другое блюдо, порция другая, удали, убери, перенеси, «не X, а Y», «та же порция»;
— "question" — пользователь спрашивает или возмущается по поводу цифр, но не даёт новых данных:
  «откуда 1050 ккал?», «как ты посчитал?», «25 г мюслей это по-твоему 114 ккал?», «ты неправильно посчитал»;
— "other" — всё остальное (самочувствие, разговор, просьба совета).

КРИТИЧЕСКИ ВАЖНО:
— Вопрос о цифрах — это НИКОГДА не новая еда. Если человек перечисляет продукты внутри вопроса
  («откуда молоко, казеин, мюсли, банан — 1050 ккал?»), он спрашивает про СУЩЕСТВУЮЩУЮ запись,
  а не сообщает о новой еде. Это message_kind="question".
— Фразы «та же порция», «это был один приём», «это то же самое» означают ДУБЛЬ: нужна операция
  delete для лишней записи, а не новая запись.
— У каждой записи есть приём пищи (завтрак/обед/ужин/перекус) и время еды. Опирайся на них,
  когда пользователь уточняет: «убери второй завтрак», «то, что я ела в обед, было больше»,
  «утренний творог был 250 г». Если правка названа через приём пищи — бери запись именно
  этого приёма, а не последнюю по списку.
— «Это был не ужин, а перекус» — это update с новым meal_type, а не удаление.
— Операции ставь ТОЛЬКО на id из списка ниже. Не выдумывай id.
— Если пользователь говорит, что запись относится к другому дню («это я ела вчера») — операция move.
— Если ничего менять не надо — верни пустой список операций.
— Не удаляй записи «на всякий случай». Удаляй только то, что пользователь явно назвал лишним,
  дублем, ошибкой или чужим днём."""

RECORD_EDITOR_TOOL = {
    "name": "plan_record_edits",
    "description": "Определить тип сообщения и операции над уже сохранёнными записями",
    "input_schema": {
        "type": "object",
        "properties": {
            "message_kind": {
                "type": "string",
                "enum": ["new_entry", "edit_request", "question", "other"],
            },
            "operations": {
                "type": "array",
                "description": "Операции над существующими записями. Пустой список, если менять нечего.",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["delete", "move", "update"]},
                        "target": {"type": "string", "enum": ["meal", "activity"]},
                        "id": {"type": "integer", "description": "id записи из списка"},
                        "new_date": {
                            "type": "string",
                            "description": "Только для move: дата в формате YYYY-MM-DD из списка допустимых дат",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Коротко, почему: дубль / другой день / ошибка в блюде",
                        },
                        "dish": {"type": "string", "description": "Только для update приёма пищи"},
                        "meal_type": {
                            "type": "string",
                            "enum": ["завтрак", "обед", "ужин", "перекус"],
                            "description": "Только для update: перенести запись в другой приём пищи "
                                           "(«это был не ужин, а перекус»)",
                        },
                        "calories": {"type": "number"},
                        "protein": {"type": "number", "description": "г"},
                        "fat": {"type": "number", "description": "г"},
                        "carbs": {"type": "number", "description": "г"},
                        "calcium": {"type": "number", "description": "мг"},
                        "fiber": {"type": "number", "description": "г"},
                        "type": {"type": "string", "description": "Только для update активности"},
                        "minutes": {"type": "integer"},
                        "comment": {"type": "string"},
                    },
                    "required": ["action", "target", "id"],
                },
            },
        },
        "required": ["message_kind", "operations"],
    },
}


async def plan_edits(text: str, meals: list[dict], activities: list[dict],
                     allowed_dates: list[str]) -> dict:
    """Вернуть {"message_kind": ..., "operations": [...]}. При сбое — безопасный пустой результат."""
    snapshot = {
        "приёмы_пищи": [
            {"id": m["id"], "дата": m["date"],
             "приём": m.get("meal_type"), "время_еды": m.get("eaten_at"),
             "время_записи": (m.get("created_at") or "")[11:16],
             "блюдо": m.get("description"), "ккал": m.get("calories"), "белок": m.get("protein")}
            for m in meals
        ],
        "активности": [
            {"id": a["id"], "дата": a["date"], "тип": a.get("type"), "минут": a.get("minutes")}
            for a in activities
        ],
        "допустимые_даты_для_move": allowed_dates,
    }
    prompt = (
        f"Сохранённые записи:\n{json.dumps(snapshot, ensure_ascii=False, indent=1)}\n\n"
        f"Новое сообщение пользователя: \"{text}\""
    )
    result = await call_tool(RECORD_EDITOR_SYSTEM, prompt, RECORD_EDITOR_TOOL, max_tokens=900)
    if not isinstance(result, dict):
        return {"message_kind": "other", "operations": []}
    result.setdefault("message_kind", "other")
    result.setdefault("operations", [])
    if not isinstance(result["operations"], list):
        result["operations"] = []
    return result
