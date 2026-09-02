import logging

from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import (Message, BufferedInputFile,
                           InlineKeyboardMarkup, InlineKeyboardButton)

from app.repositories import user_repo
from app.services import life_service
from app.bot.keyboards import main_menu
from app.config import WEB_DASHBOARD_URL

router = Router()
logger = logging.getLogger(__name__)
ERROR_TEXT = "Что-то пошло не так на моей стороне — попробуй ещё раз через минуту."


@router.message(CommandStart())
async def start(message: Message):
    user_repo.set_chat_id(message.chat.id)
    await message.answer(
        "Привет! Я LIFE AI — твой личный помощник по здоровью и образу жизни.\n\n"
        "Просто пиши или говори голосом, как прошёл день — вес, сон, работа, тренировки, самочувствие. "
        "Я сама разберусь, что куда записать, и не буду спрашивать то, что уже знаю.\n\n"
        "Кнопки внизу всегда под рукой: сводка за сегодня, вся статистика, итог недели, "
        "графики, дашборд и выгрузка таблиц.",
        reply_markup=main_menu,
    )


@router.message(Command("menu"))
async def menu(message: Message):
    await message.answer("Кнопки внизу экрана.", reply_markup=main_menu)


@router.message(Command("stats", "statistics"))
async def stats(message: Message):
    """Полная статистика по всей истории — цифры считаются из базы, а не моделью."""
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        await message.answer(life_service.full_stats_text())
    except Exception:
        logger.exception("Stats command failed")
        await message.answer(ERROR_TEXT)


@router.message(Command("dashboard"))
async def dashboard(message: Message):
    """Ссылка на живой дашборд. Файл не шлём: в Telegram он открывается без кнопок."""
    if not WEB_DASHBOARD_URL:
        await message.answer("Адрес дашборда не настроен — напиши мне, я поправлю.")
        return
    await message.answer(
        "🖥 Дашборд с выбором месяцев, недель и вкладками:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Открыть дашборд", url=WEB_DASHBOARD_URL)]
        ]),
    )


@router.message(Command("export"))
async def export(message: Message):
    """Первичка таблицами: по дням и по каждому приёму пищи."""
    await message.bot.send_chat_action(message.chat.id, "upload_document")
    try:
        for filename, content in life_service.export_tables():
            await message.answer_document(BufferedInputFile(content, filename=filename))
        await message.answer("Это вся первичка. Открывается в Excel и Google Таблицах.")
    except Exception:
        logger.exception("Export command failed")
        await message.answer(ERROR_TEXT)
