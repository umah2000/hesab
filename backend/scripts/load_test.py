"""Register load test (ROADMAP phase 4, risk R1). Run ONLY against a test database.

Simulates N registers selling at full speed through the real HTTP API — per scanned
line one barcode lookup and one quote, then checkout — and reports throughput and
latency percentiles.

    python scripts/load_test.py --base http://127.0.0.1:8080 --setup   # once: data
    python scripts/load_test.py --base http://127.0.0.1:8080 --registers 7 --seconds 120

--setup logs in as an administrator (LOAD_ADMIN_USER/LOAD_ADMIN_PASSWORD or asked; never stored) and creates registers,
cashiers, items with barcodes and opening stock. Standard library only.
"""

from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import os
import random
import statistics
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta

CASHIER_PASSWORD = "Load-Test-2026"  # test accounts on a test database only


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/") + "/api/v1"
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method: str, path: str, body: object = None, headers: dict | None = None):
        h = {"Content-Type": "application/json", **(headers or {})}
        csrf = next((c.value for c in self.jar if c.name == "nextcam_csrf"), None)
        if csrf and method != "GET":
            h["X-CSRF-Token"] = csrf
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with self.op.open(req, timeout=60) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, json.loads(raw) if raw else None

    def ok(self, method: str, path: str, body: object = None, headers: dict | None = None):
        status, data = self.call(method, path, body, headers)
        if status >= 300:
            raise RuntimeError(f"{method} {path} → {status} {data}")
        return data


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def ean13(first12: str) -> str:
    s = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return first12 + str((10 - s % 10) % 10)


def setup(base: str, registers: int, items: int) -> None:
    admin = Client(base)
    user = os.environ.get("LOAD_ADMIN_USER") or input("admin username: ")
    password = os.environ.get("LOAD_ADMIN_PASSWORD") or getpass.getpass()
    admin.ok("POST", "/auth/login", {"username": user, "password": password})
    roles = {r["code"]: r["id"] for r in admin.ok("GET", "/roles")}
    me = admin.ok("GET", "/auth/me")
    if "inventory.item.manage" not in me["permissions"]:
        # Test database only: the administrator also needs to create items and stock.
        u = admin.ok("GET", f"/users/{me['id']}")
        ids = [r["id"] for r in u["roles"]] + [roles["MGR"], roles["WHK"]]
        admin.ok("PATCH", f"/users/{me['id']}", {"role_ids": ids}, {"If-Match": u["row_version"]})
        admin.ok("POST", "/auth/login", {"username": user, "password": password})
        print("note: MGR and WHK roles added to the administrator (test database)")
    branch = admin.ok("GET", "/organization/branches")[0]
    have = {
        r["code"] for r in admin.ok("GET", f"/organization/branches/{branch['id']}/cash-registers")
    }
    for i in range(1, registers + 1):
        if f"L{i}" not in have:
            admin.ok(
                "POST",
                "/organization/cash-registers",
                {"branch_id": branch["id"], "code": f"L{i}", "name": f"صندوق بار {i}"},
                idem(),
            )
        admin.call(
            "POST",
            "/users",
            {
                "username": f"load{i}",
                "full_name": f"صندوق‌دار بار {i}",
                "password": CASHIER_PASSWORD,
                "role_ids": [roles["CSH"]],
                "branch_ids": [branch["id"]],
                "must_change_password": False,
            },
            idem(),
        )
    units = {u["code"]: u["id"] for u in admin.ok("GET", "/inventory/units")}
    wh = next(w for w in admin.ok("GET", "/inventory/warehouses") if w["branch_id"] == branch["id"])
    lines = []
    for n in range(items):
        code = f"LT{n:05d}"
        status, item = admin.call(
            "POST",
            "/inventory/items",
            {
                "code": code,
                "name": f"کالای آزمون بار {n}",
                "base_unit_id": units["PCS"],
                "vat_exempt": n % 3 == 0,
                "barcodes": [{"barcode": ean13(f"699{n:09d}")}],
                "prices": [{"unit_id": units["PCS"], "price": str(10_000 + (n % 50) * 5_000)}],
            },
            idem(),
        )
        if status == 201:
            lines.append({"item_id": item["id"], "qty": "100000", "unit_cost": "8000"})
    if lines:
        doc = admin.ok(
            "POST",
            "/inventory/stock-documents",
            {
                "doc_type": "opening",
                "warehouse_id": wh["id"],
                "document_date": (date.today() - timedelta(days=1)).isoformat(),
                "lines": lines,
            },
            idem(),
        )
        admin.ok(
            "POST",
            f"/inventory/stock-documents/{doc['id']}/finalize",
            headers={"If-Match": doc["row_version"]},
        )
    print(f"setup done: {registers} registers, {len(lines)} items with stock")


def run(
    base: str,
    registers: int,
    seconds: float,
    items: int,
    scan_gap: float = 0.0,
    customer_gap: float = 0.0,
) -> None:
    barcodes = [ean13(f"699{n:09d}") for n in range(items)]
    stats: dict[str, list[float]] = {"lookup": [], "quote": [], "checkout": []}
    errors: list[str] = []
    done: list[float] = []
    lock = threading.Lock()
    start_evt = threading.Event()
    stop_at = [0.0]

    def cashier(i: int) -> None:
        c = Client(base)
        c.ok("POST", "/auth/login", {"username": f"load{i}", "password": CASHIER_PASSWORD})
        reg = next(
            r["id"]
            for b in c.ok("GET", "/organization/branches")
            for r in c.ok("GET", f"/organization/branches/{b['id']}/cash-registers")
            if r["code"] == f"L{i}"
        )
        state = c.ok("GET", f"/sales/registers/{reg}/state")
        if state["shift"] is None:
            c.ok(
                "POST", "/sales/shifts/open", {"cash_register_id": reg, "opening_cash": "0"}, idem()
            )
        rnd = random.Random(i)
        start_evt.wait()
        while time.monotonic() < stop_at[0]:
            cart: list[dict] = []
            try:
                for _ in range(rnd.randint(3, 8)):
                    t = time.perf_counter()
                    found = c.ok("GET", f"/inventory/items/lookup?barcode={rnd.choice(barcodes)}")
                    stats_add("lookup", time.perf_counter() - t)
                    cart.append({"item_id": found["item_id"], "qty": "1"})
                    t = time.perf_counter()
                    quote = c.ok("POST", "/sales/quote", {"cash_register_id": reg, "lines": cart})
                    stats_add("quote", time.perf_counter() - t)
                    if scan_gap:
                        time.sleep(scan_gap * (0.5 + rnd.random()))
                t = time.perf_counter()
                c.ok(
                    "POST",
                    "/sales/invoices",
                    {
                        "id": str(uuid.uuid4()),
                        "cash_register_id": reg,
                        "lines": cart,
                        "payments": [{"method": "cash", "amount": quote["grand_total"]}],
                    },
                    idem(),
                )
                stats_add("checkout", time.perf_counter() - t)
                with lock:
                    done.append(time.monotonic())
                if customer_gap:
                    time.sleep(customer_gap * (0.5 + rnd.random()))
            except Exception as e:  # noqa: BLE001 - report, keep the register running
                with lock:
                    errors.append(str(e)[:200])

    def stats_add(k: str, v: float) -> None:
        with lock:
            stats[k].append(v)

    threads = [threading.Thread(target=cashier, args=(i,)) for i in range(1, registers + 1)]
    for t in threads:
        t.start()
    time.sleep(3)  # logins and shifts
    t0 = time.monotonic()
    stop_at[0] = t0 + seconds
    start_evt.set()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - t0

    def pct(xs: list[float], p: float) -> str:
        if not xs:
            return "-"
        xs = sorted(xs)
        return f"{xs[min(len(xs) - 1, int(len(xs) * p))] * 1000:.0f}ms"

    per_sec = [0] * (int(elapsed) + 1)
    for d in done:
        per_sec[int(d - t0)] += 1
    print(f"registers={registers} seconds={elapsed:.0f} invoices={len(done)} errors={len(errors)}")
    print(f"throughput={len(done) / elapsed:.2f} invoices/s (best second: {max(per_sec)})")
    for k, xs in stats.items():
        mean = f"{statistics.mean(xs) * 1000:.0f}ms" if xs else "-"
        print(
            f"{k:9s} n={len(xs):5d} mean={mean} p50={pct(xs, 0.5)} p95={pct(xs, 0.95)} p99={pct(xs, 0.99)}"
        )
    for e in errors[:5]:
        print("error:", e)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--registers", type=int, default=7)
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--items", type=int, default=2000)
    ap.add_argument("--setup", action="store_true")
    # Human pace (0 = as fast as possible): seconds between scans / between customers.
    ap.add_argument("--scan-gap", type=float, default=0.0)
    ap.add_argument("--customer-gap", type=float, default=0.0)
    a = ap.parse_args()
    if a.setup:
        setup(a.base, a.registers, a.items)
    else:
        run(a.base, a.registers, a.seconds, a.items, a.scan_gap, a.customer_gap)


if __name__ == "__main__":
    main()
