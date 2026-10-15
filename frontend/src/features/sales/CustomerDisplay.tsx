import { ShoppingCart } from "lucide-react";
import * as React from "react";
import { type DisplayCurrency, formatMoney, toFaDigits } from "@/lib/format";

/**
 * Customer display: a second browser window on the register's second monitor.
 * The POS tab broadcasts what the customer may see (never cost, discount approvals
 * or anything else) over a same-origin BroadcastChannel; no Device Agent involved.
 */

export type DisplayLine = { name: string; qty: string; unit: string; total: string };
export type DisplayMessage =
  | { type: "cart"; lines: DisplayLine[]; total: string; discount: string; currency: DisplayCurrency }
  | { type: "paid"; total: string; change: string | null; currency: DisplayCurrency }
  | { type: "idle" };

const channelName = (register: string) => `nextcam.display.${register}`;

export function useDisplayPublisher(register: string) {
  const ch = React.useRef<BroadcastChannel | null>(null);
  React.useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;
    ch.current = new BroadcastChannel(channelName(register));
    return () => ch.current?.close();
  }, [register]);
  return React.useCallback((m: DisplayMessage) => {
    try {
      ch.current?.postMessage(m);
    } catch {
      /* display is best-effort */
    }
  }, []);
}

export function openCustomerDisplay(register: string, organization: string) {
  const url = `/display?register=${encodeURIComponent(register)}&org=${encodeURIComponent(organization)}`;
  window.open(url, `nextcam-display-${register}`, "popup,width=1024,height=600");
}

export function CustomerDisplayPage() {
  const params = new URLSearchParams(window.location.search);
  const register = params.get("register") ?? "";
  const org = params.get("org") ?? "";
  const [msg, setMsg] = React.useState<DisplayMessage>({ type: "idle" });
  React.useEffect(() => {
    if (!register || typeof BroadcastChannel === "undefined") return;
    const ch = new BroadcastChannel(channelName(register));
    ch.onmessage = (e: MessageEvent<DisplayMessage>) => setMsg(e.data);
    return () => ch.close();
  }, [register]);
  React.useEffect(() => {
    document.title = "نمایشگر مشتری";
  }, []);

  return (
    <div dir="rtl" className="flex min-h-screen flex-col gap-4 overflow-hidden bg-[var(--bg)] p-6">
      <header className="glass flex items-center justify-between rounded-3xl px-6 py-4">
        <div className="text-2xl font-black text-ink">{org || "خوش آمدید"}</div>
        <ShoppingCart className="size-8 text-brand-500" aria-hidden />
      </header>
      {msg.type === "idle" ? (
        <div className="glass flex flex-1 items-center justify-center rounded-3xl text-3xl font-bold text-ink-soft">
          خوش آمدید
        </div>
      ) : msg.type === "paid" ? (
        <div className="glass flex flex-1 flex-col items-center justify-center gap-6 rounded-3xl">
          <div className="text-3xl font-bold text-ink">از خرید شما سپاسگزاریم</div>
          <div className="text-xl text-ink-soft">پرداخت شد: <b className="tabular">{formatMoney(msg.total, msg.currency)}</b></div>
          {msg.change ? (
            <div className="surface rounded-3xl px-10 py-6 text-center">
              <div className="text-lg text-ink-soft">باقی‌مانده شما</div>
              <div className="tabular text-[clamp(2rem,5vw,4rem)] font-black text-success">{formatMoney(msg.change, msg.currency)}</div>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="grid min-w-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,42%)]">
          <div className="surface overflow-hidden rounded-3xl">
            <ul className="divide-y divide-[var(--line)]">
              {msg.lines.slice(-12).map((l, i) => (
                <li key={i} className="flex items-center justify-between gap-4 px-6 py-3 text-xl">
                  <span className="truncate">{l.name}</span>
                  <span className="tabular text-ink-soft whitespace-nowrap">
                    {toFaDigits(l.qty)} {l.unit}
                  </span>
                  <span className="tabular font-bold whitespace-nowrap">{formatMoney(l.total, msg.currency)}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="flex min-w-0 flex-col justify-end gap-3 rounded-3xl bg-gradient-to-l from-brand-600 to-brand-500 p-6 text-white">
            {Number(msg.discount) ? (
              <div className="text-xl opacity-90">
                تخفیف: <span className="tabular">{formatMoney(msg.discount, msg.currency)}</span>
              </div>
            ) : null}
            <div className="text-lg opacity-80">مبلغ قابل پرداخت</div>
            <div className="tabular text-[clamp(2rem,5vw,4rem)] leading-tight font-black break-words">{formatMoney(msg.total, msg.currency)}</div>
          </div>
        </div>
      )}
    </div>
  );
}
