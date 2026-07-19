import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

import db
import handlers_organizer
import handlers_player

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]

dp = Dispatcher()
dp.include_router(handlers_organizer.router)
dp.include_router(handlers_player.router)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await db.init_db()
    bot = Bot(token=BOT_TOKEN)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
