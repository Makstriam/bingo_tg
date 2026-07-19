from aiogram.fsm.state import State, StatesGroup


class GameCreation(StatesGroup):
    title = State()
    size = State()
    anonymous = State()
    mode = State()
    pool = State()


class CardFilling(StatesGroup):
    filling = State()


class EditSlot(StatesGroup):
    waiting_text = State()
