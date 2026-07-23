import anthropic
from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


async def call_tool(system: str, user_message: str, tool_schema: dict, max_tokens: int = 800) -> dict:
    """Форсирует вызов инструмента с заданной JSON-схемой и возвращает его input."""
    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system,
        tools=[tool_schema],
        tool_choice={"type": "tool", "name": tool_schema["name"]},
        messages=[{"role": "user", "content": user_message}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    return {}


async def call_text(system: str, user_message: str, max_tokens: int = 500) -> str:
    for attempt in range(2):
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        if text:
            return text
    return "Не получилось сформулировать ответ с первого раза — спроси ещё раз, возможно чуть иначе."
