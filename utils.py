import logging

from aiogram import Bot

import menu

logger = logging.getLogger(__name__)


async def broadcast(bot: Bot, user_ids: list[int], text: str) -> None:
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, text)
        except Exception:
            logger.warning("Failed to send message to %s", user_id, exc_info=True)


async def broadcast_with_menu(bot: Bot, user_ids: list[int], text: str) -> None:
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, text, reply_markup=await menu.build_menu(user_id))
        except Exception:
            logger.warning("Failed to send message to %s", user_id, exc_info=True)
