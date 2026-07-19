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

_FONT_CANDIDATES = [
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


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                current = ""
                break
    if current:
        lines.append(current)

    truncated = len(lines) > max_lines or (not current and len(" ".join(lines)) < len(text))
    lines = lines[:max_lines]
    if truncated and lines:
        last = lines[-1]
        while draw.textlength(last + "…", font=font) > max_width and len(last) > 1:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


def _cell_font_size(n: int) -> int:
    return max(10, 18 - 2 * (n - 2))


def render_card_image(game, slots, owner_view: bool) -> bytes:
    n = game_logic.size_to_n(game["size"])
    side = LABEL + n * CELL
    img = Image.new("RGB", (side, side), BG)
    draw = ImageDraw.Draw(img)

    header_font = _font(18)
    cell_font = _font(_cell_font_size(n))

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
        lines = _wrap_text(draw, slot["text"] or "—", cell_font, CELL - 2 * PAD, max_lines=5)
        line_h = _cell_font_size(n) + 4
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
