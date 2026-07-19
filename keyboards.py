from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

SIZES = [4, 9, 16, 25]


def size_keyboard() -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text=str(s), callback_data=f"newgame:size:{s}") for s in SIZES]
    return InlineKeyboardMarkup(inline_keyboard=[row])


def yes_no_keyboard(action: str, payload: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data=f"{action}:{payload}:yes"),
                InlineKeyboardButton(text="Нет", callback_data=f"{action}:{payload}:no"),
            ]
        ]
    )


def card_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Подтвердить карточку ✅", callback_data="card:confirm")]]
    )


def done_filling_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Закончить заполнение", callback_data="donefilling")]]
    )


def edit_slot_cancel_keyboard(player_id: int, idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data=f"editcancel:{player_id}:{idx}")]]
    )


def games_pick_keyboard(games) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=g["title"], callback_data=f"setcurrent:{g['id']}")] for g in games]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def player_games_keyboard(games) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{g['title']} ({g['status']})", callback_data=f"playergame:{g['id']}")]
        for g in games
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def player_game_manage_keyboard(game_id: int, is_current: bool) -> InlineKeyboardMarkup:
    rows = []
    if not is_current:
        rows.append(
            [InlineKeyboardButton(text="✅ Сделать текущей игрой", callback_data=f"setcurrent:{game_id}")]
        )
    rows.append([InlineKeyboardButton(text="🚪 Покинуть игру", callback_data=f"leavegame_request:{game_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def editcard_slots_keyboard(player_id: int, slots) -> InlineKeyboardMarkup:
    rows = []
    for s in slots:
        label = f"{s['idx'] + 1}. {s['text']}" if s["text"] else f"{s['idx'] + 1}. (пусто)"
        rows.append([InlineKeyboardButton(text=label[:60], callback_data=f"editslot:{player_id}:{s['idx']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mygames_keyboard(games) -> InlineKeyboardMarkup:
    rows = []
    for g in games:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{g['title']} ({g['status']})", callback_data=f"game:manage:{g['id']}"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def manage_game_keyboard(game, has_own_card: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if game["status"] == "draft":
        rows.append([InlineKeyboardButton(text="🚀 Начать игру", callback_data=f"game:start:{game['id']}")])
        if has_own_card:
            rows.append(
                [InlineKeyboardButton(text="↩️ К моей карточке", callback_data=f"returncard:{game['id']}")]
            )
        rows.append([InlineKeyboardButton(text="🔗 Ссылка-приглашение", callback_data=f"game:link:{game['id']}")])
        rows.append([InlineKeyboardButton(text="🗑 Удалить игру", callback_data=f"game:delete:{game['id']}")])
    elif game["status"] == "active":
        rows.append([InlineKeyboardButton(text="🔗 Ссылка-приглашение", callback_data=f"game:link:{game['id']}")])
        rows.append([InlineKeyboardButton(text="🏁 Таблица лидеров", callback_data=f"game:leaderboard:{game['id']}")])
        rows.append([InlineKeyboardButton(text="⛔ Завершить игру", callback_data=f"game:end:{game['id']}")])
    else:
        rows.append([InlineKeyboardButton(text="🏁 Итоги", callback_data=f"game:leaderboard:{game['id']}")])
        rows.append([InlineKeyboardButton(text="🗑 Удалить игру насовсем", callback_data=f"game:delete:{game['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
