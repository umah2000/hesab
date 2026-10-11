from __future__ import annotations

import pytest

from tests.conftest import Api, Seed, new_key

pytestmark = pytest.mark.db


def test_settings_defaults_and_update(admin: Api) -> None:
    org = admin.get("/api/v1/organization/settings").get_json()
    assert org["display_currency"] == "IRT"
    assert org["negative_stock_policy"] == "warn"
    resp = admin.put(
        "/api/v1/organization/settings",
        {"display_currency": "IRR", "name": "سوپرمارکت نمونه"},
        org["row_version"],
    )
    assert resp.status_code == 200
    assert resp.get_json()["display_currency"] == "IRR"
    stale = admin.put(
        "/api/v1/organization/settings", {"display_currency": "IRT"}, org["row_version"]
    )
    assert stale.status_code == 409
    invalid = admin.put(
        "/api/v1/organization/settings", {"display_currency": "USD"}, resp.get_json()["row_version"]
    )
    assert invalid.status_code == 400
    events = admin.get("/api/v1/audit/events?action=settings").get_json()
    assert events["total"] == 1
    assert events["items"][0]["data"]["after"]["display_currency"] == "IRR"


def test_branch_and_register_crud(admin: Api, seed: Seed) -> None:
    created = admin.post(
        "/api/v1/organization/branches", {"code": "03", "name": "شعبه سه"}, idem=new_key()
    )
    assert created.status_code == 201
    branch = created.get_json()
    dup = admin.post(
        "/api/v1/organization/branches", {"code": "03", "name": "تکراری"}, idem=new_key()
    )
    assert dup.status_code == 409
    reg = admin.post(
        "/api/v1/organization/cash-registers",
        {"branch_id": branch["id"], "code": "r1", "name": "صندوق ۱"},
        idem=new_key(),
    )
    assert reg.status_code == 201
    assert reg.get_json()["code"] == "R1"
    regs = admin.get(f"/api/v1/organization/branches/{branch['id']}/cash-registers").get_json()
    assert [r["code"] for r in regs] == ["R1"]
    off = admin.patch(
        f"/api/v1/organization/branches/{branch['id']}", {"is_active": False}, branch["row_version"]
    )
    assert off.status_code == 200 and off.get_json()["is_active"] is False


def test_audit_requires_permission_and_paginates(admin: Api) -> None:
    page = admin.get("/api/v1/audit/events?page_size=1").get_json()
    assert page["page_size"] == 1
    assert page["total"] >= 1
    assert page["items"][0]["username"] == "admin"
