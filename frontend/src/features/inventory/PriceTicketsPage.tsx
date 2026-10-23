import { useMutation } from "@tanstack/react-query";
import { BadgePercent, Printer, Tags, Trash2, TriangleAlert } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { useBranding } from "@/components/layout/branding";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form-controls";
import { useCurrency } from "@/features/accounting/api";
import { ApiError, api } from "@/lib/api";
import { formatMoney, toEnDigits, toFaDigits } from "@/lib/format";
import { useGroups } from "./api";
import { ItemSearch } from "./ItemSearch";

/** A shelf ticket as the server priced it (same pricing as the register). */
type Ticket = {
  item_id: string;
  code: string;
  name: string;
  unit_name: string;
  is_weighted: boolean;
  price: string;
  promotion_name: string | null;
  discount_percent: string | null;
  final_price: string;
};
type Row = Ticket & { copies: number };
type Body = { item_ids?: string[]; group_id?: string; promoted_only?: boolean };

/** Ticket sizes in millimetres; the shop's tickets are about 40×30 (sample 1405/08/02). */
const SIZES = {
  "40x30": { w: 40, h: 30, label: "۴۰×۳۰ میلی‌متر (چاپگر برچسب)" },
  "50x30": { w: 50, h: 30, label: "۵۰×۳۰ میلی‌متر (چاپگر برچسب)" },
  "60x40": { w: 60, h: 40, label: "۶۰×۴۰ میلی‌متر (چاپگر برچسب)" },
  a4: { w: 50, h: 35, label: "برگه A4، ۴ ستون ۵۰×۳۵" },
} as const;
type SizeKey = keyof typeof SIZES;

/** The shop's ticket: name of the shop, item, price, discount, and what is paid, framed. */
function PriceTicket({ t, shop, size }: { t: Ticket; shop: string; size: SizeKey }) {
  const currency = useCurrency();
  const { w, h } = SIZES[size];
  const unit = currency === "IRT" ? "تومان" : "ریال";
  const money = (v: string) => formatMoney(v, currency).replace(/ (تومان|ریال)$/, "");
  const scale = Math.min(w / 40, h / 30);
  return (
    <div className="price-ticket bg-white p-[0.8mm] text-black" style={{ width: `${w}mm`, height: `${h}mm`, fontSize: `${6.5 * scale}pt` }}>
      <div className="flex h-full flex-col overflow-hidden rounded-[2.5mm] border-[0.35mm] border-black" dir="rtl">
        <div className="truncate border-b-[0.2mm] border-dashed border-black px-[1mm] py-[0.3mm] text-center font-bold">{shop}</div>
        <div className="line-clamp-2 px-[1mm] pt-[0.4mm] text-center leading-tight font-bold" style={{ fontSize: "1.15em" }}>
          {t.name}
        </div>
        <div className="flex-1" />
        {t.discount_percent ? (
          <div className="px-[1.2mm] leading-tight">
            <div className="flex justify-between">
              <span>قیمت{t.is_weighted ? ` هر ${t.unit_name}` : ""}:</span>
              <span className="tabular line-through decoration-[0.2mm]">{money(t.price)}</span>
            </div>
            <div className="flex justify-between">
              <span>تخفیف:</span>
              <span className="tabular" dir="ltr">٪ {toFaDigits(t.discount_percent.replace(".", "٫"))}</span>
            </div>
          </div>
        ) : t.is_weighted ? (
          <div className="px-[1.2mm] text-center leading-tight">هر {t.unit_name}</div>
        ) : null}
        <div className="mt-[0.3mm] flex items-baseline justify-center gap-[1mm] border-t-[0.2mm] border-dashed border-black py-[0.4mm] font-black">
          <span className="tabular" style={{ fontSize: "1.8em" }}>{money(t.final_price)}</span>
          <span>{unit}</span>
        </div>
      </div>
    </div>
  );
}

export function PriceTicketsPage() {
  const shop = useBranding().data?.organization_name ?? "";
  const groups = useGroups();
  const [rows, setRows] = React.useState<Row[]>([]);
  const [skipped, setSkipped] = React.useState<string[]>([]);
  const [size, setSize] = React.useState<SizeKey>("40x30");
  const [group, setGroup] = React.useState("");

  const load = useMutation({
    mutationFn: (body: Body) => api.post<{ tickets: Ticket[]; skipped: string[] }>("/sales/price-tickets", body),
    onSuccess: (r) => {
      setSkipped(r.skipped);
      setRows((old) => {
        const have = new Map(old.map((x) => [x.item_id, x]));
        for (const t of r.tickets) {
          const prev = have.get(t.item_id);
          // Re-adding an item refreshes its price and adds one more copy.
          have.set(t.item_id, { ...t, copies: prev ? prev.copies + 1 : 1 });
        }
        return [...have.values()];
      });
      if (!r.tickets.length) toast.info("کالایی برای برچسب پیدا نشد");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا"),
  });

  const tickets = rows.flatMap((r) => Array.from({ length: r.copies }, (_, i) => ({ key: `${r.item_id}-${i}`, t: r })));

  const print = () => {
    const { w, h } = SIZES[size];
    const style = document.createElement("style");
    style.textContent =
      size === "a4"
        ? "@page { size: A4; margin: 8mm; }"
        : `@page { size: ${w}mm ${h}mm; margin: 0; } .ticket-sheet { display: block !important; } .price-ticket { page-break-after: always; }`;
    document.head.appendChild(style);
    window.addEventListener("afterprint", () => style.remove(), { once: true });
    window.print();
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,26rem)_1fr]">
      <Card className="no-print flex flex-col gap-4 p-4">
        <ItemSearch onPick={(p) => load.mutate({ item_ids: [p.item_id] })} autoFocus placeholder="اسکن یا جست‌وجوی کالا برای برچسب قیمت" />
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" loading={load.isPending} onClick={() => load.mutate({ promoted_only: true })}>
            <BadgePercent /> همه‌ی کالاهای تخفیف‌دار امروز
          </Button>
        </div>
        <div className="flex items-end gap-2">
          <Field htmlFor="pt-group" label="همه‌ی کالاهای یک گروه" className="flex-1">
            <Select id="pt-group" value={group} onChange={(e) => setGroup(e.target.value)}>
              <option value="">انتخاب گروه</option>
              {groups.data?.map((g) => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
            </Select>
          </Field>
          <Button variant="outline" disabled={!group} onClick={() => load.mutate({ group_id: group })}>
            افزودن
          </Button>
        </div>
        {skipped.length ? (
          <ul className="rounded-xl bg-warning/10 p-3 text-xs text-ink">
            {skipped.map((s) => (
              <li key={s} className="flex items-start gap-1.5">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warning" /> {s}
              </li>
            ))}
          </ul>
        ) : null}
        {rows.length ? (
          <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto">
            {rows.map((r) => (
              <li key={r.item_id} className="surface flex items-center gap-3 rounded-xl px-3 py-2 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium text-ink">{r.name}</div>
                  <div className="text-xs text-ink-faint">
                    {r.promotion_name ? `${r.promotion_name} · ` : ""}
                    <span className="tabular" dir="ltr">{r.code}</span>
                  </div>
                </div>
                <Input
                  className="w-16 text-center"
                  inputMode="numeric"
                  aria-label={`تعداد برچسب ${r.name}`}
                  value={toFaDigits(r.copies)}
                  onChange={(e) => {
                    const n = Math.min(200, Math.max(1, Number.parseInt(toEnDigits(e.target.value), 10) || 1));
                    setRows((rs) => rs.map((x) => (x === r ? { ...x, copies: n } : x)));
                  }}
                />
                <Button variant="ghost" size="icon" aria-label={`حذف ${r.name}`} onClick={() => setRows((rs) => rs.filter((x) => x !== r))}>
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
        <Field htmlFor="pt-size" label="اندازه برچسب">
          <Select id="pt-size" value={size} onChange={(e) => setSize(e.target.value as SizeKey)}>
            {Object.entries(SIZES).map(([k, s]) => (
              <option key={k} value={k}>{s.label}</option>
            ))}
          </Select>
        </Field>
        <p className="text-xs text-ink-faint">
          قیمت و تخفیف را سرور با همان محاسبه‌ی صندوق می‌دهد: قیمت یک واحد اصلی از فهرست قیمت پیش‌فرض و پروموشن امروز. پس از تغییر قیمت یا
          پایان پروموشن، برچسب را دوباره چاپ کنید.
        </p>
        <div className="flex gap-2">
          <Button className="flex-1" disabled={!tickets.length} onClick={print}>
            <Printer /> چاپ {tickets.length ? `${toFaDigits(tickets.length)} برچسب` : ""}
          </Button>
          {rows.length ? (
            <Button variant="ghost" onClick={() => setRows([])}>
              پاک کردن
            </Button>
          ) : null}
        </div>
      </Card>

      <Card className="p-4">
        {tickets.length ? (
          <div className="ticket-sheet print-area flex flex-wrap content-start gap-2 print:gap-0">
            {tickets.map((x) => (
              <PriceTicket key={x.key} t={x.t} shop={shop} size={size} />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={Tags}
            title="کالایی انتخاب نشده"
            description="کالا را اسکن یا جست‌وجو کنید، یا همه‌ی کالاهای تخفیف‌دار یا یک گروه را اضافه کنید."
          />
        )}
      </Card>
    </div>
  );
}
