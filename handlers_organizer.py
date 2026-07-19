from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import db
import game_logic
from handlers_player import ask_next_slot, begin_card_filling, send_leaderboard
from menu import ALL_BUTTONS, BTN_MYGAMES, BTN_NEWGAME, build_menu
from keyboards import (
    manage_game_keyboard,
    mygames_keyboard,
    size_keyboard,
    yes_no_keyboard,
)
from states import CardFilling, GameCreation
from utils import broadcast_with_menu

router = Router()


@router.message(Command("newgame"))
async def cmd_newgame(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(GameCreation.title)
    await message.answer("Название игры?")


@router.message(F.text == BTN_NEWGAME)
async def on_btn_newgame(message: Message, state: FSMContext) -> None:
    await cmd_newgame(message, state)


@router.message(F.text == BTN_MYGAMES)
async def on_btn_mygames(message: Message) -> None:
    await cmd_mygames(message)


@router.message(
    StateFilter(GameCreation.title), F.text, ~F.text.startswith("/"), F.text.not_in(ALL_BUTTONS)
)
async def on_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=message.text.strip())
    await state.set_state(GameCreation.size)
    await message.answer("Сколько слотов в карточке?", reply_markup=size_keyboard())


@router.callback_query(StateFilter(GameCreation.size), F.data.startswith("newgame:size:"))
async def on_size(callback: CallbackQuery, state: FSMContext) -> None:
    size = int(callback.data.split(":")[-1])
    await state.update_data(size=size)
    await state.set_state(GameCreation.anonymous)
    await callback.message.edit_text(
        "Анонимная игра?", reply_markup=yes_no_keyboard("newgame_anon", "x")
    )
    await callback.answer()


@router.callback_query(StateFilter(GameCreation.anonymous), F.data.startswith("newgame_anon:"))
async def on_anonymous(callback: CallbackQuery, state: FSMContext) -> None:
    answer = callback.data.split(":")[-1]
    anonymous = answer == "yes"
    data = await state.get_data()
    game_id = await db.create_game(
        title=data["title"],
        organizer_id=callback.from_user.id,
        organizer_name=callback.from_user.full_name,
        size=data["size"],
        win_full=True,
        win_line=False,
        anonymous=anonymous,
    )
    await state.clear()
    bot_user = await callback.bot.get_me()
    link = f"https://t.me/{bot_user.username}?start=join_{game_id}"
    await callback.message.edit_text(f"Игра «{data['title']}» создана!", reply_markup=None)
    await callback.message.answer(
        f"Игра «{data['title']}» создана!\n"
        f"Слотов: {data['size']}\n"
        f"Ссылка для приглашения:\n{link}\n\n"
        "Разошли её участникам. Когда все заполнят карточки, используй /mygames, чтобы начать игру — "
        "он же теперь в меню снизу.",
        reply_markup=await build_menu(callback.from_user.id),
    )
    await callback.message.answer(
        "Хочешь и сам(а) участвовать в этой игре?",
        reply_markup=yes_no_keyboard("orgjoin", str(game_id)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("orgjoin:"))
async def cb_orgjoin(callback: CallbackQuery, state: FSMContext) -> None:
    _, game_id_s, answer = callback.data.split(":")
    game_id = int(game_id_s)
    game = await db.get_game(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    if answer == "no":
        await callback.message.edit_text(
            "Ок, ты только организуешь. Используй /mygames, чтобы начать игру, когда все будут готовы.",
            reply_markup=None,
        )
        await callback.message.answer(
            "Меню обновлено.", reply_markup=await build_menu(callback.from_user.id)
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        f"Заполним твою карточку из {game['size']} слотов.", reply_markup=None
    )
    await begin_card_filling(callback.message, state, game_id, game, callback.from_user)
    await callback.answer()


@router.message(Command("mygames"))
async def cmd_mygames(message: Message) -> None:
    games = await db.get_games_by_organizer(message.from_user.id)
    if not games:
        await message.answer("У тебя пока нет созданных игр. Используй /newgame.")
        return
    await message.answer("Твои игры:", reply_markup=mygames_keyboard(games))


@router.callback_query(F.data.startswith("game:manage:"))
async def cb_manage(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[-1])
    game = await db.get_game(game_id)
    if not game or game["organizer_id"] != callback.from_user.id:
        await callback.answer("Не найдено.", show_alert=True)
        return
    own_player = await db.get_player(game_id, callback.from_user.id)
    await callback.message.edit_text(
        f"«{game['title']}» — статус: {game['status']}, слотов: {game['size']}",
        reply_markup=manage_game_keyboard(game, has_own_card=bool(own_player)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("returncard:"))
async def cb_returncard(callback: CallbackQuery, state: FSMContext) -> None:
    game_id = int(callback.data.split(":")[-1])
    game = await db.get_game(game_id)
    player = await db.get_player(game_id, callback.from_user.id)
    if not game or not player:
        await callback.answer("Карточка не найдена.", show_alert=True)
        return
    if not player["confirmed"]:
        await state.set_state(CardFilling.filling)
        await state.update_data(game_id=game_id, player_id=player["id"])
        await ask_next_slot(callback.message, player["id"], game)
    else:
        slots = await db.get_slots(player["id"])
        text = game_logic.render_card_text(game, slots, owner_view=True)
        await callback.message.answer(
            f"Твоя карточка в игре «{game['title']}»\n{text}\n\n"
            "Изменить можно кнопкой «✏️ Редактировать карточку» в меню снизу.",
            reply_markup=await build_menu(callback.from_user.id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("game:link:"))
async def cb_link(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[-1])
    game = await db.get_game(game_id)
    if not game or game["organizer_id"] != callback.from_user.id:
        await callback.answer("Не найдено.", show_alert=True)
        return
    bot_user = await callback.bot.get_me()
    link = f"https://t.me/{bot_user.username}?start=join_{game_id}"
    await callback.message.answer(f"Ссылка для приглашения в «{game['title']}»:\n{link}")
    await callback.answer()


@router.callback_query(F.data.startswith("game:start:"))
async def cb_start_request(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[-1])
    game = await db.get_game(game_id)
    if not game or game["organizer_id"] != callback.from_user.id:
        await callback.answer("Не найдено.", show_alert=True)
        return
    if game["status"] != "draft":
        await callback.answer(f"Игру уже нельзя запустить (статус: {game['status']}).", show_alert=True)
        return
    players = await db.get_players(game_id)
    if not players:
        await callback.answer("В игре пока нет ни одного участника.", show_alert=True)
        return
    ready = [p for p in players if p["confirmed"]]
    unconfirmed = [p for p in players if not p["confirmed"]]

    lines = [f"Игроков: {len(players)}", "", "Готовы:"]
    lines += [f"✅ {p['display_name']}" for p in ready] or ["  (никого)"]
    lines.append("")
    lines.append("Не готовы:")
    lines += [f"⏳ {p['display_name']}" for p in unconfirmed] or ["  (никого)"]

    if unconfirmed:
        lines.append("")
        lines.append(
            "Если начнёшь сейчас, их незаполненные клетки автоматически станут «???», "
            "и они всё равно попадут в игру."
        )
    lines.append("")
    lines.append("Начать игру?")

    await callback.message.answer(
        "\n".join(lines), reply_markup=yes_no_keyboard("game_confirmstart", str(game_id))
    )
    await callback.answer()


@router.callback_query(F.data.startswith("game_confirmstart:"))
async def cb_confirm_start(callback: CallbackQuery) -> None:
    _, game_id_s, answer = callback.data.split(":")
    game_id = int(game_id_s)
    game = await db.get_game(game_id)
    if not game or game["organizer_id"] != callback.from_user.id:
        await callback.answer("Не найдено.", show_alert=True)
        return
    if game["status"] != "draft":
        await callback.message.edit_text(
            f"Игру уже нельзя запустить (статус: {game['status']}).", reply_markup=None
        )
        await callback.answer()
        return
    if answer == "no":
        await callback.message.edit_text("Ок, игра пока не начата.", reply_markup=None)
        await callback.answer()
        return

    for p in await db.get_players(game_id):
        if not p["confirmed"]:
            await db.autofill_and_confirm(p["id"])

    await db.set_game_status(game_id, "active")
    await callback.message.edit_text(f"Игра «{game['title']}» началась! 🎉", reply_markup=None)
    players = await db.get_players(game_id)
    await broadcast_with_menu(
        callback.bot,
        [p["user_id"] for p in players],
        f"🎉 Игра «{game['title']}» началась! Отмечай клетки номером (1-{game['size']}) "
        "или координатой вроде B5.",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("game:leaderboard:"))
async def cb_leaderboard(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[-1])
    game = await db.get_game(game_id)
    if not game:
        await callback.answer("Не найдено.", show_alert=True)
        return
    await send_leaderboard(callback.message, game)
    await callback.answer()


@router.callback_query(F.data.startswith("game:end:"))
async def cb_end_request(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[-1])
    game = await db.get_game(game_id)
    if not game or game["organizer_id"] != callback.from_user.id:
        await callback.answer("Не найдено.", show_alert=True)
        return
    if game["status"] != "active":
        await callback.answer(f"Игру нельзя завершить (статус: {game['status']}).", show_alert=True)
        return
    await callback.message.answer(
        f"Точно завершить игру «{game['title']}»? Это действие нельзя отменить.",
        reply_markup=yes_no_keyboard("game_confirmend", str(game_id)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("game_confirmend:"))
async def cb_confirm_end(callback: CallbackQuery) -> None:
    _, game_id_s, answer = callback.data.split(":")
    game_id = int(game_id_s)
    game = await db.get_game(game_id)
    if not game or game["organizer_id"] != callback.from_user.id:
        await callback.answer("Не найдено.", show_alert=True)
        return
    if game["status"] != "active":
        await callback.message.edit_text(
            f"Игра уже не активна (статус: {game['status']}) — повторное завершение не нужно.",
            reply_markup=None,
        )
        await callback.answer()
        return
    if answer == "no":
        await callback.message.edit_text("Игра продолжается.", reply_markup=None)
        await callback.answer()
        return
    await db.set_game_status(game_id, "finished")
    players = [p for p in await db.get_players(game_id) if p["confirmed"]]
    standings = []
    for p in players:
        slots = await db.get_slots(p["id"])
        closed = sum(1 for s in slots if s["closed"])
        standings.append((p["display_name"], closed, bool(p["line_won"]), bool(p["full_won"])))
    standings.sort(key=lambda t: t[1], reverse=True)
    text = "Игра завершена!\n\n" + game_logic.build_leaderboard_text(game, standings)
    await callback.message.edit_text(text, reply_markup=None)
    await broadcast_with_menu(callback.bot, [p["user_id"] for p in players], text)
    await callback.answer()


@router.callback_query(F.data.startswith("game:delete:"))
async def cb_delete_request(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[-1])
    game = await db.get_game(game_id)
    if not game or game["organizer_id"] != callback.from_user.id:
        await callback.answer("Не найдено.", show_alert=True)
        return
    if game["status"] == "active":
        await callback.answer("Сначала заверши активную игру, потом можно удалить.", show_alert=True)
        return
    await callback.message.answer(
        f"Точно удалить игру «{game['title']}» насовсем? Карточки и статистика участников "
        "будут стёрты без возможности восстановления.",
        reply_markup=yes_no_keyboard("game_confirmdelete", str(game_id)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("game_confirmdelete:"))
async def cb_confirm_delete(callback: CallbackQuery) -> None:
    _, game_id_s, answer = callback.data.split(":")
    game_id = int(game_id_s)
    game = await db.get_game(game_id)
    if not game or game["organizer_id"] != callback.from_user.id:
        await callback.message.edit_text("Игра уже удалена.", reply_markup=None)
        await callback.answer()
        return
    if answer == "no":
        await callback.message.edit_text("Ок, игра остаётся.", reply_markup=None)
        await callback.answer()
        return
    await db.delete_game(game_id)
    await callback.message.edit_text(f"Игра «{game['title']}» удалена насовсем.", reply_markup=None)
    await callback.message.answer("Меню обновлено.", reply_markup=await build_menu(callback.from_user.id))
    await callback.answer()
