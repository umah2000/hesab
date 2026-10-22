"""Product photos (ADR-0022): only real images, re-encoded without metadata, cached by id,
shown to the back office and to the visitor app."""

from __future__ import annotations

import io
import os
from typing import Any

import pytest
from flask import Flask
from PIL import Image

from tests.conftest import Api, Seed, make_user
from tests.test_distribution import Phone, field  # noqa: F401 - fixture
from tests.test_inventory import Inv, inv, keeper, make_item  # noqa: F401 - fixtures
from tests.test_sales import Pos, pos  # noqa: F401 - fixture

pytestmark = pytest.mark.db


def photo(w: int = 3000, h: int = 2000, fmt: str = "JPEG", **save: Any) -> bytes:
    img = Image.new("RGBA" if fmt == "PNG" else "RGB", (w, h), (200, 30, 30, 128))
    buf = io.BytesIO()
    img.save(buf, fmt, **save)
    return buf.getvalue()


def with_exif(w: int = 3000, h: int = 2000) -> bytes:
    """A camera photo: rotated 90° by EXIF and carrying GPS and the camera model."""
    img = Image.new("RGB", (w, h), (10, 120, 10))
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90° clockwise to display
    exif[0x0110] = "SecretPhone 9"  # camera model
    exif[0x8825] = {1: "N", 2: (35.0, 41.0, 0.0)}  # GPS
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def upload(api: Api, item_id: str, content: bytes, name: str = "p.jpg"):  # type: ignore[no-untyped-def]
    headers = {"X-CSRF-Token": api.c.get_cookie("nextcam_csrf").value}  # type: ignore[union-attr]
    return api.c.post(
        f"/api/v1/inventory/items/{item_id}/images",
        data={"file": (io.BytesIO(content), name)},
        headers=headers,
        content_type="multipart/form-data",
    )


def test_upload_reencodes_strips_metadata_and_caches(
    app: Flask,
    inv: Inv,  # noqa: F811
    keeper: Api,  # noqa: F811
) -> None:
    it = make_item(keeper, inv, "IMG1")
    r = upload(keeper, it["id"], with_exif())
    assert r.status_code == 201, r.get_json()
    img = r.get_json()
    # Upright (EXIF applied) and no larger than 1600 on the long side.
    assert (img["width"], img["height"], img["position"]) == (1067, 1600, 0)

    big = keeper.get(f"/api/v1/inventory/images/{img['id']}?size=large")
    assert big.status_code == 200 and big.mimetype == "image/jpeg"
    assert "immutable" in big.headers["Cache-Control"] and big.headers["ETag"]
    out = Image.open(io.BytesIO(big.data))
    assert out.format == "JPEG" and out.size == (1067, 1600)
    assert not out.getexif() and b"SecretPhone" not in big.data
    thumb = keeper.get(f"/api/v1/inventory/images/{img['id']}?size=thumb")
    assert max(Image.open(io.BytesIO(thumb.data)).size) == 400
    again = keeper.get(
        f"/api/v1/inventory/images/{img['id']}?size=large",
        headers={"If-None-Match": big.headers["ETag"]},
    )
    assert again.status_code == 304
    assert keeper.get(f"/api/v1/inventory/images/{img['id']}?size=huge").status_code == 422

    # Transparent PNG: flattened on white, stored as JPEG.
    png = upload(keeper, it["id"], photo(800, 600, "PNG"), "p.png")
    assert png.status_code == 201 and png.get_json()["position"] == 1
    # The same picture twice is one image.
    dup = upload(keeper, it["id"], with_exif())
    assert dup.get_json()["id"] == img["id"]

    detail = keeper.get(f"/api/v1/inventory/items/{it['id']}").get_json()
    assert [i["id"] for i in detail["images"]] == [img["id"], png.get_json()["id"]]
    listed = keeper.get("/api/v1/inventory/items?q=IMG1").get_json()["items"]
    assert listed[0]["image_id"] == img["id"]


def test_only_real_images_within_limits(app: Flask, inv: Inv, keeper: Api) -> None:  # noqa: F811
    it = make_item(keeper, inv, "IMG2")
    for bad, name in [
        (b"", "e.jpg"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "x.jpg"),
        (b"MZ\x90\x00" + os.urandom(100), "x.png"),
        (photo(50, 50, "GIF"), "x.gif"),
    ]:
        r = upload(keeper, it["id"], bad, name)
        assert r.status_code == 422 and r.get_json()["error"]["code"] == "invalid_image", name
    # Small file, enormous picture (a decompression bomb).
    bomb = Image.new("1", (9000, 9000))
    buf = io.BytesIO()
    bomb.save(buf, "PNG")
    r = upload(keeper, it["id"], buf.getvalue(), "b.png")
    assert r.get_json()["error"]["code"] == "image_too_large"
    assert upload(keeper, it["id"], os.urandom(16 * 1024 * 1024)).status_code == 413
    assert keeper.get(f"/api/v1/inventory/items/{it['id']}/images").get_json() == []


def test_order_remove_limit_and_permissions(
    app: Flask,
    seed: Seed,
    inv: Inv,  # noqa: F811
    keeper: Api,  # noqa: F811
) -> None:
    it = make_item(keeper, inv, "IMG3")
    ids = [upload(keeper, it["id"], photo(300 + n, 300)).get_json()["id"] for n in range(6)]
    seventh = upload(keeper, it["id"], photo(500, 500))
    assert seventh.status_code == 409 and seventh.get_json()["error"]["code"] == "too_many_images"

    order = [ids[3], *[i for i in ids if i != ids[3]]]
    r = keeper.put(f"/api/v1/inventory/items/{it['id']}/images/order", {"ids": order}, None)
    assert r.status_code == 200 and [i["id"] for i in r.get_json()] == order
    partial = keeper.put(f"/api/v1/inventory/items/{it['id']}/images/order", {"ids": ids[:2]}, None)
    assert partial.status_code == 422

    gone = keeper.send("DELETE", f"/api/v1/inventory/items/{it['id']}/images/{ids[3]}")
    assert gone.status_code == 204
    left = keeper.get(f"/api/v1/inventory/items/{it['id']}/images").get_json()
    assert [i["position"] for i in left] == [0, 1, 2, 3, 4] and left[0]["id"] == order[1]
    assert keeper.get(f"/api/v1/inventory/images/{ids[3]}").status_code == 404

    # A cashier sees photos but cannot change them; nobody signed out sees anything.
    make_user(app, "pos_only", ["CSH"], [seed.branch_a])
    cashier = Api(app.test_client())
    assert cashier.login("pos_only").status_code == 200
    assert cashier.get(f"/api/v1/inventory/images/{left[0]['id']}").status_code == 200
    assert upload(cashier, it["id"], photo(64, 64)).status_code == 403
    assert (
        cashier.send("DELETE", f"/api/v1/inventory/items/{it['id']}/images/{left[0]['id']}")
    ).status_code == 403
    assert app.test_client().get(f"/api/v1/inventory/images/{left[0]['id']}").status_code == 401


def test_visitor_app_gets_photo_ids_and_files(
    app: Flask,
    field: dict[str, Any],  # noqa: F811
    pos: Pos,  # noqa: F811
) -> None:
    boss: Api = field["boss"]
    img = upload(boss, pos.milk, photo(1200, 900)).get_json()
    phone = Phone(app.test_client())
    assert phone.login("visitor1").status_code == 200
    items = {i["id"]: i for i in phone.get("/distribution/mobile/bootstrap").json["items"]}
    assert items[pos.milk]["image_ids"] == [img["id"]]
    f = phone.get(f"/distribution/mobile/images/{img['id']}?size=large")
    assert f.status_code == 200 and f.mimetype == "image/jpeg"
    assert Image.open(io.BytesIO(f.data)).size == (1200, 900)
    # The app token opens the app's path only.
    assert phone.get(f"/inventory/images/{img['id']}").status_code in (401, 403)
