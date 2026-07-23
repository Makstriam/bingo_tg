from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import db
import game_logic
import word_pool
from handlers_player import ask_next_slot, begin_card_filling, send_card_image, send_leaderboard
from menu import ALL_BUTTONS, BTN_MYGAMES, BTN_NEWGAME, build_menu
from keyboards import (
    manage_game_keyboard,
    mode_choice_keyboard,
    mygames_keyboard,
    pool_choice_keyboard,
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
    await state.update_data(anonymous=answer == "yes")
    await state.set_state(GameCreation.mode)
    await callback.message.edit_text(
        "Как будут заполняться карточки?", reply_markup=mode_choice_keyboard()
    )
    await callback.answer()


async def finalize_and_create_game(
    send_target: Message, user, state: FSMContext, mode: str, word_pool: str | None
) -> None:
    data = await state.get_data()
    game_id = await db.create_game(
        title=data["title"],
        organizer_id=user.id,
        organizer_name=user.full_name,
        size=data["size"],
        win_full=True,
        win_line=False,
        anonymous=data["anonymous"],
        mode=mode,
        word_pool=word_pool,
    )
    await state.clear()
    bot_user = await send_target.bot.get_me()
    link = f"https://t.me/{bot_user.username}?start=join_{game_id}"
    mode_note = (
        "Карточки будут случайными из списка." if mode == "random" else "Каждый заполняет карточку сам."
    )
    await send_target.answer(
        f"Игра «{data['title']}» создана!\n"
        f"Слотов: {data['size']}\n"
        f"{mode_note}\n"
        f"Ссылка для приглашения:\n{link}\n\n"
        "Разошли её участникам. Когда все заполнят карточки, используй /mygames, чтобы начать игру — "
        "он же теперь в меню снизу.",
        reply_markup=await build_menu(user.id),
    )
    await send_target.answer(
        "Хочешь и сам(а) участвовать в этой игре?",
        reply_markup=yes_no_keyboard("orgjoin", str(game_id)),
    )


@router.callback_query(StateFilter(GameCreation.mode), F.data == "newgame:mode:manual")
async def on_mode_manual(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Игра создаётся...", reply_markup=None)
    await finalize_and_create_game(callback.message, callback.from_user, state, mode="manual", word_pool=None)
    await callback.answer()


@router.callback_query(StateFilter(GameCreation.mode), F.data == "newgame:mode:random")
async def on_mode_random(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(GameCreation.pool)
    await callback.message.edit_text(
        "Пришли файл (.txt) или сообщение со списком фраз — по одной на строке, я буду брать из "
        "них случайные карточки для игроков.\n\n"
        "Либо жми одну из кнопок:",
        reply_markup=pool_choice_keyboard(),
    )
    await callback.answer()


@router.callback_query(StateFilter(GameCreation.pool), F.data == "newgame:poolsample")
async def on_pool_sample(callback: CallbackQuery) -> None:
    sample = "\n".join(word_pool.get_sample())
    await callback.message.answer(
        f"Пример формата (10 строк):\n\n{sample}\n\nПришли свой список в таком же виде — файлом или сообщением."
    )
    await callback.answer()


@router.callback_query(StateFilter(GameCreation.pool), F.data == "newgame:pooldefault")
async def on_pool_default(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Использую стандартный список.", reply_markup=None)
    await finalize_and_create_game(
        callback.message,
        callback.from_user,
        state,
        mode="random",
        word_pool="\n".join(word_pool.DEFAULT_POOL),
    )
    await callback.answer()


@router.message(StateFilter(GameCreation.pool), F.document)
async def on_pool_document(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    size = data["size"]
    file = await message.bot.get_file(message.document.file_id)
    file_bytes = await message.bot.download_file(file.file_path)
    try:
        raw = file_bytes.read().decode("utf-8")
    except UnicodeDecodeError:
        await message.answer("Не получилось прочитать файл — пришли обычный текстовый .txt в кодировке UTF-8.")
        return
    pool = word_pool.parse_pool(raw)
    if len(pool) < size:
        await message.answer(
            f"В списке {len(pool)} фраз(ы), а для карточки нужно минимум {size}. Пришли список побольше."
        )
        return
    await finalize_and_create_game(message, message.from_user, state, mode="random", word_pool="\n".join(pool))


@router.message(
    StateFilter(GameCreation.pool), F.text, ~F.text.startswith("/"), F.text.not_in(ALL_BUTTONS)
)
async def on_pool_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    size = data["size"]
    pool = word_pool.parse_pool(message.text)
    if len(pool) < size:
        await message.answer(
            f"В списке {len(pool)} фраз(ы), а для карточки нужно минимум {size}. Пришли список побольше."
        )
        return
    await finalize_and_create_game(message, message.from_user, state, mode="random", word_pool="\n".join(pool))


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
    intro = (
        f"Заполним твою карточку из {game['size']} слотов."
        if game["mode"] == "manual"
        else "Сейчас соберу тебе случайную карточку."
    )
    await callback.message.edit_text(intro, reply_markup=None)
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
        await send_card_image(
            callback.message,
            game,
            slots,
            owner_view=True,
            caption=f"Твоя карточка в игре «{game['title']}»\n"
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
    await db.set_current_game_id(callback.from_user.id, game_id)
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


@router.callback_query(F.data.startswith("game:dict:"))
async def cb_export_dict(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[-1])
    game = await db.get_game(game_id)
    if not game or game["organizer_id"] != callback.from_user.id:
        await callback.answer("Не найдено.", show_alert=True)
        return
    players = [p for p in await db.get_players(game_id) if p["confirmed"]]
    if not players:
        await callback.answer("В игре пока нет подтверждённых карточек.", show_alert=True)
        return
    if game["status"] == "active":
        await callback.answer(
            "В списке будут варианты ответов ВСЕХ игроков, включая ещё не раскрытые. Сейчас пришлю файл.",
            show_alert=True,
        )
    lines = [f"# Игра «{game['title']}» — статус: {game['status']}", f"# Слотов: {game['size']}"]
    for p in players:
        slots = await db.get_slots(p["id"])
        lines.append("")
        lines.append(f"# {p['display_name']}")
        lines.extend(s["text"] for s in slots if s["text"])
    content = "\n".join(lines)
    doc = BufferedInputFile(content.encode("utf-8"), filename=f"{game['title']}_cards.txt")
    await callback.message.answer_document(doc, caption=f"Список карточек игры «{game['title']}».")
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
