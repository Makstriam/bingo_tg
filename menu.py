from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

import db

BTN_NEWGAME = "🎲 Создать игру"
BTN_MYGAMES = "🗂 Мои игры"
BTN_CARD = "🎯 Моя карточка"
BTN_PLAYERS = "👥 Игроки"
BTN_LEADERBOARD = "🏆 Лидеры"
BTN_UNDO = "↩️ Отменить отметку"
BTN_SETTINGS = "⚙️ Настройки"
BTN_EDITCARD = "✏️ Редактировать карточку"
BTN_FINISH_EDITING = "✅ Завершить редактирование"


ALL_BUTTONS = {
    BTN_NEWGAME,
    BTN_MYGAMES,
    BTN_CARD,
    BTN_PLAYERS,
    BTN_LEADERBOARD,
    BTN_UNDO,
    BTN_SETTINGS,
    BTN_EDITCARD,
    BTN_FINISH_EDITING,
}


def _kb(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label) for label in row] for row in rows],
        resize_keyboard=True,
    )


def editmode_menu() -> ReplyKeyboardMarkup:
    return _kb([[BTN_FINISH_EDITING]])


async def build_menu(user_id: int) -> ReplyKeyboardMarkup:
    active_games = await db.get_active_games_for_user(user_id)
    player_games = await db.get_player_games_for_user(user_id)
    draft_games = [g for g in player_games if g["status"] == "draft"]
    organizer_games = await db.get_games_by_organizer(user_id)

    rows: list[list[str]] = []
    if active_games:
        rows.append([BTN_CARD, BTN_PLAYERS])
        rows.append([BTN_LEADERBOARD, BTN_UNDO])
    if draft_games:
        rows.append([BTN_EDITCARD])
    if active_games or draft_games:
        rows.append([BTN_SETTINGS])
    if organizer_games:
        rows.append([BTN_MYGAMES])
    rows.append([BTN_NEWGAME])
    return _kb(rows)
