/**
 * Printed sales invoices on sheets, after the owner's two samples (1405/08/09):
 * - SalesSheet: «فاکتور فروش» on A5 or A4 portrait;
 * - OfficialInvoice: «صورتحساب فروش کالا و خدمات» on A4 landscape, with the seller's and
 *   the buyer's particulars and tax per line.
 * Amounts are printed in rials, as invoices are; the amount in words below the total.
 */
import { logoUrl, useBranding } from "@/components/layout/branding";
import { trimQty } from "@/features/inventory/api";
import { formatDate, formatMoney, toFaDigits } from "@/lib/format";
import { addRials, compareRials, divRialsByQty, subRials, sumRials } from "@/lib/money";
import { numberToWords } from "@/lib/words";
import type { Invoice } from "./api";

export type Seller = {
  name: string;
  phone?: string | null;
  address?: string | null;
  economic_code?: string | null;
  national_id?: string | null;
  registration_no?: string | null;
  postal_code?: string | null;
};

const rial = (v: string) => formatMoney(v, "IRR").replace(/ ریال$/, "");
const words = (v: string) => `${numberToWords(v.split(".")[0])} ریال`;
const fa = (v: string | null | undefined) => (v ? toFaDigits(v) : "");

function parts(invoice: Invoice) {
  const isReturn = invoice.kind === "return";
  const when = invoice.finalized_at ?? invoice.created_at;
  const auto = toFaDigits(invoice.number ?? 0);
  const number =
    invoice.number == null && invoice.device_number
      ? invoice.device_number
      : invoice.manual_number
        ? `${invoice.manual_number} (${auto})`
        : auto;
  // Paid now (cash, card) and left on account (credit).
  const credit = sumRials(invoice.payments.filter((p) => p.method === "credit").map((p) => p.amount));
  const paid = subRials(invoice.grand_total, credit);
  return { isReturn, when, number, credit, paid };
}

/** «فاکتور فروش» on A5 / A4: stripes, logo · title · number and date, seller and buyer rows,
 * a numbered table padded with empty rows, total in words, total / paid / remaining, signatures. */
export function SalesSheet({ invoice, seller, paper, reprint }: { invoice: Invoice; seller: Seller; paper: "a5" | "a4"; reprint?: boolean }) {
  const { isReturn, when, number, credit, paid } = parts(invoice);
  const logo = useBranding().data?.logo_version;
  const small = paper === "a5";
  const rows = Math.max(invoice.lines.length, small ? 8 : 15);
  const cell = "border border-black/70 px-1.5 py-[3px]";
  const band = "h-[3mm] bg-[#f6c27a] print:bg-[#f6c27a]";
  const buyer = invoice.buyer;
  return (
    <div className={`invoice-sheet bg-white text-black ${small ? "w-[128mm] text-[7.5pt]" : "w-[186mm] text-[9.5pt]"}`} dir="rtl" style={{ printColorAdjust: "exact", WebkitPrintColorAdjust: "exact" }}>
      <Stripes />
      <div className="border border-black/70">
        <div className="grid grid-cols-[1fr_1.4fr_1fr] items-stretch">
          <div className="flex items-center justify-center border-l border-black/70 p-1">
            {logo ? <img src={logoUrl(logo)} alt="" className={`${small ? "max-h-[12mm]" : "max-h-[18mm]"} max-w-full object-contain`} /> : <span className="text-black/50">{seller.name}</span>}
          </div>
          <div className={`flex items-center justify-center border-l border-black/70 font-black ${small ? "text-[13pt]" : "text-[17pt]"}`}>
            {isReturn ? "برگشت از فروش" : "فاکتور فروش"}
            {reprint ? <span className="ms-1 text-[0.55em] font-normal">(رونوشت)</span> : null}
          </div>
          <div className="grid grid-rows-2">
            <div className="grid grid-cols-2 border-b border-black/70">
              <span className="border-l border-black/70 px-1 py-0.5">شماره فاکتور</span>
              <span className="tabular px-1 py-0.5 text-center">{number}</span>
            </div>
            <div className="grid grid-cols-2">
              <span className="border-l border-black/70 px-1 py-0.5">تاریخ</span>
              <span className="tabular px-1 py-0.5 text-center">{formatDate(when)}</span>
            </div>
          </div>
        </div>
        <div className={band} />
        <PartyRow label="ارائه دهنده" name={seller.name} phone={seller.phone} code={seller.economic_code} address={seller.address} />
        <div className={band} />
        <PartyRow
          label="خریدار"
          name={invoice.customer_name ?? "مشتری نقدی"}
          phone={buyer?.phone}
          code={buyer?.economic_code ?? buyer?.national_id}
          address={[buyer?.city, buyer?.address].filter(Boolean).join("، ")}
        />
        <div className={band} />
        <table className="w-full border-collapse text-center">
          <thead>
            <tr className="font-bold">
              <th rowSpan={2} className={`${cell} w-[5%] border-r-0`}>ردیف</th>
              <th className={`${cell}`}>شرح کالا</th>
              <th className={`${cell} w-[9%]`}>تعداد</th>
              <th className={`${cell} w-[18%]`}>فی (ریال)</th>
              <th className={`${cell} w-[12%]`}>تخفیف</th>
              <th className={`${cell} w-[22%] border-l-0`}>مبلغ کل (ریال)</th>
            </tr>
            <tr className="text-[0.85em] font-normal">
              <th className={cell}>description</th>
              <th className={cell}>QTY</th>
              <th className={cell}>unit price</th>
              <th className={cell}>Discount</th>
              <th className={`${cell} border-l-0`}>final price</th>
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: rows }, (_, i) => {
              const l = invoice.lines[i];
              const disc = l ? sumRials([l.promotion_discount, l.manual_discount]) : "0";
              return (
                <tr key={i} className={i % 2 ? "bg-black/[0.03]" : ""}>
                  <td className={`${cell} border-r-0`}>{toFaDigits(i + 1)}</td>
                  <td className={`${cell} text-start`}>{l ? l.item_name : ""}</td>
                  <td className={`${cell} tabular`}>{l ? toFaDigits(trimQty(l.qty)) : ""}</td>
                  <td className={`${cell} tabular`}>{l ? rial(l.unit_price) : ""}</td>
                  <td className={`${cell} tabular`}>{l ? (compareRials(disc, "0") ? rial(disc) : "—") : ""}</td>
                  <td className={`${cell} tabular border-l-0`}>{l ? rial(l.line_total) : ""}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="grid grid-cols-[1.6fr_1fr]">
          <div className="flex flex-col border-l border-black/70">
            <div className="border-b border-black/70 px-1.5 py-1">
              کل مبلغ به حروف: <b>{words(invoice.grand_total)}</b>
            </div>
            <div className="min-h-[10mm] px-1.5 py-1">
              توضیحات:{" "}
              {[
                compareRials(invoice.discount_total, "0") ? `تخفیف ${rial(invoice.discount_total)} ریال` : "",
                compareRials(invoice.tax_total, "0") ? `مالیات بر ارزش افزوده ${rial(invoice.tax_total)} ریال` : "",
                invoice.note ?? "",
              ]
                .filter(Boolean)
                .join(" · ")}
            </div>
          </div>
          <table className="w-full border-collapse">
            <tbody>
              {[
                ["قیمت کل", invoice.grand_total],
                [isReturn ? "استرداد" : "بیعانه / پرداختی", paid],
                ["مانده", credit],
              ].map(([label, v]) => (
                <tr key={label}>
                  <td className={`${cell} border-r-0 font-bold`}>{label}</td>
                  <td className={`${cell} tabular border-l-0 text-center`}>{rial(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className={`grid grid-cols-2 border-t border-black/70 ${small ? "h-[16mm]" : "h-[24mm]"}`}>
          <div className="border-l border-black/70 p-1.5 font-bold">مهر و امضا فروشنده</div>
          <div className="p-1.5 font-bold">مهر و امضا خریدار</div>
        </div>
      </div>
      <Stripes />
    </div>
  );
}

function Stripes() {
  return (
    <div aria-hidden className="my-1 flex h-[4mm] gap-[1.5mm] overflow-hidden">
      {Array.from({ length: 24 }, (_, i) => (
        <span key={i} className="h-full w-[6mm] shrink-0 -skew-x-[30deg] bg-[#8b7cf6]" />
      ))}
    </div>
  );
}

function PartyRow({ label, name, phone, code, address }: { label: string; name: string; phone?: string | null; code?: string | null; address?: string | null }) {
  return (
    <div className="text-[0.95em]">
      <div className="grid grid-cols-[1.3fr_1fr_1fr] border-b border-black/30">
        <span className="px-1.5 py-0.5">
          {label}: <b>{name}</b>
        </span>
        <span className="px-1.5 py-0.5">
          شماره تماس: <span className="tabular">{fa(phone)}</span>
        </span>
        <span className="px-1.5 py-0.5">
          کد اقتصادی: <span className="tabular">{fa(code)}</span>
        </span>
      </div>
      <div className="px-1.5 py-0.5">آدرس: {address || ""}</div>
    </div>
  );
}

/** Digits in boxes, as on the official form (economic code, postal code …). */
function Boxes({ value, count }: { value?: string | null; count: number }) {
  const digits = (value ?? "").padStart(count, " ").slice(-count).split("");
  return (
    <span dir="ltr" className="inline-flex">
      {digits.map((d, i) => (
        <span key={i} className="tabular -ml-px inline-flex h-[5mm] w-[4.2mm] items-center justify-center border border-black/70 text-[0.95em]">
          {d.trim() ? toFaDigits(d) : ""}
        </span>
      ))}
    </span>
  );
}

/** «صورتحساب فروش کالا و خدمات» on A4 landscape. */
export function OfficialInvoice({ invoice, seller, reprint }: { invoice: Invoice; seller: Seller; reprint?: boolean }) {
  const { isReturn, when, number, credit } = parts(invoice);
  const buyer = invoice.buyer;
  const cell = "border border-black/70 px-1 py-[3px]";
  const head = "bg-black/[0.07] py-0.5 text-center font-bold";
  const lines = invoice.lines.map((l) => {
    const discount = sumRials([l.promotion_discount, l.manual_discount]);
    const after = subRials(l.line_total, l.tax); // before tax, after discount
    const gross = addRials(after, discount);
    return { l, discount, after, gross, unit: divRialsByQty(gross, l.qty) };
  });
  const total = (k: "gross" | "discount" | "after") => sumRials(lines.map((x) => x[k]));
  const rows = Math.max(lines.length, 5);
  const field = "flex items-center gap-1.5 py-0.5";
  return (
    <div className="invoice-sheet w-[273mm] bg-white text-[8.5pt] text-black" dir="rtl" style={{ printColorAdjust: "exact", WebkitPrintColorAdjust: "exact" }}>
      <div className="mb-1 grid grid-cols-[1fr_auto_1fr] items-end">
        <span />
        <h1 className="text-center text-[14pt] font-black">
          {isReturn ? "صورتحساب برگشت از فروش کالا و خدمات" : "صورتحساب فروش کالا و خدمات"}
          {reprint ? <span className="ms-1 text-[0.55em] font-normal">(رونوشت)</span> : null}
        </h1>
        <div className="flex flex-col items-end gap-0.5">
          <span>شماره سریال: <b className="tabular">{number}</b></span>
          <span>تاریخ: <b className="tabular">{formatDate(when)}</b></span>
        </div>
      </div>
      <div className="border border-black/70">
        <div className={head}>مشخصات فروشنده</div>
        <div className="grid grid-cols-3 gap-x-4 px-2 py-1">
          <span className={field}>نام شخص حقیقی / حقوقی: <b>{seller.name}</b></span>
          <span className={field}>شماره اقتصادی: <Boxes value={seller.economic_code} count={12} /></span>
          <span className={field}>شماره ثبت / شناسه ملی: <Boxes value={seller.national_id ?? seller.registration_no} count={11} /></span>
          <span className={`${field} col-span-2`}>نشانی کامل: {seller.address ?? ""}</span>
          <span className={field}>کد پستی ۱۰ رقمی: <Boxes value={seller.postal_code} count={10} /></span>
          <span className={field}>تلفن / نمابر: <span className="tabular">{fa(seller.phone)}</span></span>
        </div>
        <div className={`${head} border-t border-black/70`}>مشخصات خریدار</div>
        <div className="grid grid-cols-3 gap-x-4 px-2 py-1">
          <span className={field}>نام شخص حقیقی / حقوقی: <b>{invoice.customer_name ?? "مصرف‌کننده‌ی نهایی"}</b></span>
          <span className={field}>شماره اقتصادی: <Boxes value={buyer?.economic_code} count={12} /></span>
          <span className={field}>شماره ثبت / شناسه ملی: <Boxes value={buyer?.national_id ?? buyer?.registration_no} count={11} /></span>
          <span className={`${field} col-span-2`}>نشانی کامل: {[buyer?.city, buyer?.address].filter(Boolean).join("، ")}</span>
          <span className={field}>کد پستی ۱۰ رقمی: <Boxes value={buyer?.postal_code} count={10} /></span>
          <span className={field}>تلفن / نمابر: <span className="tabular">{fa(buyer?.phone)}</span></span>
        </div>
        <div className={`${head} border-t border-black/70`}>مشخصات کالا یا خدمات مورد معامله</div>
        <table className="w-full border-collapse text-center">
          <thead>
            <tr className="align-middle text-[0.92em]">
              {[
                "ردیف",
                "کد کالا",
                "شرح کالا یا خدمات",
                "تعداد / مقدار",
                "واحد اندازه‌گیری",
                "مبلغ واحد (ریال)",
                "مبلغ کل (ریال)",
                "مبلغ تخفیف (ریال)",
                "مبلغ کل پس از تخفیف (ریال)",
                "جمع مالیات و عوارض (ریال)",
                "جمع مبلغ کل بعلاوه‌ی مالیات و عوارض (ریال)",
              ].map((h, i) => (
                <th key={h} className={`${cell} ${i === 2 ? "w-[20%]" : ""} font-bold`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: rows }, (_, i) => {
              const x = lines[i];
              return (
                <tr key={i}>
                  <td className={cell}>{toFaDigits(i + 1)}</td>
                  <td className={`${cell} tabular`}>{x ? fa(x.l.item_code) : ""}</td>
                  <td className={`${cell} text-start`}>{x ? `${x.l.item_name}${x.l.vat_exempt ? " (معاف)" : ""}` : ""}</td>
                  <td className={`${cell} tabular`}>{x ? toFaDigits(trimQty(x.l.qty)) : ""}</td>
                  <td className={cell}>{x ? x.l.unit_name : ""}</td>
                  <td className={`${cell} tabular`}>{x ? rial(x.unit) : ""}</td>
                  <td className={`${cell} tabular`}>{x ? rial(x.gross) : ""}</td>
                  <td className={`${cell} tabular`}>{x ? rial(x.discount) : ""}</td>
                  <td className={`${cell} tabular`}>{x ? rial(x.after) : ""}</td>
                  <td className={`${cell} tabular`}>{x ? rial(x.l.tax) : ""}</td>
                  <td className={`${cell} tabular`}>{x ? rial(x.l.line_total) : ""}</td>
                </tr>
              );
            })}
            <tr className="font-bold">
              <td colSpan={6} className={`${cell} text-start`}>جمع کل</td>
              <td className={`${cell} tabular`}>{rial(total("gross"))}</td>
              <td className={`${cell} tabular`}>{rial(total("discount"))}</td>
              <td className={`${cell} tabular`}>{rial(total("after"))}</td>
              <td className={`${cell} tabular`}>{rial(invoice.tax_total)}</td>
              <td className={`${cell} tabular`}>{rial(invoice.grand_total)}</td>
            </tr>
          </tbody>
        </table>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 border-t border-black/70 px-2 py-1">
          <span>جمع نهایی به حروف: <b>{words(invoice.grand_total)}</b></span>
          <span className="flex items-center gap-2">
            شرایط و نحوه‌ی فروش:
            <Tick on={!compareRials(credit, "0")} /> نقدی
            <Tick on={!!compareRials(credit, "0")} /> غیرنقدی
          </span>
        </div>
        <div className="min-h-[8mm] border-t border-black/70 px-2 py-1">توضیحات: {invoice.note ?? ""}</div>
        <div className="grid h-[20mm] grid-cols-2 border-t border-black/70">
          <div className="border-l border-black/70 p-1.5 font-bold">مهر و امضای فروشنده</div>
          <div className="p-1.5 font-bold">مهر و امضای خریدار</div>
        </div>
      </div>
    </div>
  );
}

function Tick({ on }: { on: boolean }) {
  return <span className="inline-flex size-[3.5mm] items-center justify-center border border-black/80 text-[0.9em] leading-none">{on ? "✓" : ""}</span>;
}
