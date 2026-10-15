"""ESC/POS byte builder — only the widely documented core commands.

Text is printed as a raster image (``GS v 0``), not through the printer's code pages:
most thermal printers have no reliable Persian code page, while raster printing is
supported by practically every ESC/POS printer. Whether a *particular* model accepts
these commands must still be proven on the device (compatibility registry).
"""

from __future__ import annotations

from PIL import Image

ESC = b"\x1b"
GS = b"\x1d"

INIT = ESC + b"@"  # ESC @: initialise printer
# Dots per line at 203 dpi for the common printable widths.
PAPER_DOTS = {58: 384, 80: 576}


def feed(lines: int) -> bytes:
    """ESC d n: print and feed n lines."""
    return ESC + b"d" + bytes([max(0, min(lines, 255))])


def cut() -> bytes:
    """GS V 66 n: feed n dots then partial cut (function B)."""
    return GS + b"V" + bytes([66, 0])


def drawer_kick(pin: int) -> bytes:
    """ESC p m t1 t2: pulse the drawer kick-out connector (m=0 → pin 2, m=1 → pin 5).

    t1/t2 are on/off times in units of 2 ms (here 50 ms on, 500 ms off), the values
    commonly used for solenoid drawers.
    """
    m = 0 if pin == 2 else 1
    return ESC + b"p" + bytes([m, 25, 250])


def raster(image: Image.Image) -> bytes:
    """GS v 0 m xL xH yL yH d1…dk: one monochrome bit image; black pixels print.

    Large images are sent in bands of at most 255 rows, which every printer buffers.
    """
    img = image.convert("1")
    width_bytes = (img.width + 7) // 8
    out = bytearray()
    band = 255
    for top in range(0, img.height, band):
        part = img.crop((0, top, img.width, min(top + band, img.height)))
        rows = part.height
        # PIL mode "1": 0 = black. ESC/POS: bit 1 = print a dot.
        inverted = Image.eval(part.convert("L"), lambda v: 255 - v).convert("1")
        padded = Image.new("1", (width_bytes * 8, rows), 0)
        padded.paste(inverted, (0, 0))
        out += GS + b"v0" + bytes([0])
        out += bytes([width_bytes & 0xFF, width_bytes >> 8, rows & 0xFF, rows >> 8])
        out += padded.tobytes()
    return bytes(out)


def receipt_bytes(image: Image.Image, *, cut_paper: bool, drawer_pin: int | None) -> bytes:
    """Full job: init, optional drawer pulse first (cash in hand sooner), image, feed, cut."""
    out = INIT
    if drawer_pin is not None:
        out += drawer_kick(drawer_pin)
    out += raster(image) + feed(4)
    if cut_paper:
        out += cut()
    return out


def decode_raster(data: bytes) -> list[Image.Image]:
    """Test helper: rebuild the bit images from a byte stream (``GS v 0`` blocks only)."""
    images: list[Image.Image] = []
    i = 0
    while True:
        i = data.find(GS + b"v0", i)
        if i < 0:
            return images
        xl, xh, yl, yh = data[i + 4 : i + 8]
        wb, rows = xl + (xh << 8), yl + (yh << 8)
        body = data[i + 8 : i + 8 + wb * rows]
        img = Image.frombytes("1", (wb * 8, rows), body)
        images.append(Image.eval(img.convert("L"), lambda v: 255 - v).convert("1"))
        i += 8 + wb * rows
