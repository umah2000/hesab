import { useQueryClient } from "@tanstack/react-query";
import JsBarcode from "jsbarcode";
import { Printer, Tag, Trash2 } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/form-controls";
import { useCurrency } from "@/features/accounting/api";
import { api } from "@/lib/api";
import { formatMoney, toEnDigits, toFaDigits } from "@/lib/format";
import type { Item } from "./api";
import { ItemSearch, type Picked } from "./ItemSearch";

type LabelRow = { item_id: string; code: string; name: string; barcode: string; price: string | null; copies: number };

/** Label stock sizes in millimetres. "a4" prints a 3×8 grid of 70×37mm labels. */
const SIZES = {
  "40x25": { w: 40, h: 25, label: "۴۰×۲۵ میلی‌متر (حرارتی)" },
  "50x30": { w: 50, h: 30, label: "۵۰×۳۰ میلی‌متر (حرارتی)" },
  "60x40": { w: 60, h: 40, label: "۶۰×۴۰ میلی‌متر (حرارتی)" },
  a4: { w: 70, h: 37, label: "برگه A4 — ۲۴ برچسب ۷۰×۳۷" },
} as const;
type SizeKey = keyof typeof SIZES;

export function barcodeFormat(code: string): "EAN13" | "EAN8" | "CODE128" {
  if (/^\d{13}$/.test(code)) return "EAN13";
  if (/^\d{8}$/.test(code)) return "EAN8";
  return "CODE128";
}

function BarcodeSvg({ value, height }: { value: string; height: number }) {
  const ref = React.useRef<SVGSVGElement>(null);
  React.useEffect(() => {
    if (!ref.current) return;
    const opts = { height, margin: 0, fontSize: 11, textMargin: 1, width: 1.4, background: "transparent" };
    const format = barcodeFormat(value);
    try {
      // EAN-13 prints its first digit outside the bars, so it needs a left margin.
      JsBarcode(ref.current, value, { ...opts, format, marginLeft: format === "EAN13" ? 9 : 0 });
    } catch {
      // An EAN with a wrong check digit still prints, as plain CODE128.
      JsBarcode(ref.current, value, { ...opts, format: "CODE128" });
    }
  }, [value, height]);
  return <svg ref={ref} className="max-w-full" role="img" aria-label={`بارکد ${value}`} />;
}

function Label({ row, size, showPrice }: { row: LabelRow; size: SizeKey; showPrice: boolean }) {
  const currency = useCurrency();
  const { w, h } = SIZES[size];
  return (
    <div
      className="label-cell flex flex-col items-center justify-between overflow-hidden bg-white p-[1.5mm] text-center text-black"
      style={{ width: `${w}mm`, height: `${h}mm` }}
    >
      <div className="line-clamp-2 w-full text-[9pt] leading-tight font-bold">{row.name}</div>
      <BarcodeSvg value={row.barcode} height={h >= 35 ? 38 : 26} />
      {showPrice && row.price ? <div className="tabular text-[11pt] font-black">{formatMoney(row.price, currency)}</div> : null}
    </div>
  );
}

export function LabelsPage() {
  const qc = useQueryClient();
  const [rows, setRows] = React.useState<LabelRow[]>([]);
  const [size, setSize] = React.useState<SizeKey>("40x25");
  const [showPrice, setShowPrice] = React.useState(true);

  const add = async (p: Picked) => {
    const existing = rows.find((r) => r.item_id === p.item_id);
    if (existing) {
      setRows((rs) => rs.map((r) => (r === existing ? { ...r, copies: r.copies + 1 } : r)));
      return;
    }
    const item = await qc.fetchQuery({
      queryKey: ["inventory", "item", p.item_id],
      queryFn: () => api.get<Item>(`/inventory/items/${p.item_id}`),
    });
    // Prefer the base-unit barcode; fall back to the item code, which lookup also resolves.
    const barcode = item.barcodes.find((b) => !b.unit_id || b.unit_id === item.base_unit_id)?.barcode ?? item.code;
    const price = item.prices.find((x) => x.unit_id === item.base_unit_id)?.price ?? null;
    setRows((rs) => [...rs, { item_id: item.id, code: item.code, name: item.name, barcode, price, copies: 1 }]);
  };

  const labels = rows.flatMap((r) => Array.from({ length: r.copies }, (_, i) => ({ key: `${r.item_id}-${i}`, row: r })));

  const print = () => {
    const { w, h } = SIZES[size];
    const style = document.createElement("style");
    style.textContent =
      size === "a4"
        ? "@page { size: A4; margin: 10mm 0 0 0; }"
        : `@page { size: ${w}mm ${h}mm; margin: 0; } .label-sheet { display: block !important; } .label-cell { page-break-after: always; }`;
    document.head.appendChild(style);
    window.addEventListener("afterprint", () => style.remove(), { once: true });
    window.print();
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,26rem)_1fr]">
      <Card className="no-print flex flex-col gap-4 p-4">
        <ItemSearch onPick={(p) => void add(p)} autoFocus placeholder="اسکن یا جست‌وجوی کالا برای برچسب" />
        {rows.length ? (
          <ul className="flex flex-col gap-2">
            {rows.map((r) => (
              <li key={r.item_id} className="surface flex items-center gap-3 rounded-xl px-3 py-2 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium text-ink">{r.name}</div>
                  <div className="tabular text-xs text-ink-faint" dir="ltr">{r.barcode}</div>
                </div>
                <Input
                  className="w-16 text-center"
                  inputMode="numeric"
                  aria-label={`تعداد برچسب ${r.name}`}
                  value={toFaDigits(r.copies)}
                  onChange={(e) => {
                    const n = Math.min(500, Math.max(1, Number.parseInt(toEnDigits(e.target.value), 10) || 1));
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
        <Field label="اندازه برچسب">
          <Select value={size} onChange={(e) => setSize(e.target.value as SizeKey)}>
            {Object.entries(SIZES).map(([k, s]) => (
              <option key={k} value={k}>{s.label}</option>
            ))}
          </Select>
        </Field>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-soft">
          <Checkbox checked={showPrice} onCheckedChange={(c) => setShowPrice(c === true)} />
          چاپ قیمت (فهرست قیمت پیش‌فرض، واحد اصلی)
        </label>
        <p className="text-xs text-ink-faint">
          بارکد ۱۳ رقمی به‌صورت EAN-13 و بقیه به‌صورت Code128 چاپ می‌شود. کالای بدون بارکد با کد کالا چاپ می‌شود که در صندوق هم شناخته می‌شود.
          مدل چاپگر برچسب هنوز مشخص نیست؛ اندازه و حاشیه را با یک چاپ آزمایشی بررسی کنید.
        </p>
        <Button disabled={!labels.length} onClick={print}>
          <Printer /> چاپ {labels.length ? `${toFaDigits(labels.length)} برچسب` : ""}
        </Button>
      </Card>

      <Card className="p-4">
        {labels.length ? (
          <div className="label-sheet print-area flex flex-wrap content-start gap-2 print:gap-0">
            {labels.map((l) => (
              <div key={l.key} className="rounded-md ring-1 ring-black/10 print:rounded-none print:ring-0">
                <Label row={l.row} size={size} showPrice={showPrice} />
              </div>
            ))}
          </div>
        ) : (
          <EmptyState icon={Tag} title="کالایی انتخاب نشده" description="کالا را اسکن یا جست‌وجو کنید تا پیش‌نمایش برچسب این‌جا ببینید." />
        )}
      </Card>
    </div>
  );
}
