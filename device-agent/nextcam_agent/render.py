"""Lay a receipt payload out as a monochrome image (right-to-left, Persian shaping).

The payload is built and formatted by the server (``app.modules.devices.services.receipt``);
this module only places text. Pillow's RAQM layout (HarfBuzz + FriBiDi, bundled in the
Pillow wheels) shapes Persian letters and orders mixed RTL/LTR runs.
"""

from __future__ import annotations

from importlib import resources
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from nextcam_agent.escpos import PAPER_DOTS

MARGIN = 8
GAP = 6


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    name = "Vazirmatn-Bold.ttf" if bold else "Vazirmatn-Regular.ttf"
    path = resources.files("nextcam_agent") / "fonts" / name
    with resources.as_file(path) as p:
        return ImageFont.truetype(str(p), size, layout_engine=ImageFont.Layout.RAQM)


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
        box = self.d.textbbox((0, 0), text, font=font, direction="rtl", language="fa")
        return self.d.textlength(text, font=font, direction="rtl", language="fa"), int(
            box[3] - min(box[1], 0)
        )

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
            self.d.text((x, self.y), line, font=font, fill=0, direction="rtl", language="fa")
            self.y += th + GAP

    def pair(self, right: str, left: str, font: ImageFont.FreeTypeFont) -> None:
        """Label on the right, value on the left (amounts line up on the left edge)."""
        lw, lh = self._size(left, font)
        rights = self._wrap(right, font, self.w - 2 * MARGIN - lw - 16)
        y0 = self.y
        for line in rights:
            tw, th = self._size(line, font)
            self.d.text(
                (self.w - MARGIN - tw, self.y),
                line,
                font=font,
                fill=0,
                direction="rtl",
                language="fa",
            )
            self.y += th + GAP
        self.d.text((MARGIN, y0), left, font=font, fill=0, direction="rtl", language="fa")
        self.y = max(self.y, y0 + lh + GAP)

    def rule(self) -> None:
        self.y += 2
        for x in range(MARGIN, self.w - MARGIN, 8):
            self.d.line((x, self.y, x + 4, self.y), fill=0, width=2)
        self.y += 8

    def done(self) -> Image.Image:
        return self.img.crop((0, 0, self.w, self.y + MARGIN))


def receipt_image(payload: dict[str, Any], paper_width: int) -> Image.Image:
    c = Canvas(PAPER_DOTS.get(paper_width, PAPER_DOTS[80]))
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
    if payload.get("footer"):
        c.rule()
        for line in payload["footer"]:
            c.text(str(line), c.small, "center")
    return c.done()
