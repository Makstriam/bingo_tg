import re

COLUMN_LETTERS = "ABCDE"  # enough for max size 25 -> n=5

SIZE_TO_N = {4: 2, 9: 3, 16: 4, 25: 5}

_COORD_RE = re.compile(
    r"^\s*(?:([A-Ea-e])(\d{1,2})|(\d{1,2})([A-Ea-e]))\s*$"
)


def size_to_n(size: int) -> int:
    return SIZE_TO_N[size]


def parse_mark_input(raw: str, size: int) -> int | None:
    """Return a 0-based slot index parsed from plain slot number or battleship
    coordinate (b5 / 5b), or None if the input doesn't match either format."""
    n = size_to_n(size)
    raw = raw.strip()

    if raw.isdigit():
        num = int(raw)
        if 1 <= num <= size:
            return num - 1
        return None

    m = _COORD_RE.match(raw)
    if not m:
        return None

    if m.group(1) is not None:
        letter, number = m.group(1), m.group(2)
    else:
        number, letter = m.group(3), m.group(4)

    col = COLUMN_LETTERS.index(letter.upper())
    row = int(number) - 1
    if col >= n or not (0 <= row < n):
        return None
    return row * n + col


def idx_to_coord(idx: int, size: int) -> str:
    n = size_to_n(size)
    row, col = divmod(idx, n)
    return f"{COLUMN_LETTERS[col]}{row + 1}"


def check_win(closed_idx: set[int], size: int) -> dict:
    n = size_to_n(size)
    full = len(closed_idx) == size

    line = False
    for row in range(n):
        if all((row * n + col) in closed_idx for col in range(n)):
            line = True
            break
    if not line:
        for col in range(n):
            if all((row * n + col) in closed_idx for row in range(n)):
                line = True
                break
    if not line:
        if all((i * n + i) in closed_idx for i in range(n)):
            line = True
        elif all((i * n + (n - 1 - i)) in closed_idx for i in range(n)):
            line = True

    return {"line": line, "full": full}


def render_card_text(game, slots, owner_view: bool) -> str:
    size = game["size"]
    closed_count = sum(1 for s in slots if s["closed"])
    lines = [f"Закрыто: {closed_count}/{size}"]
    for s in slots:
        coord = idx_to_coord(s["idx"], size)
        if s["closed"]:
            lines.append(f"{coord} ✅ {s['text']}")
        elif owner_view or not game["anonymous"]:
            lines.append(f"{coord} ⬜ {s['text']}")
        else:
            lines.append(f"{coord} 🔒")
    return "\n".join(lines)


MEDALS = ["🥇", "🥈", "🥉"]


def build_leaderboard_text(game, standings: list[tuple]) -> str:
    """standings: list of (display_name, closed_count, line_won, full_won), pre-sorted desc by closed_count."""
    lines = [f"Таблица лидеров — «{game['title']}»"]
    for place, (name, count, line_won, full_won) in enumerate(standings):
        medal = MEDALS[place] if place < 3 else f"{place + 1}."
        badges = ""
        if full_won:
            badges += " 🏆(вся карточка)"
        if line_won:
            badges += " 📏(линия)"
        lines.append(f"{medal} {name} — {count}/{game['size']}{badges}")
    return "\n".join(lines)
