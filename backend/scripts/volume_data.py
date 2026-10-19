"""Months of supermarket history for performance tests (phase 10). DISPOSABLE DATABASES ONLY.

Every document goes through the real API and services (in-process, Flask test client),
so stock, costing, vouchers, numbering and the database triggers are exercised exactly as
in production; only the clock is simulated (``app.core.db.utcnow``), day by day.

    NEXTCAM_DATABASE_URL=...nextcam_load... python scripts/volume_data.py --confirm-disposable \\
        --days 180 --per-day 1500 --items 12000

Then time the screens and reports against the same database: ``scripts/volume_timing.py``.

Shape of a day (per register, Tehran time 08:00–23:00, evening peak):
- shift open with float, sales with 1–15 lines (popular items sell far more: Zipf),
  payments ~55% card / ~42% cash / ~3% credit to a customer with a credit limit,
- ~1% returns of one line of an earlier sale, shift close (sometimes short or over);
- weekly: one purchase invoice per supplier replacing what was sold, and bank receipts
  from customers who bought on credit.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import random
import secrets
import sys
import time
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# Set before the app reads its settings: generous login rate and session lifetime, since
# the simulated clock jumps a day at a time and every register logs in each morning.
os.environ.setdefault("NEXTCAM_LOGIN_RATE_LIMIT", "100000 per minute")
os.environ.setdefault("NEXTCAM_SESSION_ABSOLUTE_HOURS", "24")
os.environ.setdefault("NEXTCAM_SESSION_IDLE_MINUTES", "1440")
os.environ.setdefault("NEXTCAM_COOKIE_SECURE", "false")
os.environ.setdefault("NEXTCAM_SECRET_KEY", secrets.token_urlsafe(32))

TEHRAN = timedelta(hours=3, minutes=30)  # no DST in Iran since 2022

# --- simulated clock ------------------------------------------------------------------

_now: list[datetime | None] = [None]


def _patch_clock() -> None:
    from app.core import db

    real = db.utcnow

    def sim_utcnow() -> datetime:
        return _now[0] or real()

    for m in list(sys.modules.values()):
        if m is not None and m.__name__.startswith("app") and getattr(m, "utcnow", None) is real:
            m.utcnow = sim_utcnow  # type: ignore[attr-defined]


def at(day: date, minutes_after_midnight_tehran: float) -> datetime:
    local = datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(
        minutes=minutes_after_midnight_tehran
    )
    return local - TEHRAN


# --- in-process client ----------------------------------------------------------------


class Client:
    def __init__(self, app: Any) -> None:
        self.c = app.test_client()

    def call(self, method: str, path: str, body: Any = None, headers: dict | None = None):
        h = dict(headers or {})
        csrf = self.c.get_cookie("nextcam_csrf")
        if csrf is not None and method != "GET":
            h["X-CSRF-Token"] = csrf.value
        r = self.c.open("/api/v1" + path, method=method, json=body, headers=h)
        return r.status_code, r.get_json(silent=True)

    def ok(self, method: str, path: str, body: Any = None, headers: dict | None = None):
        status, data = self.call(method, path, body, headers)
        if status >= 300:
            raise RuntimeError(f"{method} {path} → {status} {json.dumps(data, ensure_ascii=False)}")
        return data

    def post(self, path: str, body: Any = None, *, if_match: str | None = None):
        h = {"Idempotency-Key": str(uuid.uuid4())}
        if if_match:
            h["If-Match"] = if_match
        return self.ok("POST", path, body, h)

    def login(self, username: str, password: str) -> None:
        self.c.delete_cookie("nextcam_session")
        self.ok("POST", "/auth/login", {"username": username, "password": password})


def make_app():
    from app import create_app

    app = create_app()
    _patch_clock()
    return app


# --- set-up ----------------------------------------------------------------------------


def ean13(first12: str) -> str:
    s = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return first12 + str((10 - s % 10) % 10)


GROUPS = [
    ("DAIRY", "لبنیات"),
    ("BAKERY", "نان و شیرینی"),
    ("DRINK", "نوشیدنی"),
    ("SNACK", "تنقلات"),
    ("GROCERY", "خواربار"),
    ("CANNED", "کنسرو"),
    ("CLEAN", "شوینده"),
    ("HYGIENE", "بهداشتی"),
    ("FROZEN", "منجمد"),
    ("FRUIT", "میوه و سبزی"),
]


def setup(app: Any, a: argparse.Namespace, password: str) -> dict[str, Any]:
    from sqlalchemy import func, select

    from app.core.db import unit_of_work
    from app.core.numbering import ensure_counters
    from app.core.security import hash_password
    from app.modules.accounting.models import FiscalYear
    from app.modules.accounting.services.chart import seed_defaults
    from app.modules.accounting.services.fiscal import current_jalali_year, ensure_year
    from app.modules.iam.models import AppUser, Role, UserScope
    from app.modules.iam.permissions import ADMIN_ROLE
    from app.modules.iam.services.roles import sync_catalog
    from app.modules.inventory.services.catalog import seed_catalog
    from app.modules.inventory.services.stock import ensure_default_warehouses
    from app.modules.organization.models import Branch
    from app.modules.organization.services import ensure_organization
    from app.modules.sales.models import SalesInvoice

    start = a.end - timedelta(days=a.days)
    with app.app_context(), unit_of_work() as s:
        if s.scalar(select(func.count()).select_from(SalesInvoice)):
            raise SystemExit("this database already has sales; use an empty, disposable one")
        ensure_organization(s, "سوپرمارکت آزمون حجم")
        sync_catalog(s)
        seed_defaults(s)
        for y in sorted({current_jalali_year(start), current_jalali_year(a.end)}):
            ensure_year(s, y)
        seed_catalog(s)
        if s.scalar(select(Branch).where(Branch.code == "01")) is None:
            s.add(Branch(code="01", name="شعبه مرکزی", is_active=True))
            s.flush()
        ensure_default_warehouses(s)
        ensure_counters(
            s,
            list(s.scalars(select(FiscalYear.id).where(FiscalYear.status == "open"))),
            list(s.scalars(select(Branch.id))),
        )
        admin_role = s.scalar(select(Role).where(Role.code == ADMIN_ROLE))
        mgr = s.scalar(select(Role).where(Role.code == "MGR"))
        whk = s.scalar(select(Role).where(Role.code == "WHK"))
        acc = s.scalar(select(Role).where(Role.code == "ACC"))
        pur = s.scalar(select(Role).where(Role.code == "PUR"))
        u = AppUser(
            username="vol_admin",
            full_name="مدیر آزمون حجم",
            password_hash=hash_password(password),
            is_active=True,
            must_change_password=False,
            failed_attempts=0,
        )
        u.roles = [r for r in (admin_role, mgr, whk, acc, pur) if r is not None]
        u.scopes = [UserScope(branch_id=None)]
        s.add(u)

    _now[0] = at(start - timedelta(days=2), 9 * 60)
    admin = Client(app)
    admin.login("vol_admin", password)
    branch = admin.ok("GET", "/organization/branches")[0]["id"]
    roles = {r["code"]: r["id"] for r in admin.ok("GET", "/roles")}
    regs = []
    for i in range(1, a.registers + 1):
        reg = admin.post(
            "/organization/cash-registers",
            {"branch_id": branch, "code": f"R{i}", "name": f"صندوق {i}"},
        )
        admin.post(
            "/users",
            {
                "username": f"vol_r{i}",
                "full_name": f"صندوق‌دار {i}",
                "password": password,
                "role_ids": [roles["SUP"]],
                "branch_ids": [branch],
                "must_change_password": False,
            },
        )
        regs.append(reg["id"])
    units = {u["code"]: u["id"] for u in admin.ok("GET", "/inventory/units")}
    wh = next(w for w in admin.ok("GET", "/inventory/warehouses") if w["branch_id"] == branch)
    groups = [admin.post("/inventory/groups", {"code": c, "name": n})["id"] for c, n in GROUPS]
    bank = admin.post(
        "/treasury/accounts",
        {"code": "BANK-01", "name": "بانک ملت جاری", "kind": "bank", "bank_name": "ملت"},
    )["id"]

    rnd = random.Random(a.seed)
    t0 = time.monotonic()
    items: list[dict[str, Any]] = []
    for n in range(a.items):
        price = rnd.choice([1, 2, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 30, 45, 60, 90, 150])
        price *= 10_000 + rnd.randrange(0, 50) * 1_000
        g = n % len(GROUPS)
        body = {
            "code": f"V{n:05d}",
            "name": f"{GROUPS[g][1]} — کالای {n}",
            "group_id": groups[g],
            "base_unit_id": units["PCS"],
            "vat_exempt": g in (0, 1, 9),
            "barcodes": [{"barcode": ean13(f"626{n:09d}")}],
            "prices": [{"unit_id": units["PCS"], "price": str(price)}],
        }
        made = admin.post("/inventory/items", body)
        items.append(
            {
                "id": made["id"],
                "price": price,
                "vat": 0 if body["vat_exempt"] else 10,
                "barcode": body["barcodes"][0]["barcode"],
            }
        )
        if n and n % 2000 == 0:
            print(f"  items {n} ({time.monotonic() - t0:.0f}s)", flush=True)

    suppliers = [
        admin.post(
            "/parties",
            {
                "code": f"S{k:03d}",
                "name": f"پخش {k}",
                "is_customer": False,
                "is_supplier": True,
                "payment_terms_days": 30,
            },
        )["id"]
        for k in range(a.suppliers)
    ]
    customers = []
    for k in range(a.customers):
        limit = str(rnd.choice([50, 100, 200, 500]) * 1_000_000) if k % 3 == 0 else None
        c = admin.post(
            "/parties",
            {
                "code": f"C{k:05d}",
                "name": f"مشتری {k}",
                "mobile": f"0912{k:07d}",
                "credit_limit": limit,
            },
        )
        if limit:
            customers.append(c["id"])
    print(
        f"master data: {len(items)} items, {len(customers)} credit customers "
        f"({time.monotonic() - t0:.0f}s)",
        flush=True,
    )
    return {
        "branch": branch,
        "warehouse": wh["id"],
        "registers": regs,
        "items": items,
        "suppliers": suppliers,
        "customers": customers,
        "bank": bank,
        "start": start.isoformat(),
    }


def weights(n: int) -> list[float]:
    """Zipf-like popularity: a few hundred items make most of the sales."""
    return [1.0 / (r + 8) ** 1.05 for r in range(n)]


def opening_stock(app: Any, a: argparse.Namespace, password: str, w: dict[str, Any]) -> None:
    admin = Client(app)
    start = date.fromisoformat(w["start"])
    _now[0] = at(start - timedelta(days=1), 9 * 60)
    admin.login("vol_admin", password)
    ws = weights(len(w["items"]))
    total = sum(ws)
    lines_per_day = a.per_day * 6
    lines = []
    for it, wt in zip(w["items"], ws, strict=True):
        # three weeks of demand (purchases top up weekly) plus a shelf minimum
        qty = math.ceil(wt / total * lines_per_day * 1.3 * 21) + 6
        lines.append(
            {"item_id": it["id"], "qty": str(qty), "unit_cost": str(it["price"] * 78 // 100)}
        )
    for i in range(0, len(lines), 5000):
        doc = admin.post(
            "/inventory/stock-documents",
            {
                "doc_type": "opening",
                "warehouse_id": w["warehouse"],
                "document_date": (start - timedelta(days=1)).isoformat(),
                "lines": lines[i : i + 5000],
            },
        )
        admin.post(f"/inventory/stock-documents/{doc['id']}/finalize", if_match=doc["row_version"])


# --- one register, one day (worker process) --------------------------------------------

_W: dict[str, Any] = {}


def _init_worker(world: dict[str, Any], password: str, seed: int) -> None:
    _W["app"] = make_app()
    _W["world"], _W["password"], _W["seed"] = world, password, seed
    ws = weights(len(world["items"]))
    acc, run = [], 0.0
    for x in ws:
        run += x
        acc.append(run)
    _W["cum"] = acc


def _times(rnd: random.Random, n: int) -> list[float]:
    """Minutes after midnight: open 08:00–23:00, a lunch bump and an evening peak."""
    out = []
    while len(out) < n:
        r = rnd.random()
        if r < 0.25:
            t = rnd.uniform(8 * 60, 23 * 60)
        elif r < 0.45:
            t = rnd.gauss(13 * 60, 60)
        else:
            t = rnd.gauss(19 * 60 + 30, 90)
        if 8 * 60 <= t < 23 * 60:
            out.append(t)
    return sorted(out)


def sell_day(job: tuple[str, int, int]) -> dict[str, Any]:
    day_s, reg_no, count = job
    day = date.fromisoformat(day_s)
    w, app = _W["world"], _W["app"]
    rnd = random.Random(f"{_W['seed']}-{day_s}-{reg_no}")
    reg = w["registers"][reg_no - 1]
    items, cum = w["items"], _W["cum"]
    by_id = {it["id"]: it for it in items}
    c = Client(app)
    _now[0] = at(day, 7 * 60 + 50)
    c.login(f"vol_r{reg_no}", _W["password"])
    shift = c.post("/sales/shifts/open", {"cash_register_id": reg, "opening_cash": "5000000"})
    sold: Counter[str] = Counter()
    credit: Counter[str] = Counter()
    made: list[dict[str, Any]] = []
    stats = {"invoices": 0, "returns": 0, "lines": 0, "quotes": 0, "errors": 0, "ms": 0.0}
    first_error = None
    for minute in _times(rnd, count):
        _now[0] = at(day, minute)
        n_lines = min(15, max(1, int(rnd.expovariate(1 / 5.5)) + 1))
        cart: dict[str, int] = {}
        for _ in range(n_lines):
            i = bisect_cum(cum, rnd.random() * cum[-1])
            cart[items[i]["id"]] = cart.get(items[i]["id"], 0) + rnd.choice((1, 1, 1, 1, 2, 3))
        lines = [{"item_id": k, "qty": str(v)} for k, v in cart.items()]
        try:
            t = time.perf_counter()
            # The register quotes every scan; here the total is estimated (prices are
            # VAT-exclusive, default rate 10%) and the server quote is fetched only when the
            # server disagrees, which halves the requests per sale.
            total = sum(
                (
                    Decimal(by_id[k]["price"] * v)
                    + rial(Decimal(by_id[k]["price"] * v * by_id[k]["vat"]) / 100)
                    for k, v in cart.items()
                ),
                Decimal(0),
            )
            r = rnd.random()
            body: dict[str, Any] = {
                "id": str(uuid.uuid4()),
                "cash_register_id": reg,
                "lines": lines,
            }
            method = "credit" if r < 0.03 and w["customers"] else "card" if r < 0.58 else "cash"
            if method == "credit":
                body["customer_id"] = rnd.choice(w["customers"])
            inv = None
            for _attempt in range(3):
                pay: dict[str, Any] = {"method": method, "amount": str(total)}
                if method == "card":
                    pay["card_reference"] = f"{rnd.randrange(10**11, 10**12)}"
                body["payments"] = [pay]
                status, inv = c.call(
                    "POST", "/sales/invoices", body, {"Idempotency-Key": str(uuid.uuid4())}
                )
                code = (inv or {}).get("error", {}).get("code") if status >= 300 else None
                if code is None:
                    break
                if code == "payment_mismatch":
                    stats["quotes"] += 1
                    q = c.ok("POST", "/sales/quote", {"cash_register_id": reg, "lines": lines})
                    total = Decimal(q["grand_total"])
                elif code == "credit_limit_exceeded":
                    body.pop("customer_id")
                    method = "cash"
                else:
                    raise RuntimeError(f"checkout {status} {inv}")
            else:
                raise RuntimeError(f"checkout failed {inv}")
            assert inv is not None
            stats["ms"] += (time.perf_counter() - t) * 1000
            stats["invoices"] += 1
            stats["lines"] += len(lines)
            for k, v in cart.items():
                sold[k] += v
            if method == "credit":
                credit[body["customer_id"]] += int(total)
            made.append(inv)
            if rnd.random() < 0.01 and len(made) > 3:
                orig = rnd.choice(made[:-1])
                ln = rnd.choice(orig["lines"])
                if Decimal(ln["returned_qty"]) == 0:
                    _now[0] = at(day, minute + 1)
                    c.post(
                        f"/sales/invoices/{orig['id']}/returns",
                        {
                            "cash_register_id": reg,
                            "lines": [{"original_line_id": ln["id"], "qty": "1"}],
                            "refunds": [{"method": "cash"}],
                            "reason": "مرجوعی مشتری",
                        },
                    )
                    sold[ln["item_id"]] -= 1
                    stats["returns"] += 1
        except Exception as e:  # noqa: BLE001 - count, keep the register selling
            stats["errors"] += 1
            first_error = first_error or str(e)[:300]
    _now[0] = at(day, 23 * 60 + 5)
    rep = c.ok("GET", f"/sales/shifts/{shift['id']}/report")
    expected = Decimal(rep["expected_cash"])
    off = rnd.random()
    counted = expected - 50_000 if off < 0.08 else expected + 20_000 if off < 0.12 else expected
    c.post(
        f"/sales/shifts/{shift['id']}/close",
        {"counted_cash": str(max(counted, Decimal(0)))},
        if_match=rep["shift"]["row_version"],
    )
    return {"sold": dict(sold), "credit": dict(credit), "stats": stats, "error": first_error}


def rial(d: Decimal) -> Decimal:
    return d.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def bisect_cum(cum: list[float], x: float) -> int:
    lo, hi = 0, len(cum) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cum[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


# --- weekly back office (main process) --------------------------------------------------


def restock(admin: Client, w: dict[str, Any], day: date, sold: Counter[str]) -> int:
    by_id = {it["id"]: it for it in w["items"]}
    sup = w["suppliers"]
    per_supplier: dict[str, list[dict[str, Any]]] = {}
    for n, it in enumerate(w["items"]):
        q = sold.get(it["id"], 0)
        if q > 0:
            per_supplier.setdefault(sup[n % len(sup)], []).append(
                {
                    "item_id": it["id"],
                    "qty": str(q),
                    "unit_cost": str(by_id[it["id"]]["price"] * 78 // 100),
                }
            )
    made = 0
    for k, (supplier, lines) in enumerate(per_supplier.items()):
        for i in range(0, len(lines), 500):
            _now[0] = at(day, 7 * 60 + k)
            inv = admin.post(
                "/purchasing/invoices",
                {
                    "warehouse_id": w["warehouse"],
                    "supplier_id": supplier,
                    "document_date": day.isoformat(),
                    "supplier_invoice_no": f"F-{day:%m%d}-{k}-{i}",
                    "lines": lines[i : i + 500],
                },
            )
            admin.post(f"/purchasing/invoices/{inv['id']}/finalize", if_match=inv["row_version"])
            made += 1
    return made


def collect(admin: Client, w: dict[str, Any], day: date, credit: Counter[str]) -> int:
    n = 0
    for k, (cust, amount) in enumerate(credit.items()):
        pay = amount * 7 // 10
        if pay <= 0:
            continue
        _now[0] = at(day, 23 * 60 + 20 + k % 30)
        admin.post(
            "/treasury/receipts",
            {
                "branch_id": w["branch"],
                "document_date": day.isoformat(),
                "party_id": cust,
                "lines": [
                    {
                        "method": "bank",
                        "money_account_id": w["bank"],
                        "amount": str(pay),
                        "reference": f"T{k}",
                    }
                ],
            },
        )
        credit[cust] -= pay
        n += 1
    return n


# --- main --------------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--confirm-disposable", action="store_true", required=True)
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--end", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    ap.add_argument("--per-day", type=int, default=1500, help="sales per day, all registers")
    ap.add_argument("--registers", type=int, default=7)
    ap.add_argument("--items", type=int, default=12000)
    ap.add_argument("--customers", type=int, default=1500)
    ap.add_argument("--suppliers", type=int, default=40)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--seed", type=int, default=1405)
    ap.add_argument("--state", default="volume_state.json", help="world ids, for timing")
    a = ap.parse_args()
    if os.environ.get("NEXTCAM_ENV") == "production":
        raise SystemExit("refusing to run with NEXTCAM_ENV=production")
    # Users of this run share one random password that exists only in memory.
    password = "Vol-" + secrets.token_urlsafe(12) + "9"

    app = make_app()
    t0 = time.monotonic()
    w = setup(app, a, password)
    opening_stock(app, a, password, w)
    with open(a.state, "w", encoding="utf-8") as f:
        json.dump(
            {k: v for k, v in w.items() if k != "items"}
            | {"barcodes": [i["barcode"] for i in w["items"][:500]]},
            f,
        )

    admin = Client(app)
    start = date.fromisoformat(w["start"])
    week_sold: Counter[str] = Counter()
    week_credit: Counter[str] = Counter()
    totals = Counter()
    ctx = mp.get_context("spawn")
    with ctx.Pool(a.workers, initializer=_init_worker, initargs=(w, password, a.seed)) as pool:
        for d in range(a.days):
            day = start + timedelta(days=d)
            rnd = random.Random(f"{a.seed}-{day}")
            # Fridays are busier, a quiet day now and then.
            factor = 1.3 if day.weekday() == 4 else 0.8 if rnd.random() < 0.1 else 1.0
            n = int(a.per_day * factor * rnd.uniform(0.9, 1.1))
            per_reg = [
                n // a.registers + (1 if i < n % a.registers else 0) for i in range(a.registers)
            ]
            if d % 7 == 6 or d == a.days - 1:
                _now[0] = at(day, 6 * 60 + 30)
                admin.login("vol_admin", password)
                totals["purchases"] += restock(admin, w, day, week_sold)
                week_sold.clear()
            t = time.monotonic()
            results = pool.map(
                sell_day, [(day.isoformat(), i + 1, c) for i, c in enumerate(per_reg)]
            )
            for r in results:
                week_sold.update(r["sold"])
                week_credit.update(r["credit"])
                for k, v in r["stats"].items():
                    totals[k] += v
                if r["error"]:
                    print("  error:", r["error"], flush=True)
            if d % 7 == 6 or d == a.days - 1:
                _now[0] = at(day, 23 * 60 + 15)
                admin.login("vol_admin", password)
                totals["receipts"] += collect(admin, w, day, week_credit)
            dt = time.monotonic() - t
            print(
                f"{day} sales={sum(r['stats']['invoices'] for r in results)} "
                f"({dt:.0f}s) total={totals['invoices']} errors={totals['errors']} "
                f"elapsed={(time.monotonic() - t0) / 60:.0f}m",
                flush=True,
            )
    totals["ms"] = int(totals["ms"] / max(1, totals["invoices"]))
    print("done:", dict(totals), f"in {(time.monotonic() - t0) / 60:.0f} minutes")


if __name__ == "__main__":
    main()
