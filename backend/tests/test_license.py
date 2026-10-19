"""License and activation (ADR-0021): signed offline licenses; limits on adding, not selling."""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from flask import Flask

from app.modules.system import license_keys
from tests.conftest import Api, Seed, make_user, new_key

pytestmark = pytest.mark.db

TOOL = Path(__file__).resolve().parents[2] / "tools" / "license" / "nextcam_license.py"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("nextcam_license", TOOL)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tool = _tool()


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> Ed25519PrivateKey:
    key = Ed25519PrivateKey.generate()
    raw = tool.public_raw(key)
    monkeypatch.setattr(license_keys, "TRUSTED", {tool.key_id(raw): tool.b64e(raw)})
    return key


def issue(key: Ed25519PrivateKey, request: dict[str, str], **kw: object) -> str:
    args: dict[str, object] = {
        "branches": None,
        "registers": None,
        "users": None,
        "features": [],
        "valid_until": None,
        "support_until": None,
        "issued": date.today(),
    }
    args.update(kw)
    payload = tool.build_payload(request, kid=tool.key_id(tool.public_raw(key)), **args)
    return tool.sign(key, payload)


def login(app: Flask, username: str) -> Api:
    a = Api(app.test_client())
    assert a.login(username).status_code == 200
    return a


def test_activation_limits_and_expiry(app: Flask, seed: Seed, vendor: Ed25519PrivateKey) -> None:
    make_user(app, "owner", ["ADM"])
    make_user(app, "mgr", ["MGR"])
    make_user(app, "csh", ["CSH"])
    admin = login(app, "owner")
    st = admin.get("/api/v1/system/license").get_json()
    assert st["state"] == "unlicensed" and st["warnings"]
    request = tool.parse_request(st["request_code"])
    assert request["installation_id"] == st["installation_id"]

    def add_register(code: str):
        return admin.post(
            "/api/v1/organization/cash-registers",
            {"branch_id": str(seed.branch_a), "code": code, "name": f"صندوق {code}"},
            idem=new_key(),
        )

    # Unlicensed: nothing is restricted (a warning only).
    assert add_register("U1").status_code == 201
    used = {x["kind"]: x["used"] for x in st["limits"]}
    used["registers"] += 1

    text = issue(
        vendor,
        request,
        registers=used["registers"] + 1,
        branches=used["branches"],
        users=used["users"] + 1,
        valid_until=date.today() + timedelta(days=10),
        support_until=date.today() + timedelta(days=10),
    )
    # Pasted with line breaks (from an e-mail): still fine.
    wrapped = "\n".join(text[i : i + 60] for i in range(0, len(text), 60))
    assert login(app, "csh").post("/api/v1/system/license", {"text": text}).status_code == 403
    st = admin.post("/api/v1/system/license", {"text": wrapped}).get_json()
    assert st["state"] == "expiring" and st["days_left"] in (9, 10, 11)
    assert st["customer"] == "سوپرمارکت آزمایشی"
    assert any("روز دیگر" in w for w in st["warnings"])
    # Managers see the state (dashboard warning), cashiers do not.
    assert login(app, "mgr").get("/api/v1/system/license").status_code == 200
    assert login(app, "csh").get("/api/v1/system/license").status_code == 403

    # Limits apply to adding, with a clear message.
    assert add_register("L1").status_code == 201
    full = add_register("L2")
    assert full.status_code == 422 and full.get_json()["error"]["code"] == "license_limit"
    assert "صندوق" in full.get_json()["error"]["message"]
    branch = admin.post(
        "/api/v1/organization/branches", {"code": "99", "name": "شعبه جدید"}, idem=new_key()
    )
    assert branch.get_json()["error"]["code"] == "license_limit"
    vis_id = str(make_user(app, "vis", ["VIS"]))
    visitor = login(app, "mgr").post(
        "/api/v1/distribution/visitors",
        {"user_id": vis_id, "branch_id": str(seed.branch_a), "code": "V1"},
        idem=new_key(),
    )
    assert visitor.get_json()["error"]["code"] == "license_feature"

    # Expired: a warning, and work goes on (sign-in, lists); limits still hold.
    expired = issue(vendor, request, registers=50, valid_until=date.today() - timedelta(days=1))
    st = admin.post("/api/v1/system/license", {"text": expired}).get_json()
    assert st["state"] == "expired" and any("تمام شده" in w for w in st["warnings"])
    assert login(app, "csh").get("/api/v1/auth/me").status_code == 200
    assert add_register("L3").status_code == 201
    # The replaced license cannot come back.
    again = admin.post("/api/v1/system/license", {"text": text}).get_json()
    assert again["error"]["code"] == "license_reused"


def test_forged_foreign_and_unknown_licenses(
    app: Flask, seed: Seed, vendor: Ed25519PrivateKey
) -> None:
    make_user(app, "owner", ["ADM"])
    admin = login(app, "owner")
    request = tool.parse_request(admin.get("/api/v1/system/license").get_json()["request_code"])

    def install(text: str) -> dict:
        r = admin.post("/api/v1/system/license", {"text": text})
        assert r.status_code == 422, r.get_json()
        return r.get_json()["error"]

    other = issue(vendor, {**request, "installation_id": str(uuid.uuid4())})
    assert install(other)["code"] == "license_other_installation"

    # Raise the limit in the payload without the vendor's key: the signature breaks.
    good = issue(vendor, request, registers=1)
    prefix, body, sig = good.split(".")
    payload = json.loads(tool.b64d(body))
    payload["limits"]["registers"] = 999
    forged_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert "معتبر نیست" in install(f"{prefix}.{tool.b64e(forged_body.encode())}.{sig}")["message"]

    stranger = Ed25519PrivateKey.generate()
    assert "ناشر" in install(issue(stranger, request))["message"]
    assert "NEXTCAM" in install("hello world, not a license")["message"]

    # Installed, then the trusted key is withdrawn (e.g. a leaked key): the license no
    # longer counts — a warning, and no limits from an unverifiable license.
    assert admin.post("/api/v1/system/license", {"text": good}).status_code == 200
    license_keys.TRUSTED.clear()
    st = admin.get("/api/v1/system/license").get_json()
    assert st["state"] == "invalid" and st["warnings"]
    made = admin.post(
        "/api/v1/organization/cash-registers",
        {"branch_id": str(seed.branch_a), "code": "X9", "name": "صندوق X9"},
        idem=new_key(),
    )
    assert made.status_code == 201


def test_vendor_tool_keygen_and_sign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXTCAM_LICENSE_KEY_PASSPHRASE", "a long test passphrase")
    key_file = tmp_path / "vendor.pem"
    assert tool.main(["keygen", "--out", str(key_file)]) == 0
    assert b"ENCRYPTED PRIVATE KEY" in key_file.read_bytes()
    with pytest.raises(SystemExit):
        tool.main(["keygen", "--out", str(key_file)])  # never overwrites a key
    code = "NCR1." + tool.b64e(
        json.dumps({"installation_id": str(uuid.uuid4()), "customer": "فروشگاه"}).encode()
    )
    out = tmp_path / "c.nclic"
    assert (
        tool.main(
            [
                "sign",
                "--key",
                str(key_file),
                "--request",
                code,
                "--registers",
                "3",
                "--feature",
                "distribution",
                "--valid-until",
                "2027-10-19",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    assert out.read_text("utf-8").startswith("NCL1.")
    with pytest.raises(ValueError):
        tool.build_payload(
            tool.parse_request(code),
            kid="x",
            branches=None,
            registers=None,
            users=None,
            features=["teleport"],
            valid_until=None,
            support_until=None,
            issued=date.today(),
        )
