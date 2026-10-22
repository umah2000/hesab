import { logoUrl, useBranding } from "@/components/layout/branding";
import { formatDateTime, formatMoney, toFaDigits } from "@/lib/format";
import type { DisplayCurrency } from "@/lib/format";
import { trimQty } from "@/features/inventory/api";
import { sumRials } from "@/lib/money";
import { type Invoice, METHOD_LABEL } from "./api";

/** Thermal receipt, 80 mm roll. Printed through the browser/Windows driver until phase 6. */
export function Receipt({
  invoice,
  currency,
  organization,
  header,
  footer,
  reprint,
}: {
  invoice: Invoice;
  currency: DisplayCurrency;
  organization: string;
  header?: string | null;
  footer?: string | null;
  reprint?: boolean;
}) {
  const money = (v: string) => formatMoney(v, currency).replace(/ (تومان|ریال)$/, "");
  const unit = currency === "IRT" ? "تومان" : "ریال";
  const isReturn = invoice.kind === "return";
  const logo = useBranding().data?.logo_version;
  return (
    <div className="receipt w-[72mm] bg-white p-[2mm] text-[9pt] leading-snug text-black" dir="rtl">
      <div className="text-center">
        {logo ? <img src={logoUrl(logo)} alt="" className="mx-auto mb-1 max-h-[18mm] max-w-[40mm] object-contain grayscale" /> : null}
        <div className="text-[12pt] font-black">{organization}</div>
        {header ? <div className="whitespace-pre-line">{header}</div> : null}
        <div className="mt-1 font-bold">{isReturn ? "رسید برگشت از فروش" : "فاکتور فروش"}{reprint ? " (چاپ مجدد)" : ""}</div>
      </div>
      <div className="my-1 flex justify-between border-y border-dashed border-black py-1">
        {invoice.number == null && invoice.device_number ? (
          <span>شماره صندوق: <span className="latin-digits">{invoice.device_number}</span></span>
        ) : (
          <span>شماره: {toFaDigits(invoice.number ?? 0)}</span>
        )}
        <span>{formatDateTime(invoice.finalized_at ?? invoice.created_at)}</span>
      </div>
      <div className="flex justify-between">
        <span>{invoice.register_name}</span>
        <span>صندوق‌دار: {invoice.cashier_name}</span>
      </div>
      {isReturn && invoice.original_number ? <div>برگشت فاکتور شماره {toFaDigits(invoice.original_number)}</div> : null}
      {invoice.customer_name ? <div>مشتری: {invoice.customer_name}</div> : null}
      <table className="mt-1 w-full border-t border-dashed border-black">
        <tbody>
          {invoice.lines.map((l) => (
            <tr key={l.id} className="align-top">
              <td className="py-0.5">
                <div>{l.item_name}{l.vat_exempt ? " *" : ""}</div>
                <div className="tabular text-[8pt]">
                  {toFaDigits(trimQty(l.qty))} {l.unit_name} × {money(l.unit_price)}
                  {Number(l.promotion_discount) || Number(l.manual_discount)
                    ? ` − تخفیف ${money(sumRials([l.promotion_discount, l.manual_discount]))}`
                    : ""}
                </div>
              </td>
              <td className="tabular py-0.5 text-start whitespace-nowrap">{money(l.line_total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-1 border-t border-dashed border-black pt-1">
        <Row label="جمع" value={money(invoice.subtotal)} />
        {Number(invoice.discount_total) ? <Row label="تخفیف" value={money(invoice.discount_total)} /> : null}
        <Row label="مالیات بر ارزش افزوده" value={money(invoice.tax_total)} />
        <div className="my-1 flex justify-between text-[12pt] font-black">
          <span>{isReturn ? "مبلغ استرداد" : "قابل پرداخت"}</span>
          <span className="tabular">{money(invoice.grand_total)} {unit}</span>
        </div>
        {invoice.payments.map((p, i) => (
          <Row
            key={i}
            label={`${METHOD_LABEL[p.method]}${p.card_reference ? ` (پیگیری ${toFaDigits(p.card_reference)})` : ""}`}
            value={money(p.amount)}
          />
        ))}
        {invoice.cash_tendered ? <Row label="دریافتی" value={money(invoice.cash_tendered)} /> : null}
        {invoice.change_due && Number(invoice.change_due) ? <Row label="باقی‌مانده (پس داده شد)" value={money(invoice.change_due)} /> : null}
      </div>
      {invoice.lines.some((l) => l.vat_exempt) ? <div className="mt-1 text-[8pt]">* کالای معاف از مالیات</div> : null}
      {invoice.device_number && invoice.number == null ? (
        <div className="mt-1 text-[8pt]">ثبت در حالت آفلاین؛ شماره قطعی پس از اتصال به سرور داده می‌شود.</div>
      ) : null}
      {footer ? <div className="mt-2 border-t border-dashed border-black pt-1 text-center whitespace-pre-line">{footer}</div> : null}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span>{label}</span>
      <span className="tabular">{value}</span>
    </div>
  );
}

/** Prints the element with class .print-area on an 80 mm roll. */
export function printReceipt() {
  const style = document.createElement("style");
  style.textContent = "@page { size: 80mm auto; margin: 0; }";
  document.head.appendChild(style);
  window.addEventListener("afterprint", () => style.remove(), { once: true });
  window.print();
}
