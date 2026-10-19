"""Screen and report timings on a large database (phase 10). DISPOSABLE DATABASES ONLY.

Run after ``scripts/volume_data.py`` against the same ``NEXTCAM_DATABASE_URL``:

    python scripts/volume_timing.py --confirm-disposable --state volume_state.json

Requests go through the real Flask app in-process (routing, permissions, serialization;
no network). Each request runs once cold and then ``--repeat`` times; the table shows the
row counts of the database, then per request the cold time, median and maximum.
The ``vol_admin`` password is replaced by a random one that exists only in this process.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import statistics
import time
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("NEXTCAM_COOKIE_SECURE", "false")
os.environ.setdefault("NEXTCAM_SECRET_KEY", secrets.token_urlsafe(32))

TABLES = [
    "item",
    "item_barcode",
    "sales_invoice",
    "sales_invoice_line",
    "sales_payment",
    "stock_ledger",
    "stock_document",
    "voucher",
    "voucher_line",
    "purchase_invoice",
    "treasury_document",
    "detail_account",
    "audit_event",
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--confirm-disposable", action="store_true", required=True)
    ap.add_argument("--state", default="volume_state.json")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--out", default=None, help="also write the results as JSON here")
    a = ap.parse_args()
    if os.environ.get("NEXTCAM_ENV") == "production":
        raise SystemExit("refusing to run with NEXTCAM_ENV=production")

    from sqlalchemy import func, select, text

    from app import create_app
    from app.core.db import new_session, unit_of_work
    from app.core.security import hash_password
    from app.modules.accounting.models import FiscalYear, VoucherLine
    from app.modules.iam.models import AppUser
    from app.modules.sync.services import snapshot as snap

    with open(a.state, encoding="utf-8") as f:
        w = json.load(f)
    app = create_app()
    password = "Tm-" + secrets.token_urlsafe(12) + "7"
    with app.app_context(), unit_of_work() as s:
        admin = s.scalar(select(AppUser).where(AppUser.username == "vol_admin"))
        if admin is None:
            raise SystemExit("no vol_admin: run scripts/volume_data.py first")
        admin.password_hash = hash_password(password)
        counts = {}
        for t in TABLES:
            counts[t] = s.scalar(text(f"SELECT COUNT_BIG(*) FROM {t}"))  # noqa: S608 - fixed names
        fy = str(s.scalar(select(FiscalYear.id).order_by(FiscalYear.start_date.desc())))
        busiest = s.execute(
            select(VoucherLine.account_id, func.count())
            .group_by(VoucherLine.account_id)
            .order_by(func.count().desc())
        ).first()
        account = str(busiest[0]) if busiest else ""
        top_customer = s.scalar(
            text(
                "SELECT TOP 1 customer_id FROM sales_invoice WHERE customer_id IS NOT NULL "
                "GROUP BY customer_id ORDER BY COUNT(*) DESC"
            )
        )
        size_mb = s.scalar(
            text("SELECT SUM(size) * 8 / 1024 FROM sys.database_files WHERE type = 0")
        )

    c = app.test_client()
    r = c.post("/api/v1/auth/login", json={"username": "vol_admin", "password": password})
    assert r.status_code == 200, r.get_json()
    csrf = c.get_cookie("nextcam_csrf")
    assert csrf is not None
    hdr = {"X-CSRF-Token": csrf.value}

    end = date.fromisoformat(w["start"]) + timedelta(days=10_000)
    with app.app_context():
        s = new_session()
        try:
            end = s.scalar(text("SELECT MAX(document_date) FROM sales_invoice")) or date.today()
        finally:
            s.close()
    start = date.fromisoformat(w["start"])
    month = (end - timedelta(days=29)).isoformat()
    whole = start.isoformat()
    e = end.isoformat()
    reg = w["registers"][0]
    barcode = w["barcodes"][0]
    rare = w["barcodes"][-1]
    some_item = None

    def get(path: str) -> Any:
        r = c.get("/api/v1" + path)
        if r.status_code >= 300:
            raise RuntimeError(f"GET {path} → {r.status_code} {r.get_json()}")
        return r.get_json()

    some_item = get(f"/inventory/items/lookup?barcode={barcode}")["item_id"]
    quote_lines = [
        {"item_id": get(f"/inventory/items/lookup?barcode={b}")["item_id"], "qty": "1"}
        for b in w["barcodes"][:6]
    ]

    cases: list[tuple[str, Any]] = [
        ("صندوق: جست‌وجوی بارکد (کالای پرفروش)", f"/inventory/items/lookup?barcode={barcode}"),
        ("صندوق: جست‌وجوی بارکد (کالای کم‌فروش)", f"/inventory/items/lookup?barcode={rare}"),
        (
            "صندوق: قیمت سبد ۶ قلمی",
            ("POST", "/sales/quote", {"cash_register_id": reg, "lines": quote_lines}),
        ),
        ("صندوق: وضعیت صندوق", f"/sales/registers/{reg}/state"),
        ("کالاها: جست‌وجوی نام", "/inventory/items?q=%D9%84%D8%A8%D9%86%DB%8C%D8%A7%D8%AA"),
        ("کالاها: صفحه اول", "/inventory/items"),
        ("موجودی: صفحه اول", "/inventory/balances"),
        (
            "کاردکس کالای پرفروش",
            f"/inventory/kardex?item_id={some_item}&warehouse_id={w['warehouse']}",
        ),
        ("فاکتورها: صفحه اول", "/sales/invoices"),
        ("فاکتورها: جست‌وجوی شماره", "/sales/invoices?q=50000"),
        ("داشبورد: امروز", "/reports/dashboard"),
        ("داشبورد: ۳۰ روز", f"/reports/dashboard?date_from={month}&date_to={e}"),
        ("داشبورد: کل دوره", f"/reports/dashboard?date_from={whole}&date_to={e}"),
    ]
    for g in ("day", "item", "group", "cashier", "register"):
        cases.append(
            (
                f"گزارش فروش ۳۰ روز / {g}",
                f"/reports/sales?group_by={g}&date_from={month}&date_to={e}",
            )
        )
        cases.append(
            (
                f"گزارش فروش کل دوره / {g}",
                f"/reports/sales?group_by={g}&date_from={whole}&date_to={e}",
            )
        )
    for key in ("cash-shortages", "stock-movement", "money-flow", "profit-loss"):
        cases.append((f"گزارش {key} کل دوره", f"/reports/{key}?date_from={whole}&date_to={e}"))
    for key in ("slow-moving", "near-expiry", "debtors", "creditors", "balance-sheet"):
        cases.append((f"گزارش {key}", f"/reports/{key}"))
    cases += [
        (
            "گزارش فروش کل دوره / کالا — Excel",
            f"/reports/sales?group_by=item&date_from={whole}&date_to={e}&format=xlsx",
        ),
        ("تراز آزمایشی", f"/accounting/reports/trial-balance?fiscal_year_id={fy}"),
        (
            "دفتر حساب پرگردش (صفحه اول)",
            f"/accounting/reports/ledger?fiscal_year_id={fy}&account_id={account}",
        ),
        ("دفتر روزنامه (صفحه اول)", f"/accounting/reports/journal?fiscal_year_id={fy}"),
        ("اسناد حسابداری: صفحه اول", "/accounting/vouchers"),
        ("طرف‌حساب‌ها: صفحه اول", "/parties"),
    ]
    if top_customer:
        cases.append(("صورت‌حساب پرتراکنش‌ترین مشتری", f"/parties/{top_customer}/statement"))
    cases.append(("داده‌ی آفلاین صندوق (snapshot)", "snapshot"))

    results = []
    for label, req in cases:
        times = []
        size = 0
        for _ in range(a.repeat + 1):
            t = time.perf_counter()
            if req == "snapshot":
                with app.app_context():
                    s = new_session()
                    try:
                        out = snap.snapshot(s, SimpleNamespace(cash_register_id=reg, id=None))  # type: ignore[arg-type]
                        size = len(out.model_dump_json())
                    finally:
                        s.close()
            elif isinstance(req, tuple):
                r = c.open("/api/v1" + req[1], method=req[0], json=req[2], headers=hdr)
                assert r.status_code < 300, (label, r.get_json())
                size = len(r.data)
            else:
                r = c.get("/api/v1" + req)
                assert r.status_code < 300, (label, r.status_code, r.get_data(as_text=True)[:300])
                size = len(r.data)
            times.append((time.perf_counter() - t) * 1000)
        cold, warm = times[0], times[1:]
        row = {
            "label": label,
            "cold_ms": round(cold),
            "p50_ms": round(statistics.median(warm)),
            "max_ms": round(max(warm)),
            "kb": round(size / 1024),
        }
        results.append(row)
        print(
            f"{row['p50_ms']:>7} ms  (cold {row['cold_ms']:>6}, max {row['max_ms']:>6}, {row['kb']:>6} KB)  {label}",
            flush=True,
        )

    print("\nrows:", json.dumps(counts), f"data file ≈ {size_mb} MB")
    print(f"period: {whole} .. {e}")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(
                {"counts": counts, "data_mb": size_mb, "results": results},
                f,
                ensure_ascii=False,
                indent=1,
            )


if __name__ == "__main__":
    main()
