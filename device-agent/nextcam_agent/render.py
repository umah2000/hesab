"""Lay a receipt payload out as a monochrome image (right-to-left, Persian shaping).

The payload is built and formatted by the server (``app.modules.devices.services.receipt``);
this module only places text. Pillow's RAQM layout (HarfBuzz + FriBiDi) shapes Persian
letters and orders mixed RTL/LTR runs where it is available (the Linux and macOS wheels).
The Windows wheels have no FriBiDi, so RAQM is missing exactly on the registers: there the
text is shaped (arabic-reshaper) and put in display order (python-bidi) before Pillow's
basic layout draws it. Both paths are tested on every platform (tests force the fallback).
"""

from __future__ import annotations

from importlib import resources
from typing import Any

import arabic_reshaper
from bidi import get_display
from PIL import Image, ImageDraw, ImageFont, features

from nextcam_agent.escpos import PAPER_DOTS

MARGIN = 8
GAP = 6
# Read at call time so tests can force the fallback path.
RAQM = features.check("raqm")


def _visual(text: str) -> str:
    """Shaped presentation forms in left-to-right display order (no RAQM)."""
    # base_dir R: a line of only digits (date and time) must still read right to left.
    shaped: str = get_display(arabic_reshaper.reshape(text), base_dir="R")
    return shaped


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    name = "Vazirmatn-Bold.ttf" if bold else "Vazirmatn-Regular.ttf"
    path = resources.files("nextcam_agent") / "fonts" / name
    with resources.as_file(path) as p:
        engine = ImageFont.Layout.RAQM if RAQM else ImageFont.Layout.BASIC
        return ImageFont.truetype(str(p), size, layout_engine=engine)


class Canvas:
    """Draws rows top to bottom on a tall strip, then crops to the used height."""

    def __init__(self, width_dots: int) -> None:
        self.w = width_dots
        scale = width_dots / 576
        self.small = _font(False, round(20 * scale) + 2)
        self.normal = _font(False, round(24 * scale) + 2)
        self.bold = _font(True, round(24 * scale) + 2)
        self.big = _font(True, round(32 * scale) + 2)
        self.img = Image.new("1", (width_dots, 6000), 1)
        self.d = ImageDraw.Draw(self.img)
        self.y = MARGIN

    def _size(self, text: str, font: ImageFont.FreeTypeFont) -> tuple[float, int]:
        if RAQM:
            box = self.d.textbbox((0, 0), text, font=font, direction="rtl", language="fa")
            width = self.d.textlength(text, font=font, direction="rtl", language="fa")
        else:
            box = self.d.textbbox((0, 0), _visual(text), font=font)
            width = self.d.textlength(_visual(text), font=font)
        return width, int(box[3] - min(box[1], 0))

    def _draw(self, xy: tuple[float, float], text: str, font: ImageFont.FreeTypeFont) -> None:
        if RAQM:
            self.d.text(xy, text, font=font, fill=0, direction="rtl", language="fa")
        else:
            self.d.text(xy, _visual(text), font=font, fill=0)

    def _wrap(self, text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
        words, lines, cur = text.split(), [], ""
        for w in words:
            cand = f"{cur} {w}".strip()
            if self._size(cand, font)[0] <= width or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = w
        return [*lines, cur] if cur else lines or [""]

    def text(self, text: str, font: ImageFont.FreeTypeFont, align: str = "right") -> None:
        for line in self._wrap(text, font, self.w - 2 * MARGIN):
            tw, th = self._size(line, font)
            x = {"right": self.w - MARGIN - tw, "center": (self.w - tw) / 2}.get(align, MARGIN)
            self._draw((x, self.y), line, font)
            self.y += th + GAP

    def pair(self, right: str, left: str, font: ImageFont.FreeTypeFont) -> None:
        """Label on the right, value on the left (amounts line up on the left edge)."""
        lw, lh = self._size(left, font)
        rights = self._wrap(right, font, self.w - 2 * MARGIN - lw - 16)
        y0 = self.y
        for line in rights:
            tw, th = self._size(line, font)
            self._draw((self.w - MARGIN - tw, self.y), line, font)
            self.y += th + GAP
        self._draw((MARGIN, y0), left, font)
        self.y = max(self.y, y0 + lh + GAP)

    def rule(self) -> None:
        self.y += 2
        for x in range(MARGIN, self.w - MARGIN, 8):
            self.d.line((x, self.y, x + 4, self.y), fill=0, width=2)
        self.y += 8

    def line(self, y: int) -> None:
        self.d.line((MARGIN, y, self.w - MARGIN, y), fill=0, width=2)

    def box(self, top: int) -> None:
        """A frame from ``top`` down to the current row."""
        self.d.rectangle((MARGIN, top, self.w - MARGIN, self.y), outline=0, width=2)
        self.y += GAP

    def shade(self, box: tuple[int, int, int, int]) -> None:
        """Light dot shading, the thermal printer's grey (header and total rows)."""
        x0, y0, x1, y1 = box
        for y in range(y0 + 2, y1 - 1, 3):
            for x in range(x0 + 2 + (y % 2), x1 - 1, 3):
                self.d.point((x, y), fill=0)

    def cell(
        self,
        x0: float,
        x1: float,
        y: int,
        text: str,
        font: ImageFont.FreeTypeFont,
        align: str = "center",
    ) -> int:
        """Wrapped text inside [x0, x1]; returns the height used."""
        pad = 6
        h = 0
        for part in self._wrap(text, font, x1 - x0 - 2 * pad):
            tw, th = self._size(part, font)
            x = x1 - pad - tw if align == "right" else x0 + (x1 - x0 - tw) / 2
            self._draw((x, y + h), part, font)
            h += th + 2
        return h

    def grid(
        self,
        rows: list[list[str]],
        widths: list[float],
        fonts: list[ImageFont.FreeTypeFont],
        *,
        shaded: frozenset[int] | set[int] = frozenset(),
        first_right: bool = True,
    ) -> None:
        """A bordered table, first column on the right (RTL)."""
        inner = self.w - 2 * MARGIN
        edges: list[float] = [self.w - MARGIN]
        for w in widths:
            edges.append(edges[-1] - w * inner)
        edges[-1] = MARGIN
        for r, row in enumerate(rows):
            font = fonts[min(r, len(fonts) - 1)]
            top = self.y
            heights = []
            for c, text in enumerate(row):
                x1, x0 = edges[c], edges[c + 1]
                align = "right" if c == 0 and first_right else "center"
                heights.append(self.cell(x0, x1, top + 6, text, font, align))
            bottom = top + max(heights) + 12
            if r in shaded:
                self.shade((MARGIN, top, self.w - MARGIN, bottom))
                for c, text in enumerate(row):  # text again, over the dots
                    x1, x0 = edges[c], edges[c + 1]
                    align = "right" if c == 0 and first_right else "center"
                    self.cell(x0, x1, top + 6, text, font, align)
            self.d.rectangle((MARGIN, top, self.w - MARGIN, bottom), outline=0, width=2)
            for x in edges[1:-1]:
                self.d.line((x, top, x, bottom), fill=0, width=2)
            self.y = bottom
        self.y += GAP

    def done(self) -> Image.Image:
        return self.img.crop((0, 0, self.w, self.y + MARGIN))


# Column widths of the item table (shop name, qty, list price, shop price, amount).
TABLE_WIDTHS = [0.30, 0.10, 0.20, 0.20, 0.20]


def _table_receipt(c: Canvas, payload: dict[str, Any]) -> Image.Image:
    """The shop's receipt layout (sample 1405/08/02): framed name, framed details, a
    bordered item table and a bordered totals table."""
    top = c.y
    c.y += GAP
    c.text(str(payload.get("title", "")), c.big, "center")
    for line in payload.get("header", []):
        c.text(str(line), c.small, "center")
    c.box(top)
    c.text(str(payload.get("heading", "")), c.bold, "center")
    top = c.y
    c.y += GAP
    # Two details per row, as on the sample: «شماره: …  تاریخ: …».
    meta = [f"{label}: {value}" for label, value in payload.get("meta", [])]
    half = (c.w - 2 * MARGIN) / 2
    for i in range(0, len(meta), 2):
        right = c.w - MARGIN
        h = c.cell(right - half, right, c.y, meta[i], c.small, "right")
        if i + 1 < len(meta):
            h = max(h, c.cell(MARGIN, right - half, c.y, meta[i + 1], c.small, "right"))
        c.y += h + GAP
    c.box(top)
    table = payload["table"]
    rows = [list(table["columns"]), *[list(r) for r in table["rows"]]]
    c.grid(rows, TABLE_WIDTHS, [c.small, c.small], shaded={0})
    totals = payload.get("totals", [])
    main: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for t in totals:
        (rest if main and main[-1].get("bold") else main).append(t)
    c.grid(
        [[str(t["label"]), str(t["value"])] for t in main],
        [0.5, 0.5],
        [c.bold],
        shaded=set(range(len(main))),
    )
    for t in rest:
        c.pair(str(t["label"]), str(t["value"]), c.normal)
    for note in payload.get("notes", []):
        c.text(str(note), c.small)
    for line in payload.get("contact", []):
        c.text(str(line), c.normal, "center")
    if payload.get("footer"):
        c.rule()
        for line in payload["footer"]:
            c.text(str(line), c.small, "center")
    return c.done()


def receipt_image(payload: dict[str, Any], paper_width: int) -> Image.Image:
    c = Canvas(PAPER_DOTS.get(paper_width, PAPER_DOTS[80]))
    # 58 mm has no room for five columns: the line layout below.
    if payload.get("table") and c.w >= PAPER_DOTS[80]:
        return _table_receipt(c, payload)
    c.text(str(payload.get("title", "")), c.big, "center")
    for line in payload.get("header", []):
        c.text(str(line), c.small, "center")
    c.text(str(payload.get("heading", "")), c.bold, "center")
    c.rule()
    for label, value in payload.get("meta", []):
        c.pair(f"{label}:", str(value), c.small)
    c.rule()
    for ln in payload.get("lines", []):
        c.pair(str(ln["name"]), str(ln["amount"]), c.normal)
        if ln.get("detail"):
            c.text(str(ln["detail"]), c.small)
    c.rule()
    for t in payload.get("totals", []):
        c.pair(str(t["label"]), str(t["value"]), c.big if t.get("bold") else c.normal)
    for note in payload.get("notes", []):
        c.text(str(note), c.small)
    for line in payload.get("contact", []):
        c.text(str(line), c.small, "center")
    if payload.get("footer"):
        c.rule()
        for line in payload["footer"]:
            c.text(str(line), c.small, "center")
    return c.done()
