from aiogram import Bot, Dispatcher

from app.config import BOT_TOKEN
from app.bot.handlers import commands, menu, photos, messages


def create_bot() -> Bot:
    return Bot(token=BOT_TOKEN)


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(commands.router)
    dp.include_router(menu.router)
    dp.include_router(photos.router)
    dp.include_router(messages.router)
    return dp
