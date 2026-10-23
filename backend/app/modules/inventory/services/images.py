"""Product photos (ADR-0022): validated, re-encoded and stored in the database.

The server never keeps or serves what the user uploaded: the image is decoded, turned
upright (EXIF), stripped of all metadata (GPS, camera) and written again as two JPEGs.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from dataclasses import dataclass

from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import images as pictures
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.inventory.models import Item, ItemImage
from app.modules.inventory.schemas import ItemImageOut

MAX_UPLOAD = pictures.MAX_UPLOAD
MAX_PER_ITEM = 6
LARGE_SIDE = 1600
THUMB_SIDE = 400
SIZES = ("thumb", "large")


@dataclass
class Processed:
    large: bytes
    thumb: bytes
    width: int
    height: int
    sha256: str


def _jpeg(img: Image.Image, side: int, quality: int) -> tuple[bytes, int, int]:
    copy = img.copy()
    copy.thumbnail((side, side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    copy.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue(), copy.width, copy.height


def process(data: bytes) -> Processed:
    """Decode an upload and produce the stored JPEGs; anything else is refused."""
    img = pictures.on_white(pictures.decode(data))
    large, w, h = _jpeg(img, LARGE_SIDE, 85)
    thumb, _, _ = _jpeg(img, THUMB_SIDE, 80)
    return Processed(large, thumb, w, h, hashlib.sha256(large).hexdigest())


def _out(im: ItemImage) -> ItemImageOut:
    return ItemImageOut(id=im.id, position=im.position, width=im.width, height=im.height)


def _ordered(s: Session, item_id: uuid.UUID) -> list[ItemImage]:
    return list(
        s.scalars(
            select(ItemImage)
            .where(ItemImage.item_id == item_id)
            .order_by(ItemImage.position, ItemImage.created_at)
        )
    )


def list_images(s: Session, item_id: uuid.UUID) -> list[ItemImageOut]:
    if s.get(Item, item_id) is None:
        raise NotFoundError("کالا یافت نشد")
    return [_out(im) for im in _ordered(s, item_id)]


def image_ids(
    s: Session, item_ids: list[uuid.UUID] | None = None
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """{item id: image ids, main image first} without reading any image bytes."""
    q = select(ItemImage.item_id, ItemImage.id).order_by(
        ItemImage.item_id, ItemImage.position, ItemImage.created_at
    )
    if item_ids is not None:
        if not item_ids:
            return {}
        q = q.where(ItemImage.item_id.in_(item_ids))
    out: dict[uuid.UUID, list[uuid.UUID]] = {}
    for item_id, image_id in list(s.execute(q)):
        out.setdefault(item_id, []).append(image_id)
    return out


def add(s: Session, actor: Actor, item_id: uuid.UUID, data: bytes) -> ItemImageOut:
    p = process(data)
    # Key seek on the item: two uploads to one item get distinct positions.
    item = s.get(Item, item_id, with_for_update=True)
    if item is None:
        raise NotFoundError("کالا یافت نشد")
    images = _ordered(s, item.id)
    same = next((im for im in images if im.sha256 == p.sha256), None)
    if same is not None:
        return _out(same)
    if len(images) >= MAX_PER_ITEM:
        raise ConflictError(
            f"هر کالا حداکثر {MAX_PER_ITEM} عکس دارد؛ اول یکی را حذف کنید", code="too_many_images"
        )
    position = (
        s.scalar(select(func.max(ItemImage.position)).where(ItemImage.item_id == item.id)) or 0
    ) + (1 if images else 0)
    im = ItemImage(
        item_id=item.id,
        position=position,
        width=p.width,
        height=p.height,
        sha256=p.sha256,
        large=p.large,
        thumb=p.thumb,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(im)
    s.flush()
    audit.record(
        s,
        "inventory.item_image_added",
        user_id=actor.user_id,
        entity_type="item",
        entity_id=item.id,
        data={"image_id": str(im.id), "bytes": len(p.large)},
    )
    return _out(im)


def remove(s: Session, actor: Actor, item_id: uuid.UUID, image_id: uuid.UUID) -> None:
    if s.get(Item, item_id, with_for_update=True) is None:
        raise NotFoundError("کالا یافت نشد")
    im = s.get(ItemImage, image_id)
    if im is None or im.item_id != item_id:
        raise NotFoundError("عکس یافت نشد")
    s.delete(im)
    s.flush()
    for pos, rest in enumerate(_ordered(s, item_id)):
        rest.position = pos
    s.flush()
    audit.record(
        s,
        "inventory.item_image_removed",
        user_id=actor.user_id,
        entity_type="item",
        entity_id=item_id,
        data={"image_id": str(image_id)},
    )


def reorder(
    s: Session, actor: Actor, item_id: uuid.UUID, ids: list[uuid.UUID]
) -> list[ItemImageOut]:
    if s.get(Item, item_id, with_for_update=True) is None:
        raise NotFoundError("کالا یافت نشد")
    images = {im.id: im for im in _ordered(s, item_id)}
    if len(ids) != len(set(ids)) or set(ids) != set(images):
        raise DomainError("فهرست عکس‌ها با عکس‌های کالا یکی نیست", code="invalid_order")
    for pos, iid in enumerate(ids):
        images[iid].position = pos
    s.flush()
    audit.record(
        s,
        "inventory.item_images_ordered",
        user_id=actor.user_id,
        entity_type="item",
        entity_id=item_id,
        data={"main": str(ids[0]) if ids else None},
    )
    return [_out(images[i]) for i in ids]


def content(s: Session, image_id: uuid.UUID, size: str) -> tuple[bytes, str]:
    """(JPEG bytes, sha256 ETag) of one image in one size."""
    if size not in SIZES:
        raise DomainError("اندازه‌ی عکس نامعتبر است", code="invalid_size")
    col = ItemImage.thumb if size == "thumb" else ItemImage.large
    row = s.execute(select(col, ItemImage.sha256).where(ItemImage.id == image_id)).first()
    if row is None:
        raise NotFoundError("عکس یافت نشد")
    return bytes(row[0]), f"{row[1]}-{size}"
