import os
import logging
import tempfile

from aiogram import Router, F
from aiogram.types import Message

from app.services import life_service
from app.services.speech.whisper_client import transcribe

router = Router()
logger = logging.getLogger(__name__)

FRIENDLY_ERROR = "Что-то пошло не так на моей стороне — попробуй ещё раз через минуту."


@router.message(F.voice)
async def handle_voice(message: Message):
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ogg_path = os.path.join(tmp, "voice.ogg")
            file = await message.bot.get_file(message.voice.file_id)
            await message.bot.download_file(file.file_path, ogg_path)
            try:
                text = await transcribe(ogg_path)
            except RuntimeError as e:
                await message.answer(str(e))
                return

        reply = await life_service.process_message(text)
        await message.answer(f"🎙 «{text}»\n\n{reply}")
    except Exception:
        logger.exception("Voice handling failed")
        await message.answer(FRIENDLY_ERROR)


@router.message(F.text)
async def handle_text(message: Message):
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        reply = await life_service.process_message(message.text)
        await message.answer(reply)
    except Exception:
        logger.exception("Text handling failed")
        await message.answer(FRIENDLY_ERROR)
