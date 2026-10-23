"""Organization logo and «درباره ما» (ADR-0022): the login page sees only the name and
logo; the About page needs a session; only settings.manage changes them."""

from __future__ import annotations

import io

import pytest
from flask import Flask
from PIL import Image

from tests.conftest import Api, Seed, make_user

pytestmark = pytest.mark.db


def png(w: int = 1200, h: int = 600) -> bytes:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    img.paste((20, 90, 200, 255), (100, 100, 700, 500))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def upload(api: Api, content: bytes):  # type: ignore[no-untyped-def]
    headers = {"X-CSRF-Token": api.c.get_cookie("nextcam_csrf").value}  # type: ignore[union-attr]
    return api.c.post(
        "/api/v1/organization/logo",
        data={"file": (io.BytesIO(content), "logo.png")},
        headers=headers,
        content_type="multipart/form-data",
    )


def test_logo_and_about(app: Flask, seed: Seed, admin: Api) -> None:
    anon = app.test_client()
    brand = anon.get("/api/v1/system/branding").get_json()
    assert brand["logo_version"] is None and brand["organization_name"]
    assert anon.get("/api/v1/system/logo").status_code == 404

    r = upload(admin, png())
    assert r.status_code == 200, r.get_json()
    version = r.get_json()["logo_version"]
    assert version and anon.get("/api/v1/system/branding").get_json()["logo_version"] == version
    logo = anon.get(f"/api/v1/system/logo?v={version}")
    assert logo.status_code == 200 and logo.mimetype == "image/png"
    img = Image.open(io.BytesIO(logo.data))
    # At most 512 px, transparency kept.
    assert img.size == (512, 256) and img.mode == "RGBA" and img.getpixel((0, 0))[3] == 0
    assert (
        anon.get("/api/v1/system/logo", headers={"If-None-Match": logo.headers["ETag"]}).status_code
        == 304
    )
    assert upload(admin, b"not an image").get_json()["error"]["code"] == "invalid_image"

    org = admin.get("/api/v1/organization/settings").get_json()
    body = {
        "about": "سوپرمارکت محله از ۱۳۸۰",
        "phone": "021-12345678",
        "website": "shop.example.ir",
        "address": "تهران",
    }
    upd = admin.put("/api/v1/organization/settings", body, org["row_version"])
    assert upd.status_code == 200, upd.get_json()
    bad = admin.put(
        "/api/v1/organization/settings", {"website": "javascript:alert(1)"}, upd.json["row_version"]
    )
    assert bad.status_code == 400

    # Any signed-in user sees «درباره ما»; signed out, nothing.
    make_user(app, "clerk", ["CSH"])
    clerk = Api(app.test_client())
    assert clerk.login("clerk").status_code == 200
    about = clerk.get("/api/v1/system/about").get_json()
    assert about["organization"]["about"] == body["about"]
    assert about["organization"]["logo_version"] == version
    assert about["app"]["version"]
    assert isinstance(about["developer"], dict)
    assert anon.get("/api/v1/system/about").status_code == 401
    # Only settings.manage changes the logo.
    assert upload(clerk, png()).status_code == 403
    assert clerk.send("DELETE", "/api/v1/organization/logo").status_code == 403

    gone = admin.send("DELETE", "/api/v1/organization/logo")
    assert gone.status_code == 200 and gone.get_json()["logo_version"] is None
    assert anon.get("/api/v1/system/logo").status_code == 404
