from openai import AsyncOpenAI
from app.config import OPENAI_API_KEY

client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


async def transcribe(audio_path: str) -> str:
    if client is None:
        raise RuntimeError("OPENAI_API_KEY не задан — добавь его в .env для распознавания голоса")
    with open(audio_path, "rb") as f:
        result = await client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="ru",
        )
    return result.text
