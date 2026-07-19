import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import card_image
import db
import game_logic
from keyboards import (
    card_confirm_keyboard,
    edit_slot_cancel_keyboard,
    editcard_slots_keyboard,
    done_filling_inline_keyboard,
    games_pick_keyboard,
    player_game_manage_keyboard,
    player_games_keyboard,
    yes_no_keyboard,
)
from menu import (
    ALL_BUTTONS,
    BTN_CARD,
    BTN_EDITCARD,
    BTN_FINISH_EDITING,
    BTN_LEADERBOARD,
    BTN_PLAYERS,
    BTN_SETTINGS,
    BTN_UNDO,
    build_menu,
    editmode_menu,
)
from states import CardFilling, EditSlot
from utils import broadcast

logger = logging.getLogger(__name__)

router = Router()


async def send_card_image(target: Message, game, slots, owner_view: bool, caption: str, reply_markup=None) -> None:
    try:
        photo_bytes = card_image.render_card_image(game, slots, owner_view)
        photo = BufferedInputFile(photo_bytes, filename="card.png")
        await target.answer_photo(photo, caption=caption, reply_markup=reply_markup)
    except Exception:
        logger.exception("Failed to render card image, falling back to text")
        text = game_logic.render_card_text(game, slots, owner_view)
        await target.answer(f"{caption}\n{text}", reply_markup=reply_markup)


async def ask_next_slot(message: Message, player_id: int, game) -> None:
    player = await db.get_player_by_id(player_id)
    idx = player["fill_index"]
    if idx >= game["size"]:
        await message.answer(
            f"Все {game['size']} слотов заполнены!", reply_markup=card_confirm_keyboard()
        )
        return
    await message.answer(
        f"Слот {idx + 1}/{game['size']}: пришли текст предложения для бинго.",
        reply_markup=done_filling_inline_keyboard(),
    )


async def begin_card_filling(message_target: Message, state: FSMContext, game_id: int, game, user) -> int:
    existing = await db.get_player(game_id, user.id)
    if existing:
        player_id = existing["id"]
    else:
        player_id = await db.add_player(game_id, user.id, user.full_name, game["size"])
    await db.set_current_game_id(user.id, game_id)
    await state.set_state(CardFilling.filling)
    await state.update_data(game_id=game_id, player_id=player_id)
    await ask_next_slot(message_target, player_id, game)
    return player_id


async def resolve_current_game(message: Message, silent_if_empty: bool = False):
    games = await db.get_active_games_for_user(message.from_user.id)
    if not games:
        if not silent_if_empty:
            await message.answer("У тебя нет активных игр.")
        return None
    if len(games) == 1:
        await db.set_current_game_id(message.from_user.id, games[0]["id"])
        return games[0]
    current_id = await db.get_current_game_id(message.from_user.id)
    match = next((g for g in games if g["id"] == current_id), None)
    if match:
        return match
    await message.answer(
        "Ты участвуешь в нескольких активных играх — выбери, с какой сейчас работаешь, "
        "и повтори команду:",
        reply_markup=games_pick_keyboard(games),
    )
    return None


async def resolve_draft_game_for_edit(message: Message, silent_if_empty: bool = False):
    games = [g for g in await db.get_player_games_for_user(message.from_user.id) if g["status"] == "draft"]
    if not games:
        if not silent_if_empty:
            await message.answer("Нет игр в статусе подготовки, где можно редактировать карточку.")
        return None
    if len(games) == 1:
        return games[0]
    current_id = await db.get_current_game_id(message.from_user.id)
    match = next((g for g in games if g["id"] == current_id), None)
    if match:
        return match
    await message.answer(
        "У тебя несколько игр в подготовке — выбери, какую карточку редактировать, и повтори команду:",
        reply_markup=games_pick_keyboard(games),
    )
    return None


@router.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject, state: FSMContext) -> None:
    args = command.args or ""
    if not args:
        await message.answer(
            "Привет! Я бот для игры в бинго-предсказания.\n"
            "/newgame — создать новую игру\n"
            "/mygames — мои игры (как организатора)\n"
            "/card — моя карточка в текущей игре\n"
            "/players — список игроков и их карточки\n"
            "/leaderboard — таблица лидеров\n"
            "/undo — отменить последнюю отметку\n"
            "/settings — мои игры: выбрать текущую или покинуть игру\n"
            "/editcard — исправить слот, пока игра не началась",
            reply_markup=await build_menu(message.from_user.id),
        )
        return
    if not args.startswith("join_"):
        await message.answer("Неизвестная ссылка-приглашение.")
        return
    try:
        game_id = int(args.removeprefix("join_"))
    except ValueError:
        await message.answer("Некорректная ссылка-приглашение.")
        return
    game = await db.get_game(game_id)
    if not game:
        await message.answer("Игра не найдена — возможно, ссылка устарела.")
        return
    if game["status"] != "draft":
        await message.answer("В эту игру уже нельзя вступить — она уже началась или завершена.")
        return
    existing = await db.get_player(game_id, message.from_user.id)
    if existing:
        if existing["confirmed"]:
            await message.answer(
                "Ты уже подтвердил(а) участие в этой игре. Используй /card, чтобы посмотреть карточку.",
                reply_markup=await build_menu(message.from_user.id),
            )
        else:
            await begin_card_filling(message, state, game_id, game, message.from_user)
        return
    await message.answer(
        f"Присоединиться к игре «{game['title']}» (организатор: {game['organizer_name']})?",
        reply_markup=yes_no_keyboard("join", str(game_id)),
    )


@router.callback_query(F.data.startswith("join:"))
async def cb_join(callback: CallbackQuery, state: FSMContext) -> None:
    _, game_id_s, answer = callback.data.split(":")
    game_id = int(game_id_s)
    game = await db.get_game(game_id)
    if not game or game["status"] != "draft":
        await callback.message.edit_text("Эта игра больше не принимает участников.", reply_markup=None)
        await callback.answer()
        return
    if answer == "no":
        await callback.message.edit_text("Хорошо, ты не участвуешь в этой игре.", reply_markup=None)
        await callback.answer()
        return
    await callback.message.edit_text(
        f"Ты в игре «{game['title']}»! Заполним карточку из {game['size']} слотов.", reply_markup=None
    )
    await begin_card_filling(callback.message, state, game_id, game, callback.from_user)
    await callback.answer()


@router.message(StateFilter(CardFilling.filling), Command("done"))
async def cmd_done_filling(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    player_id = data["player_id"]
    game = await db.get_game(data["game_id"])
    player = await db.get_player_by_id(player_id)
    remaining = game["size"] - player["fill_index"]
    if remaining <= 0:
        await message.answer("Карточка уже полностью заполнена.", reply_markup=card_confirm_keyboard())
        return
    await message.answer(
        f"Не заполнено ещё {remaining} клеток. Заполнить их пустышками (—) и подтвердить карточку?",
        reply_markup=yes_no_keyboard("filldone", str(player_id)),
    )


@router.callback_query(F.data.startswith("filldone:"))
async def cb_filldone(callback: CallbackQuery) -> None:
    _, player_id_s, answer = callback.data.split(":")
    player_id = int(player_id_s)
    if answer == "no":
        await callback.message.edit_text("Ок, продолжай заполнение.", reply_markup=None)
        await callback.answer()
        return
    player = await db.get_player_by_id(player_id)
    game = await db.get_game(player["game_id"])
    for idx in range(player["fill_index"], game["size"]):
        await db.set_slot_text(player_id, idx, "—")
    await db.set_fill_index(player_id, game["size"])
    await callback.message.edit_text(
        "Пустые клетки заполнены. Подтверди карточку.", reply_markup=card_confirm_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "donefilling")
async def cb_done_filling_request(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    player_id = data.get("player_id")
    if player_id is None:
        await callback.answer("Сессия заполнения не найдена.", show_alert=True)
        return
    game = await db.get_game(data["game_id"])
    player = await db.get_player_by_id(player_id)
    remaining = game["size"] - player["fill_index"]
    if remaining <= 0:
        await callback.message.edit_text(
            "Карточка уже полностью заполнена.", reply_markup=card_confirm_keyboard()
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        f"Не заполнено ещё {remaining} клеток. Заполнить их пустышками (—) и подтвердить карточку?",
        reply_markup=yes_no_keyboard("filldone", str(player_id)),
    )
    await callback.answer()


@router.message(
    StateFilter(CardFilling.filling), F.text, ~F.text.startswith("/"), F.text.not_in(ALL_BUTTONS)
)
async def on_slot_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    player_id = data["player_id"]
    game = await db.get_game(data["game_id"])
    player = await db.get_player_by_id(player_id)
    idx = player["fill_index"]
    if idx >= game["size"]:
        await message.answer("Карточка уже полностью заполнена.", reply_markup=card_confirm_keyboard())
        return
    await db.set_slot_text(player_id, idx, message.text.strip())
    await db.set_fill_index(player_id, idx + 1)
    await ask_next_slot(message, player_id, game)


@router.callback_query(F.data == "card:confirm")
async def cb_card_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    player_id = data.get("player_id")
    if player_id is None:
        await callback.answer("Не найдено активное заполнение карточки.", show_alert=True)
        return
    await db.confirm_player(player_id)
    await state.clear()
    player = await db.get_player_by_id(player_id)
    game = await db.get_game(player["game_id"])
    slots = await db.get_slots(player_id)
    await callback.message.edit_text("Карточка подтверждена ✅", reply_markup=None)
    await send_card_image(
        callback.message,
        game,
        slots,
        owner_view=True,
        caption=f"Твоя карточка в игре «{game['title']}»\n⏳ Жди, когда организатор начнёт игру.",
        reply_markup=await build_menu(callback.from_user.id),
    )
    if game["organizer_id"] != callback.from_user.id:
        await broadcast(
            callback.bot,
            [game["organizer_id"]],
            f"✅ {player['display_name']} присоединился(ась) и готов(а) в игре «{game['title']}».",
        )
    await callback.answer()


@router.message(Command("card"))
async def cmd_card(message: Message) -> None:
    game = await resolve_current_game(message)
    if not game:
        return
    player = await db.get_player(game["id"], message.from_user.id)
    if not player:
        await message.answer("Ты не участвуешь в этой игре.")
        return
    slots = await db.get_slots(player["id"])
    closed = sum(1 for s in slots if s["closed"])
    await send_card_image(
        message,
        game,
        slots,
        owner_view=True,
        caption=f"Твоя карточка в игре «{game['title']}» ({closed}/{game['size']})",
    )


@router.message(Command("players"))
async def cmd_players(message: Message) -> None:
    game = await resolve_current_game(message)
    if not game:
        return
    players = [p for p in await db.get_players(game["id"]) if p["confirmed"]]
    rows = []
    for p in players:
        slots = await db.get_slots(p["id"])
        closed = sum(1 for s in slots if s["closed"])
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{p['display_name']} ({closed}/{game['size']})",
                    callback_data=f"viewcard:{game['id']}:{p['id']}",
                )
            ]
        )
    if not rows:
        await message.answer("В игре пока нет подтверждённых игроков.")
        return
    await message.answer("Игроки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("viewcard:"))
async def cb_viewcard(callback: CallbackQuery) -> None:
    _, game_id_s, player_id_s = callback.data.split(":")
    game = await db.get_game(int(game_id_s))
    target = await db.get_player_by_id(int(player_id_s))
    slots = await db.get_slots(target["id"])
    owner_view = target["user_id"] == callback.from_user.id
    closed = sum(1 for s in slots if s["closed"])
    await send_card_image(
        callback.message,
        game,
        slots,
        owner_view=owner_view,
        caption=f"Карточка {target['display_name']} ({closed}/{game['size']})",
    )
    await callback.answer()


@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message) -> None:
    game = await resolve_current_game(message)
    if not game:
        return
    await send_leaderboard(message, game)


async def send_leaderboard(message: Message, game) -> None:
    players = [p for p in await db.get_players(game["id"]) if p["confirmed"]]
    standings = []
    for p in players:
        slots = await db.get_slots(p["id"])
        closed = sum(1 for s in slots if s["closed"])
        standings.append((p["display_name"], closed, bool(p["line_won"]), bool(p["full_won"])))
    standings.sort(key=lambda t: t[1], reverse=True)
    text = game_logic.build_leaderboard_text(game, standings)
    await message.answer(text)


@router.message(Command("undo"))
async def cmd_undo(message: Message) -> None:
    game = await resolve_current_game(message)
    if not game:
        return
    player = await db.get_player(game["id"], message.from_user.id)
    if not player:
        await message.answer("Ты не участвуешь в этой игре.")
        return
    idx = await db.get_last_marked_idx(player["id"])
    if idx is None:
        await message.answer("Нечего отменять.")
        return
    await db.reopen_slot(player["id"], idx)
    coord = game_logic.idx_to_coord(idx, game["size"])
    await message.answer(f"Отметка клетки {coord} отменена.")


@router.message(F.text == BTN_CARD)
async def on_btn_card(message: Message, state: FSMContext) -> None:
    await state.clear()
    await cmd_card(message)


@router.message(F.text == BTN_PLAYERS)
async def on_btn_players(message: Message, state: FSMContext) -> None:
    await state.clear()
    await cmd_players(message)


@router.message(F.text == BTN_LEADERBOARD)
async def on_btn_leaderboard(message: Message, state: FSMContext) -> None:
    await state.clear()
    await cmd_leaderboard(message)


@router.message(F.text == BTN_UNDO)
async def on_btn_undo(message: Message, state: FSMContext) -> None:
    await state.clear()
    await cmd_undo(message)


@router.message(F.text == BTN_SETTINGS)
async def on_btn_settings(message: Message, state: FSMContext) -> None:
    await state.clear()
    await cmd_settings(message)


@router.message(F.text == BTN_EDITCARD)
async def on_btn_editcard(message: Message, state: FSMContext) -> None:
    await state.clear()
    await cmd_editcard(message)


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"), F.text.not_in(ALL_BUTTONS))
async def on_mark_attempt(message: Message) -> None:
    game = await resolve_current_game(message, silent_if_empty=True)
    if not game:
        return
    player = await db.get_player(game["id"], message.from_user.id)
    idx = game_logic.parse_mark_input(message.text, game["size"])
    if idx is None:
        await message.answer("Не понял. Введи номер клетки (1-N) или координату вроде B5.")
        return
    slot = await db.get_slot(player["id"], idx)
    coord = game_logic.idx_to_coord(idx, game["size"])
    if slot["closed"]:
        await message.answer(f"Клетка {coord} уже закрыта.")
        return

    await db.close_slot(player["id"], idx)
    updated_slots = await db.get_slots(player["id"])
    await send_card_image(
        message,
        game,
        updated_slots,
        owner_view=True,
        caption=f"Клетка {coord} закрыта: «{slot['text']}» ✅",
    )

    others = [
        p for p in await db.get_players(game["id"]) if p["id"] != player["id"] and p["confirmed"]
    ]
    await broadcast(
        message.bot,
        [p["user_id"] for p in others],
        f"🎯 {message.from_user.full_name} закрыл(а) клетку {coord} в игре «{game['title']}»: «{slot['text']}»",
    )

    closed_idx = {s["idx"] for s in updated_slots if s["closed"]}
    result = game_logic.check_win(closed_idx, game["size"])
    line_won = bool(player["line_won"]) or (result["line"] and bool(game["win_line"]))
    full_won = bool(player["full_won"]) or (result["full"] and bool(game["win_full"]))
    new_line = line_won and not player["line_won"]
    new_full = full_won and not player["full_won"]
    if new_line or new_full:
        await db.set_win_flags(player["id"], line_won, full_won)
        kind = []
        if new_full:
            kind.append("собрал(а) ВСЮ карточку")
        if new_line:
            kind.append("собрал(а) линию")
        win_text = f"🏆 {message.from_user.full_name} {' и '.join(kind)} в игре «{game['title']}»!"
        all_ids = [p["user_id"] for p in await db.get_players(game["id"]) if p["confirmed"]]
        await broadcast(message.bot, all_ids, win_text)


@router.callback_query(F.data.startswith("setcurrent:"))
async def cb_setcurrent(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[1])
    game = await db.get_game(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    await db.set_current_game_id(callback.from_user.id, game_id)
    await callback.message.edit_text(f"Текущая игра: «{game['title']}». Повтори свою команду.")
    await callback.answer()


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    games = await db.get_player_games_for_user(message.from_user.id)
    if not games:
        await message.answer("Ты пока не участвуешь ни в одной игре.")
        return
    current_id = await db.get_current_game_id(message.from_user.id)
    lines = ["Твои игры:"]
    for g in games:
        marker = " ← текущая" if g["id"] == current_id else ""
        lines.append(f"• {g['title']} ({g['status']}){marker}")
    lines.append("\nВыбери игру, чтобы сделать её текущей или покинуть:")
    await message.answer("\n".join(lines), reply_markup=player_games_keyboard(games))


@router.callback_query(F.data.startswith("playergame:"))
async def cb_playergame(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[1])
    game = await db.get_game(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    player = await db.get_player(game_id, callback.from_user.id)
    if not player:
        await callback.answer("Ты не в этой игре.", show_alert=True)
        return
    current_id = await db.get_current_game_id(callback.from_user.id)
    is_current = current_id == game_id
    status_text = "подтверждена ✅" if player["confirmed"] else "ещё заполняется"
    await callback.message.edit_text(
        f"«{game['title']}» — статус игры: {game['status']}, твоя карточка: {status_text}",
        reply_markup=player_game_manage_keyboard(game_id, is_current),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("leavegame_request:"))
async def cb_leavegame_request(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[1])
    game = await db.get_game(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    await callback.message.edit_text(
        f"Точно покинуть игру «{game['title']}»? Твоя карточка и все отметки удалятся без возможности "
        "восстановления.",
        reply_markup=yes_no_keyboard("leavegame_confirm", str(game_id)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("leavegame_confirm:"))
async def cb_leavegame_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    _, game_id_s, answer = callback.data.split(":")
    game_id = int(game_id_s)
    game = await db.get_game(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    if answer == "no":
        await callback.message.edit_text("Ок, остаёшься в игре.", reply_markup=None)
        await callback.answer()
        return

    player = await db.get_player(game_id, callback.from_user.id)
    if not player:
        await callback.message.edit_text("Ты уже не в этой игре.", reply_markup=None)
        await callback.answer()
        return

    data = await state.get_data()
    if data.get("game_id") == game_id:
        await state.clear()

    await db.remove_player(game_id, callback.from_user.id)
    await db.clear_current_game_id_if_matches(callback.from_user.id, game_id)
    await callback.message.edit_text(f"Ты покинул(а) игру «{game['title']}».", reply_markup=None)
    await callback.message.answer(
        "Меню обновлено.", reply_markup=await build_menu(callback.from_user.id)
    )

    if game["status"] == "active":
        others = [p["user_id"] for p in await db.get_players(game_id) if p["confirmed"]]
        await broadcast(
            callback.bot, others, f"🚪 {callback.from_user.full_name} покинул(а) игру «{game['title']}»."
        )
    await callback.answer()


@router.message(Command("editcard"))
async def cmd_editcard(message: Message) -> None:
    game = await resolve_draft_game_for_edit(message)
    if not game:
        return
    player = await db.get_player(game["id"], message.from_user.id)
    if not player:
        await message.answer("Ты не участвуешь в этой игре.")
        return
    slots = await db.get_slots(player["id"])
    await message.answer("Режим редактирования карточки.", reply_markup=editmode_menu())
    await message.answer(
        f"Какой слот отредактировать в «{game['title']}»?",
        reply_markup=editcard_slots_keyboard(player["id"], slots),
    )


@router.message(F.text == BTN_FINISH_EDITING)
async def on_btn_finish_editing(message: Message, state: FSMContext) -> None:
    await state.clear()
    game = await resolve_draft_game_for_edit(message, silent_if_empty=True)
    if not game:
        await message.answer("Меню обновлено.", reply_markup=await build_menu(message.from_user.id))
        return
    player = await db.get_player(game["id"], message.from_user.id)
    slots = await db.get_slots(player["id"])
    await send_card_image(
        message,
        game,
        slots,
        owner_view=True,
        caption=f"Твоя карточка в игре «{game['title']}»\n⏳ Ожидаем, когда организатор начнёт игру.",
        reply_markup=await build_menu(message.from_user.id),
    )


@router.callback_query(F.data.startswith("editslot:"))
async def cb_editslot(callback: CallbackQuery, state: FSMContext) -> None:
    _, player_id_s, idx_s = callback.data.split(":")
    player_id, idx = int(player_id_s), int(idx_s)
    player = await db.get_player_by_id(player_id)
    if not player or player["user_id"] != callback.from_user.id:
        await callback.answer("Это не твоя карточка.", show_alert=True)
        return
    game = await db.get_game(player["game_id"])
    if not game or game["status"] != "draft":
        await callback.answer("Игра уже началась — редактирование недоступно.", show_alert=True)
        return
    slot = await db.get_slot(player_id, idx)
    await state.set_state(EditSlot.waiting_text)
    prompt = await callback.message.answer(
        f"Текущий текст слота {idx + 1}: «{slot['text']}»\nПришли новый текст:",
        reply_markup=edit_slot_cancel_keyboard(player_id, idx),
    )
    await state.update_data(
        player_id=player_id, idx=idx, prompt_chat_id=prompt.chat.id, prompt_message_id=prompt.message_id
    )
    await callback.answer()


@router.callback_query(F.data.startswith("editcancel:"))
async def cb_editcancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Отменено, текст слота не изменён.", reply_markup=None)
    await callback.answer()


@router.message(
    StateFilter(EditSlot.waiting_text), F.text, ~F.text.startswith("/"), F.text.not_in(ALL_BUTTONS)
)
async def on_editslot_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    player_id, idx = data["player_id"], data["idx"]
    player = await db.get_player_by_id(player_id)
    game = await db.get_game(player["game_id"])
    if not game or game["status"] != "draft":
        await message.answer("Игра уже началась — редактирование недоступно.")
        await state.clear()
        return
    await db.set_slot_text(player_id, idx, message.text.strip())
    await state.clear()
    try:
        await message.bot.edit_message_reply_markup(
            chat_id=data["prompt_chat_id"], message_id=data["prompt_message_id"], reply_markup=None
        )
    except Exception:
        pass
    await message.answer(f"Слот {idx + 1} обновлён ✅")
