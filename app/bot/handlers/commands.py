from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from app.repositories import user_repo
from app.bot.keyboards import main_menu

router = Router()


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
