import asyncio
import logging

from aiogram import Bot

import menu

logger = logging.getLogger(__name__)


async def _safe_send(bot: Bot, user_id: int, text: str, reply_markup=None) -> None:
    try:
        await bot.send_message(user_id, text, reply_markup=reply_markup)
    except Exception:
        logger.warning("Failed to send message to %s", user_id, exc_info=True)


async def broadcast(bot: Bot, user_ids: list[int], text: str) -> None:
    await asyncio.gather(*(_safe_send(bot, user_id, text) for user_id in user_ids))


async def broadcast_with_menu(bot: Bot, user_ids: list[int], text: str) -> None:
    async def send_one(user_id: int) -> None:
        markup = await menu.build_menu(user_id)
        await _safe_send(bot, user_id, text, reply_markup=markup)

    await asyncio.gather(*(send_one(user_id) for user_id in user_ids))
