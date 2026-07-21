import io
import logging
import os

from PIL import Image, ImageDraw, ImageFont

import game_logic

logger = logging.getLogger(__name__)

CELL = 120
LABEL = 34
PAD = 6

BG = (255, 255, 255)
GRID_LINE = (90, 90, 90)
HEADER_BG = (230, 230, 230)
CELL_BG = (255, 255, 255)
CELL_CLOSED_BG = (198, 239, 206)
CELL_LOCKED_BG = (222, 222, 222)
TEXT_COLOR = (20, 20, 20)
CLOSED_TEXT_COLOR = (25, 100, 25)

_BUNDLED_FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "DejaVuSans.ttf")

_FONT_CANDIDATES = [
    _BUNDLED_FONT,
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]

_font_path_cache: str | None = None
_warned_no_font = False


def _find_font_path() -> str | None:
    global _font_path_cache, _warned_no_font
    if _font_path_cache is not None:
        return _font_path_cache or None
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            _font_path_cache = path
            return path
    _font_path_cache = ""
    if not _warned_no_font:
        logger.warning(
            "No Cyrillic-capable font found on this system; card images won't render "
            "Cyrillic text correctly. Install a font like DejaVu Sans or Liberation Sans."
        )
        _warned_no_font = True
    return None


def _font(size: int) -> ImageFont.ImageFont:
    path = _find_font_path()
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


MAX_FONT_SIZE = 30
MIN_FONT_SIZE = 9


def _wrap_lines(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _hard_break(draw: ImageDraw.ImageDraw, word: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for ch in word:
        candidate = current + ch
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def _ellipsize(draw: ImageDraw.ImageDraw, line: str, font, max_width: int) -> str:
    while line and draw.textlength(line + "…", font=font) > max_width:
        line = line[:-1]
    return (line + "…") if line else "…"


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, max_height: int):
    """Pick the largest font size whose wrapped text still fits max_width x max_height."""
    text = text or "—"
    for size in range(MAX_FONT_SIZE, MIN_FONT_SIZE - 1, -1):
        font = _font(size)
        lines = _wrap_lines(draw, text, font, max_width)
        line_h = size + 4
        fits_width = all(draw.textlength(line, font=font) <= max_width for line in lines)
        if fits_width and len(lines) * line_h <= max_height:
            return font, lines, line_h

    # Nothing fit even at the minimum size (e.g. one very long word) — force-break and clip.
    font = _font(MIN_FONT_SIZE)
    line_h = MIN_FONT_SIZE + 4
    max_lines = max(1, max_height // line_h)
    raw_lines = _wrap_lines(draw, text, font, max_width)
    lines: list[str] = []
    for line in raw_lines:
        if draw.textlength(line, font=font) <= max_width:
            lines.append(line)
        else:
            lines.extend(_hard_break(draw, line, font, max_width))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(draw, lines[-1], font, max_width)
    return font, lines, line_h


def render_card_image(game, slots, owner_view: bool) -> bytes:
    n = game_logic.size_to_n(game["size"])
    side = LABEL + n * CELL
    img = Image.new("RGB", (side, side), BG)
    draw = ImageDraw.Draw(img)

    header_font = _font(18)

    draw.rectangle([0, 0, LABEL, LABEL], fill=HEADER_BG, outline=GRID_LINE)
    for col in range(n):
        x0 = LABEL + col * CELL
        draw.rectangle([x0, 0, x0 + CELL, LABEL], fill=HEADER_BG, outline=GRID_LINE)
        letter = game_logic.COLUMN_LETTERS[col]
        w = draw.textlength(letter, font=header_font)
        draw.text((x0 + CELL / 2 - w / 2, LABEL / 2 - 10), letter, font=header_font, fill=TEXT_COLOR)
    for row in range(n):
        y0 = LABEL + row * CELL
        draw.rectangle([0, y0, LABEL, y0 + CELL], fill=HEADER_BG, outline=GRID_LINE)
        num = str(row + 1)
        w = draw.textlength(num, font=header_font)
        draw.text((LABEL / 2 - w / 2, y0 + CELL / 2 - 10), num, font=header_font, fill=TEXT_COLOR)

    anonymous = bool(game["anonymous"])
    slot_by_idx = {s["idx"]: s for s in slots}
    for idx in range(n * n):
        slot = slot_by_idx[idx]
        row, col = divmod(idx, n)
        x0 = LABEL + col * CELL
        y0 = LABEL + row * CELL
        closed = bool(slot["closed"])
        hidden = (not owner_view) and anonymous and not closed

        if closed:
            bg = CELL_CLOSED_BG
        elif hidden:
            bg = CELL_LOCKED_BG
        else:
            bg = CELL_BG
        draw.rectangle([x0, y0, x0 + CELL, y0 + CELL], fill=bg, outline=GRID_LINE, width=2)

        if hidden:
            label = "?"
            w = draw.textlength(label, font=header_font)
            draw.text(
                (x0 + CELL / 2 - w / 2, y0 + CELL / 2 - 10), label, font=header_font, fill=TEXT_COLOR
            )
            continue

        text_color = CLOSED_TEXT_COLOR if closed else TEXT_COLOR
        cell_font, lines, line_h = _fit_text(draw, slot["text"], CELL - 2 * PAD, CELL - 2 * PAD)
        ty = y0 + CELL / 2 - (len(lines) * line_h) / 2
        for line in lines:
            w = draw.textlength(line, font=cell_font)
            draw.text((x0 + CELL / 2 - w / 2, ty), line, font=cell_font, fill=text_color)
            ty += line_h

        if closed:
            cx, cy = x0 + CELL - 16, y0 + 14
            draw.line(
                [(cx - 8, cy), (cx - 3, cy + 6), (cx + 9, cy - 8)],
                fill=CLOSED_TEXT_COLOR,
                width=3,
            )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()
