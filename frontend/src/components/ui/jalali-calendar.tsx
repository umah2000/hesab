import { jalaaliMonthLength, toGregorian, toJalaali } from "jalaali-js";
import { ChevronLeft, ChevronRight } from "lucide-react";
import * as React from "react";
import { createPortal } from "react-dom";
import { toFaDigits } from "@/lib/format";
import { todayIso } from "@/lib/jalali";
import { cn } from "@/lib/utils";

export const JALALI_MONTHS = [
  "فروردین",
  "اردیبهشت",
  "خرداد",
  "تیر",
  "مرداد",
  "شهریور",
  "مهر",
  "آبان",
  "آذر",
  "دی",
  "بهمن",
  "اسفند",
];
const WEEKDAYS = ["ش", "ی", "د", "س", "چ", "پ", "ج"];

const pad = (n: number) => String(n).padStart(2, "0");
const toIso = (jy: number, jm: number, jd: number) => {
  const g = toGregorian(jy, jm, jd);
  return `${g.gy}-${pad(g.gm)}-${pad(g.gd)}`;
};
const fromIso = (iso: string) => {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return toJalaali(y, m, d);
};

/** A month of the Jalali calendar, week starting Saturday; emits ISO (Gregorian) dates. */
export function JalaliCalendar({ value, onPick, onClear }: { value: string | null; onPick: (iso: string) => void; onClear?: () => void }) {
  const today = todayIso();
  const start = fromIso(value ?? today);
  const [view, setView] = React.useState({ jy: start.jy, jm: start.jm });
  React.useEffect(() => {
    if (value) {
      const j = fromIso(value);
      setView({ jy: j.jy, jm: j.jm });
    }
  }, [value]);
  const step = (d: number) =>
    setView(({ jy, jm }) => {
      const m = jm + d;
      return m < 1 ? { jy: jy - 1, jm: 12 } : m > 12 ? { jy: jy + 1, jm: 1 } : { jy, jm: m };
    });
  const first = toGregorian(view.jy, view.jm, 1);
  // JS: Sunday = 0 … Saturday = 6; the Persian week starts on Saturday.
  const lead = (new Date(first.gy, first.gm - 1, first.gd).getDay() + 1) % 7;
  const days = jalaaliMonthLength(view.jy, view.jm);
  const cells = [...Array.from({ length: lead }, () => null), ...Array.from({ length: days }, (_, i) => i + 1)];
  const years = Array.from({ length: 21 }, (_, i) => fromIso(today).jy - 15 + i);
  return (
    <div className="w-72 select-none p-3" dir="rtl">
      <div className="mb-2 flex items-center gap-1">
        <button type="button" className="rounded-lg p-1.5 hover:bg-black/5 dark:hover:bg-white/10" aria-label="ماه قبل" onClick={() => step(-1)}>
          <ChevronRight className="size-4" />
        </button>
        <select
          aria-label="ماه"
          className="flex-1 rounded-lg bg-transparent px-1 py-1 text-sm font-semibold text-ink"
          value={view.jm}
          onChange={(e) => setView((v) => ({ ...v, jm: Number(e.target.value) }))}
        >
          {JALALI_MONTHS.map((m, i) => (
            <option key={m} value={i + 1}>{m}</option>
          ))}
        </select>
        <select
          aria-label="سال"
          className="w-20 rounded-lg bg-transparent px-1 py-1 text-sm font-semibold text-ink"
          value={view.jy}
          onChange={(e) => setView((v) => ({ ...v, jy: Number(e.target.value) }))}
        >
          {(years.includes(view.jy) ? years : [...years, view.jy].sort()).map((y) => (
            <option key={y} value={y}>{toFaDigits(y)}</option>
          ))}
        </select>
        <button type="button" className="rounded-lg p-1.5 hover:bg-black/5 dark:hover:bg-white/10" aria-label="ماه بعد" onClick={() => step(1)}>
          <ChevronLeft className="size-4" />
        </button>
      </div>
      <div className="grid grid-cols-7 gap-0.5 text-center text-xs">
        {WEEKDAYS.map((w, i) => (
          <span key={w} className={cn("py-1 font-semibold text-ink-faint", i === 6 && "text-danger")}>{w}</span>
        ))}
        {cells.map((d, i) => {
          if (d === null) return <span key={`e${i}`} />;
          const iso = toIso(view.jy, view.jm, d);
          const selected = iso === value;
          const isToday = iso === today;
          return (
            <button
              key={iso}
              type="button"
              aria-label={`${toFaDigits(d)} ${JALALI_MONTHS[view.jm - 1]} ${toFaDigits(view.jy)}`}
              aria-pressed={selected}
              onClick={() => onPick(iso)}
              className={cn(
                "tabular rounded-lg py-1.5 text-sm hover:bg-brand-500/10",
                selected && "bg-brand-600 font-bold text-white hover:bg-brand-600",
                !selected && isToday && "ring-1 ring-brand-500",
                !selected && i % 7 === 6 && "text-danger",
              )}
            >
              {toFaDigits(d)}
            </button>
          );
        })}
      </div>
      <div className="mt-2 flex items-center justify-between border-t border-[var(--line)] pt-2 text-sm">
        <button type="button" className="font-semibold text-brand-600 hover:underline dark:text-brand-300" onClick={() => onPick(today)}>
          امروز
        </button>
        {onClear ? (
          <button type="button" className="text-ink-soft hover:underline" onClick={onClear}>
            پاک کردن
          </button>
        ) : null}
      </div>
    </div>
  );
}

/**
 * Floats ``children`` under ``anchor``. Rendered into the open dialog (if any) or the body,
 * so a table's overflow never clips it and a modal dialog still receives the clicks.
 */
export function Popover({
  anchor,
  open,
  onClose,
  children,
}: {
  anchor: React.RefObject<HTMLElement | null>;
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const box = React.useRef<HTMLDivElement>(null);
  const [pos, setPos] = React.useState<{ top: number; left: number; container: HTMLElement } | null>(null);
  React.useLayoutEffect(() => {
    if (!open || !anchor.current) {
      setPos(null);
      return;
    }
    const place = () => {
      const a = anchor.current;
      if (!a) return;
      const container = (a.closest('[role="dialog"]') as HTMLElement | null) ?? document.body;
      const r = a.getBoundingClientRect();
      const width = 288;
      const height = box.current?.offsetHeight ?? 330;
      let top = r.bottom + 4;
      if (top + height > window.innerHeight && r.top - height - 4 > 0) top = r.top - height - 4;
      let left = r.right - width; // RTL: line up with the field's right edge
      left = Math.max(8, Math.min(left, window.innerWidth - width - 8));
      if (container !== document.body) {
        // Inside a dialog: stay within its width, or it would scroll sideways.
        const c = container.getBoundingClientRect();
        const inside = Math.max(0, Math.min(left - c.left, container.clientWidth - width));
        setPos({ top: top - c.top + container.scrollTop, left: inside + container.scrollLeft, container });
      } else {
        setPos({ top: top + window.scrollY, left: left + window.scrollX, container });
      }
    };
    place();
    const close = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!box.current?.contains(t) && !anchor.current?.contains(t)) onClose();
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && (e.stopPropagation(), onClose());
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", key, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", key, true);
    };
  }, [open, anchor, onClose]);
  if (!open || !pos) return null;
  return createPortal(
    <div
      ref={box}
      role="dialog"
      aria-label="انتخاب تاریخ"
      style={{ position: "absolute", top: pos.top, left: pos.left, zIndex: 80 }}
      className="rounded-2xl bg-[var(--popover)] shadow-xl ring-1 ring-[var(--line)]"
    >
      {children}
    </div>,
    pos.container,
  );
}

const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

/** Quick report periods in the Jalali calendar, Tehran days: [label, from, to]. */
export function periodPresets(today = todayIso()): [string, string, string][] {
  const j = fromIso(today);
  const weekday = (new Date(`${today}T12:00:00Z`).getUTCDay() + 1) % 7; // Saturday = 0
  const prevMonth = j.jm === 1 ? { jy: j.jy - 1, jm: 12 } : { jy: j.jy, jm: j.jm - 1 };
  return [
    ["امروز", today, today],
    ["دیروز", addDays(today, -1), addDays(today, -1)],
    ["این هفته", addDays(today, -weekday), today],
    ["این ماه", toIso(j.jy, j.jm, 1), today],
    ["ماه قبل", toIso(prevMonth.jy, prevMonth.jm, 1), toIso(prevMonth.jy, prevMonth.jm, jalaaliMonthLength(prevMonth.jy, prevMonth.jm))],
    ["امسال", toIso(j.jy, 1, 1), today],
  ];
}
