"""Decoding uploaded pictures safely (ADR-0022): product photos and the organization logo.

Only real JPEG, PNG or WebP files within size limits are accepted; the result is an
upright image with no metadata left, ready to be written again by the caller. The
server never stores or serves the bytes a user uploaded.
"""

from __future__ import annotations

import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import DomainError

MAX_UPLOAD = 15 * 1024 * 1024
MAX_PIXELS = 40_000_000
ACCEPTED = {"JPEG", "PNG", "WEBP"}


def decode(data: bytes) -> Image.Image:
    """The uploaded picture, upright (EXIF applied); anything else is refused."""
    if not data:
        raise DomainError("فایل عکس خالی است", code="invalid_image")
    if len(data) > MAX_UPLOAD:
        raise DomainError("حجم عکس بیش از ۱۵ مگابایت است", code="image_too_large")
    try:
        with warnings.catch_warnings():
            # A decompression bomb is an error, not a warning.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as src:
                if src.format not in ACCEPTED:
                    raise DomainError(
                        "فقط عکس JPEG، PNG یا WebP پذیرفته می‌شود", code="invalid_image"
                    )
                if src.width * src.height > MAX_PIXELS:
                    raise DomainError("ابعاد عکس بیش از حد بزرگ است", code="image_too_large")
                src.load()
                return ImageOps.exif_transpose(src)
    except DomainError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise DomainError("فایل عکس خوانا نیست", code="invalid_image") from e
    except Image.DecompressionBombWarning as e:
        raise DomainError("ابعاد عکس بیش از حد بزرگ است", code="image_too_large") from e


def on_white(img: Image.Image) -> Image.Image:
    """RGB, with any transparency laid on a white background (for JPEG)."""
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return img if img.mode == "RGB" else img.convert("RGB")


def png(img: Image.Image, side: int) -> bytes:
    """A PNG no larger than ``side`` on its long edge, transparency kept (a logo)."""
    copy = img.convert("RGBA")
    copy.thumbnail((side, side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    copy.save(out, "PNG", optimize=True)
    return out.getvalue()
