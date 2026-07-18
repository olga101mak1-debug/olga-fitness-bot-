import json
from app.services.ai.claude_client import call_tool

INSIGHT_SYSTEM = """Ты ищешь закономерности в данных о здоровье и образе жизни пользователя за длительный период.
Формулируй только те наблюдения, которые реально подтверждаются данными (минимум 3 повторения паттерна).
Не придумывай причинно-следственных связей без оснований в данных. Пиши по-русски, коротко, по одному предложению
на наблюдение. Если явных закономерностей нет — верни пустой массив."""

INSIGHT_TOOL = {
    "name": "report_insights",
    "description": "Вернуть найденные закономерности в данных пользователя",
    "input_schema": {
        "type": "object",
        "properties": {
            "insights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "сон/настроение/работа/тренировки/вес/другое"},
                        "observation": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    },
                    "required": ["category", "observation", "confidence"],
                },
            }
        },
        "required": ["insights"],
    },
}


async def generate_insights(history: list[dict]) -> list[dict]:
    result = await call_tool(INSIGHT_SYSTEM, json.dumps(history, ensure_ascii=False), INSIGHT_TOOL, max_tokens=800)
    return result.get("insights", [])
