"""Command line: ``nextcam-agent pair|run|status|render|unpair``."""

from __future__ import annotations

import argparse
import json
import logging
import platform
import signal
import sys
import threading
import urllib.request
from collections.abc import Callable
from logging.handlers import RotatingFileHandler

from nextcam_agent import __version__, config
from nextcam_agent.client import ServerClient, ServerError
from nextcam_agent.gateway import Gateway
from nextcam_agent.gateway import serve_in_background as serve_gateway
from nextcam_agent.localapi import serve_in_background
from nextcam_agent.runner import Agent
from nextcam_agent.store import Store
from nextcam_agent.syncer import Local, Syncer


def setup_logging(verbose: bool = False) -> None:
    d = config.data_dir()
    d.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        d / "agent.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler, logging.StreamHandler()]
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


def cmd_pair(args: argparse.Namespace) -> int:
    client = ServerClient(args.server)
    try:
        resp = client.pair(args.code, f"{platform.system()} {platform.release()}")
    except ServerError as e:
        print(f"جفت‌سازی ناموفق: {e.message}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"سرور در دسترس نیست: {e}", file=sys.stderr)
        return 1
    config.save_token(resp["token"])
    config.save(config.AgentConfig(args.server, resp["device_id"], resp["name"]))
    print(f"جفت شد: {resp['name']}")
    return 0


def build_agent() -> Agent:
    cfg = config.load()
    token = config.load_token()
    if cfg is None or token is None:
        raise SystemExit("ابتدا با «nextcam-agent pair» جفت‌سازی کنید")
    local = Local(Store(config.data_dir() / "register.db"))
    return Agent(cfg, ServerClient(cfg.server_url, token), local=local)


def start_services(agent: Agent, stop: threading.Event) -> Callable[[], None]:
    """Status page, register gateway and offline sync around the polling loop."""
    assert agent.local is not None
    cfg = agent.cfg
    status = serve_in_background(cfg.status_port, agent.snapshot)
    gw = Gateway(
        cfg.server_url,
        agent.local,
        config.data_dir() / "spa",
        port=cfg.gateway_port,
        device_id=cfg.device_id,
        print_fn=agent.print_local,
    )
    gateway = serve_gateway(gw)
    syncer = Syncer(agent.local, agent.client)
    threading.Thread(target=syncer.run, args=(stop,), name="sync", daemon=True).start()
    logging.info("register gateway on http://127.0.0.1:%d/", cfg.gateway_port)

    def shutdown() -> None:
        status.shutdown()
        gateway.shutdown()

    return shutdown


def cmd_run(args: argparse.Namespace) -> int:
    setup_logging(args.verbose)
    agent = build_agent()
    stop = threading.Event()
    shutdown = start_services(agent, stop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    logging.info("agent %s started for %s", __version__, agent.cfg.device_name)
    try:
        agent.run(stop)
    finally:
        stop.set()
        shutdown()
    return 0 if agent.status.paired else 2


def cmd_status(args: argparse.Namespace) -> int:
    cfg = config.load()
    port = cfg.status_port if cfg else 47615
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=3) as r:
            print(json.dumps(json.loads(r.read()), ensure_ascii=False, indent=2))
        return 0
    except OSError:
        print("Device Agent در حال اجرا نیست", file=sys.stderr)
        return 1


def cmd_render(args: argparse.Namespace) -> int:
    """Offline check: render a payload JSON to PNG (and ESC/POS bytes) without a server."""
    from nextcam_agent import escpos
    from nextcam_agent.render import receipt_image

    with open(args.payload, encoding="utf-8") as f:
        payload = json.load(f)
    img = receipt_image(payload, args.width)
    img.save(args.png)
    if args.bin:
        with open(args.bin, "wb") as f:
            f.write(escpos.receipt_bytes(img, cut_paper=True, drawer_pin=None))
    print(f"{img.width}×{img.height} → {args.png}")
    return 0


def cmd_unpair(args: argparse.Namespace) -> int:
    db = config.data_dir() / "register.db"
    if db.exists():
        store = Store(db)
        try:
            pending = store.pending_count()
        finally:
            store.close()
        if pending and not args.force:
            print(
                f"{pending} فروش آفلاین هنوز به سرور نرسیده است؛ ابتدا اتصال را برقرار کنید "
                "(یا همین دستگاه را با کد تازه دوباره جفت کنید). حذف آن‌ها یعنی از دست رفتن فروش.",
                file=sys.stderr,
            )
            return 1
    config.forget()
    print("تنظیمات و توکن این رایانه پاک شد")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nextcam-agent", description="NEXTCAM Device Agent")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("pair", help="جفت‌سازی با کد نمایش داده‌شده در تنظیمات دستگاه‌ها")
    pp.add_argument("--server", required=True, help="مثلاً http://192.168.1.10:8080")
    pp.add_argument("--code", required=True)
    pp.set_defaults(fn=cmd_pair)
    pr = sub.add_parser("run", help="اجرا در پیش‌زمینه")
    pr.add_argument("-v", "--verbose", action="store_true")
    pr.set_defaults(fn=cmd_run)
    sub.add_parser("status", help="وضعیت سرویس در حال اجرا").set_defaults(fn=cmd_status)
    pn = sub.add_parser("render", help="ساخت تصویر فیش از فایل JSON (بدون سرور)")
    pn.add_argument("payload")
    pn.add_argument("png")
    pn.add_argument("--bin")
    pn.add_argument("--width", type=int, default=80, choices=(58, 80))
    pn.set_defaults(fn=cmd_render)
    pu = sub.add_parser("unpair", help="حذف توکن و تنظیمات از این رایانه")
    pu.add_argument("--force", action="store_true", help="حتی با فروش آفلاین ارسال‌نشده")
    pu.set_defaults(fn=cmd_unpair)
    args = p.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
