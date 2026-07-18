import asyncio
import logging

from app.database.engine import init_db
from app.bot.main import create_bot, create_dispatcher
from app.scheduler.jobs import start_scheduler

logging.basicConfig(level=logging.INFO)


async def main():
    init_db()
    bot = create_bot()
    dp = create_dispatcher()
    start_scheduler(bot)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
