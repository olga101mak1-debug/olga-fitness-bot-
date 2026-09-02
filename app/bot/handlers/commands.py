import logging

from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from app.repositories import user_repo
from app.services import life_service
from app.bot.keyboards import main_menu

router = Router()
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def start(message: Message):
    user_repo.set_chat_id(message.chat.id)
    await message.answer(
        "Привет! Я LIFE AI — твой личный помощник по здоровью и образу жизни.\n\n"
        "Просто пиши или говори голосом, как прошёл день — вес, сон, работа, тренировки, самочувствие. "
        "Я сам разберусь, что куда записать, и не буду спрашивать то, что уже знаю.",
        reply_markup=main_menu,
    )


@router.message(Command("menu"))
async def menu(message: Message):
    await message.answer("Меню:", reply_markup=main_menu)


@router.message(Command("stats", "statistics"))
async def stats(message: Message):
    """Полная статистика по всей истории — цифры считаются из базы, а не моделью."""
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        await message.answer(life_service.full_stats_text())
    except Exception:
        logger.exception("Stats command failed")
        await message.answer("Что-то пошло не так на моей стороне — попробуй ещё раз через минуту.")
