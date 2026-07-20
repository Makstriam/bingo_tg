import datetime
from typing import Optional

import aiosqlite

DB_PATH = "bingo.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    organizer_id INTEGER NOT NULL,
    organizer_name TEXT NOT NULL,
    size INTEGER NOT NULL,
    win_full INTEGER NOT NULL DEFAULT 1,
    win_line INTEGER NOT NULL DEFAULT 0,
    anonymous INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft',
    mode TEXT NOT NULL DEFAULT 'manual',
    word_pool TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES games(id),
    user_id INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    confirmed INTEGER NOT NULL DEFAULT 0,
    fill_index INTEGER NOT NULL DEFAULT 0,
    last_marked_slot_id INTEGER,
    line_won INTEGER NOT NULL DEFAULT 0,
    full_won INTEGER NOT NULL DEFAULT 0,
    notify_muted INTEGER NOT NULL DEFAULT 0,
    joined_at TEXT NOT NULL,
    UNIQUE(game_id, user_id)
);

CREATE TABLE IF NOT EXISTS slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    idx INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    closed INTEGER NOT NULL DEFAULT 0,
    closed_at TEXT,
    UNIQUE(player_id, idx)
);

CREATE TABLE IF NOT EXISTS user_prefs (
    user_id INTEGER PRIMARY KEY,
    current_game_id INTEGER,
    current_draft_game_id INTEGER
);

CREATE TABLE IF NOT EXISTS mark_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL
);
"""


def _now() -> str:
    return datetime.datetime.utcnow().isoformat()


async def init_db(path: str = DB_PATH) -> None:
    global DB_PATH
    DB_PATH = path
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        cur = await db.execute("PRAGMA table_info(players)")
        cols = [row[1] for row in await cur.fetchall()]
        if "notify_muted" not in cols:
            await db.execute("ALTER TABLE players ADD COLUMN notify_muted INTEGER NOT NULL DEFAULT 0")

        cur = await db.execute("PRAGMA table_info(games)")
        game_cols = [row[1] for row in await cur.fetchall()]
        if "mode" not in game_cols:
            await db.execute("ALTER TABLE games ADD COLUMN mode TEXT NOT NULL DEFAULT 'manual'")
        if "word_pool" not in game_cols:
            await db.execute("ALTER TABLE games ADD COLUMN word_pool TEXT")

        cur = await db.execute("PRAGMA table_info(user_prefs)")
        prefs_cols = [row[1] for row in await cur.fetchall()]
        if "current_draft_game_id" not in prefs_cols:
            await db.execute("ALTER TABLE user_prefs ADD COLUMN current_draft_game_id INTEGER")

        await db.commit()


# ---- games ----

async def create_game(
    title: str,
    organizer_id: int,
    organizer_name: str,
    size: int,
    win_full: bool,
    win_line: bool,
    anonymous: bool,
    mode: str = "manual",
    word_pool: Optional[str] = None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO games (title, organizer_id, organizer_name, size, win_full, win_line, anonymous, "
            "status, mode, word_pool, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)",
            (
                title,
                organizer_id,
                organizer_name,
                size,
                int(win_full),
                int(win_line),
                int(anonymous),
                mode,
                word_pool,
                _now(),
            ),
        )
        await db.commit()
        return cur.lastrowid


async def get_game(game_id: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        return await cur.fetchone()


async def get_games_by_organizer(organizer_id: int, statuses: Optional[list[str]] = None) -> list[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            cur = await db.execute(
                f"SELECT * FROM games WHERE organizer_id = ? AND status IN ({placeholders}) ORDER BY id DESC",
                (organizer_id, *statuses),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM games WHERE organizer_id = ? ORDER BY id DESC", (organizer_id,)
            )
        return await cur.fetchall()


async def set_game_status(game_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE games SET status = ? WHERE id = ?", (status, game_id))
        await db.commit()


# ---- players ----

async def add_player(game_id: int, user_id: int, display_name: str, size: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO players (game_id, user_id, display_name, joined_at) VALUES (?, ?, ?, ?)",
            (game_id, user_id, display_name, _now()),
        )
        player_id = cur.lastrowid
        await db.executemany(
            "INSERT INTO slots (player_id, idx, text) VALUES (?, ?, '')",
            [(player_id, i) for i in range(size)],
        )
        await db.commit()
        return player_id


async def get_player(game_id: int, user_id: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM players WHERE game_id = ? AND user_id = ?", (game_id, user_id)
        )
        return await cur.fetchone()


async def get_player_by_id(player_id: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM players WHERE id = ?", (player_id,))
        return await cur.fetchone()


async def get_players(game_id: int) -> list[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM players WHERE game_id = ? ORDER BY id", (game_id,))
        return await cur.fetchall()


async def confirm_player(player_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE players SET confirmed = 1 WHERE id = ?", (player_id,))
        await db.commit()


async def set_notify_muted(player_id: int, muted: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE players SET notify_muted = ? WHERE id = ?", (int(muted), player_id))
        await db.commit()


async def set_fill_index(player_id: int, index: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE players SET fill_index = ? WHERE id = ?", (index, player_id))
        await db.commit()


async def set_win_flags(player_id: int, line_won: bool, full_won: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE players SET line_won = ?, full_won = ? WHERE id = ?",
            (int(line_won), int(full_won), player_id),
        )
        await db.commit()


async def get_active_games_for_user(user_id: int) -> list[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT g.* FROM games g JOIN players p ON p.game_id = g.id "
            "WHERE p.user_id = ? AND g.status = 'active' AND p.confirmed = 1",
            (user_id,),
        )
        return await cur.fetchall()


async def get_player_games_for_user(user_id: int) -> list[aiosqlite.Row]:
    """Draft/active games this user currently takes part in, newest first."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT g.* FROM games g JOIN players p ON p.game_id = g.id "
            "WHERE p.user_id = ? AND g.status IN ('draft', 'active') ORDER BY g.id DESC",
            (user_id,),
        )
        return await cur.fetchall()


async def remove_player(game_id: int, user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM players WHERE game_id = ? AND user_id = ?", (game_id, user_id)
        )
        row = await cur.fetchone()
        if not row:
            return
        player_id = row[0]
        await db.execute("DELETE FROM slots WHERE player_id = ?", (player_id,))
        await db.execute("DELETE FROM players WHERE id = ?", (player_id,))
        await db.commit()


# ---- per-user preferences ----

async def get_current_game_id(user_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT current_game_id FROM user_prefs WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        return row[0] if row else None


async def set_current_game_id(user_id: int, game_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO user_prefs (user_id, current_game_id) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET current_game_id = excluded.current_game_id",
            (user_id, game_id),
        )
        await db.commit()


async def clear_current_game_id_if_matches(user_id: int, game_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE user_prefs SET current_game_id = NULL WHERE user_id = ? AND current_game_id = ?",
            (user_id, game_id),
        )
        await db.execute(
            "UPDATE user_prefs SET current_draft_game_id = NULL "
            "WHERE user_id = ? AND current_draft_game_id = ?",
            (user_id, game_id),
        )
        await db.commit()


async def get_current_draft_game_id(user_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT current_draft_game_id FROM user_prefs WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        return row[0] if row else None


async def set_current_draft_game_id(user_id: int, game_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO user_prefs (user_id, current_draft_game_id) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET current_draft_game_id = excluded.current_draft_game_id",
            (user_id, game_id),
        )
        await db.commit()


# ---- slots ----

async def get_slots(player_id: int) -> list[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM slots WHERE player_id = ? ORDER BY idx", (player_id,))
        return await cur.fetchall()


async def get_slot(player_id: int, idx: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM slots WHERE player_id = ? AND idx = ?", (player_id, idx)
        )
        return await cur.fetchone()


async def set_slot_text(player_id: int, idx: int, text: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE slots SET text = ? WHERE player_id = ? AND idx = ?", (text, player_id, idx)
        )
        await db.commit()


async def close_slot(player_id: int, idx: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE slots SET closed = 1, closed_at = ? WHERE player_id = ? AND idx = ?",
            (_now(), player_id, idx),
        )
        cur = await db.execute(
            "SELECT id FROM slots WHERE player_id = ? AND idx = ?", (player_id, idx)
        )
        row = await cur.fetchone()
        await db.execute(
            "UPDATE players SET last_marked_slot_id = ? WHERE id = ?", (row[0], player_id)
        )
        await db.commit()


async def reopen_slot(player_id: int, idx: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE slots SET closed = 0, closed_at = NULL WHERE player_id = ? AND idx = ?",
            (player_id, idx),
        )
        await db.execute(
            "UPDATE players SET last_marked_slot_id = NULL WHERE id = ? AND last_marked_slot_id = "
            "(SELECT id FROM slots WHERE player_id = ? AND idx = ?)",
            (player_id, player_id, idx),
        )
        await db.commit()


async def autofill_and_confirm(player_id: int, placeholder: str = "???") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT idx FROM slots WHERE player_id = ? AND (text IS NULL OR text = '')", (player_id,)
        )
        empty_idxs = [row[0] for row in await cur.fetchall()]
        for idx in empty_idxs:
            await db.execute(
                "UPDATE slots SET text = ? WHERE player_id = ? AND idx = ?", (placeholder, player_id, idx)
            )
        await db.execute(
            "UPDATE players SET fill_index = (SELECT COUNT(*) FROM slots WHERE player_id = players.id), "
            "confirmed = 1 WHERE id = ?",
            (player_id,),
        )
        await db.commit()


async def delete_game(game_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id FROM players WHERE game_id = ?", (game_id,))
        player_ids = [row[0] for row in await cur.fetchall()]
        for player_id in player_ids:
            await db.execute("DELETE FROM slots WHERE player_id = ?", (player_id,))
        await db.execute("DELETE FROM players WHERE game_id = ?", (game_id,))
        await db.execute("DELETE FROM games WHERE id = ?", (game_id,))
        await db.execute(
            "UPDATE user_prefs SET current_game_id = NULL WHERE current_game_id = ?", (game_id,)
        )
        await db.execute(
            "UPDATE user_prefs SET current_draft_game_id = NULL WHERE current_draft_game_id = ?",
            (game_id,),
        )
        await db.commit()


async def get_last_marked_idx(player_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT s.idx FROM slots s JOIN players p ON p.last_marked_slot_id = s.id WHERE p.id = ?",
            (player_id,),
        )
        row = await cur.fetchone()
        return row["idx"] if row else None


async def save_mark_notifications(player_id: int, idx: int, entries: list[tuple[int, int]]) -> None:
    if not entries:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT INTO mark_notifications (player_id, idx, chat_id, message_id) VALUES (?, ?, ?, ?)",
            [(player_id, idx, chat_id, message_id) for chat_id, message_id in entries],
        )
        await db.commit()


async def pop_mark_notifications(player_id: int, idx: int) -> list[tuple[int, int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT chat_id, message_id FROM mark_notifications WHERE player_id = ? AND idx = ?",
            (player_id, idx),
        )
        rows = await cur.fetchall()
        await db.execute(
            "DELETE FROM mark_notifications WHERE player_id = ? AND idx = ?", (player_id, idx)
        )
        await db.commit()
        return [(row[0], row[1]) for row in rows]
