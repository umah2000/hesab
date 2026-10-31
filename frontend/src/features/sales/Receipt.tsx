import { logoUrl, useBranding } from "@/components/layout/branding";
import { formatDate, formatMoney, formatTime, toFaDigits } from "@/lib/format";
import type { DisplayCurrency } from "@/lib/format";
import { trimQty } from "@/features/inventory/api";
import { compareRials } from "@/lib/money";
import { type Invoice, type InvoicePaper, METHOD_LABEL } from "./api";
import { OfficialInvoice, SalesSheet, type Seller } from "./InvoiceSheets";

type ReceiptProps = {
  invoice: Invoice;
  currency: DisplayCurrency;
  organization: string;
  header?: string | null;
  footer?: string | null;
  phone?: string | null;
  address?: string | null;
  reprint?: boolean;
  /** Thermal roll (default), an A5 / A4 sheet, or the official A4 landscape invoice. */
  paper?: InvoicePaper;
  /** Seller particulars for the official invoice. */
  seller?: Omit<Seller, "name" | "phone" | "address">;
};

/** An invoice as printed from the browser: the 80 mm roll, or an A5 / A4 sheet. */
export function Receipt({ paper = "thermal", seller, ...props }: ReceiptProps) {
  if (paper === "thermal") return <ThermalReceipt {...props} />;
  const who: Seller = { name: props.organization, phone: props.phone, address: props.address, ...seller };
  return paper === "official" ? (
    <OfficialInvoice invoice={props.invoice} seller={who} reprint={props.reprint} />
  ) : (
    <SalesSheet invoice={props.invoice} seller={who} paper={paper} reprint={props.reprint} />
  );
}

function useParts({ invoice, currency }: Pick<ReceiptProps, "invoice" | "currency">) {
  const money = (v: string) => formatMoney(v, currency).replace(/ (تومان|ریال)$/, "");
  const unit = currency === "IRT" ? "تومان" : "ریال";
  const isReturn = invoice.kind === "return";
  const when = invoice.finalized_at ?? invoice.created_at;
  const number =
    invoice.number == null && invoice.device_number ? (
      <span className="latin-digits">{invoice.device_number}</span>
    ) : invoice.manual_number ? (
      // The company's own number first; the automatic one stays beside it (ADR-0029).
      <>
        <span dir="ltr">{invoice.manual_number}</span> ({toFaDigits(invoice.number ?? 0)})
      </>
    ) : (
      toFaDigits(invoice.number ?? 0)
    );
  const totals: { label: string; value: string; bold?: boolean }[] = [{ label: "جمع کل", value: money(invoice.subtotal) }];
  if (compareRials(invoice.discount_total, "0")) totals.push({ label: "تخفیف", value: money(invoice.discount_total) });
  if (compareRials(invoice.tax_total, "0")) totals.push({ label: "مالیات بر ارزش افزوده", value: money(invoice.tax_total) });
  totals.push({ label: isReturn ? "مبلغ استرداد" : "قابل پرداخت", value: `${money(invoice.grand_total)} ${unit}`, bold: true });
  const payments = invoice.payments.map((p) => ({
    label: `${METHOD_LABEL[p.method]}${p.card_reference ? ` (پیگیری ${toFaDigits(p.card_reference)})` : ""}`,
    value: money(p.amount),
  }));
  if (invoice.cash_tendered) payments.push({ label: "دریافتی", value: money(invoice.cash_tendered) });
  if (invoice.change_due && compareRials(invoice.change_due, "0")) payments.push({ label: "باقی‌مانده (پس داده شد)", value: money(invoice.change_due) });
  const heading = `${isReturn ? "رسید برگشت از فروش" : "فاکتور فروش"}`;
  const notes: string[] = [];
  if (invoice.lines.some((l) => l.vat_exempt)) notes.push("* کالای معاف از مالیات");
  if (invoice.device_number && invoice.number == null) notes.push("ثبت در حالت آفلاین؛ شماره قطعی پس از اتصال به سرور داده می‌شود.");
  return { money, isReturn, when, number, totals, payments, heading, notes };
}

/**
 * The 80 mm roll, laid out like the shop's own receipts (sample 1405/08/02): framed
 * name, framed details, a bordered item table with list and shop price, shaded totals.
 */
function ThermalReceipt({ invoice, currency, organization, header, footer, phone, address, reprint }: ReceiptProps) {
  const { money, isReturn, when, number, totals, payments, heading, notes } = useParts({ invoice, currency });
  const logo = useBranding().data?.logo_version;
  const cell = "border border-black px-[1mm] py-[0.8mm]";
  return (
    <div className="receipt w-[72mm] bg-white p-[2mm] text-[8.5pt] leading-snug text-black" dir="rtl">
      {logo ? <img src={logoUrl(logo)} alt="" className="mx-auto mb-1 max-h-[16mm] max-w-[40mm] object-contain grayscale" /> : null}
      <div className="border-2 border-black px-1 py-1 text-center">
        <div className="text-[13pt] font-black">{organization}</div>
        {header ? <div className="whitespace-pre-line text-[8pt]">{header}</div> : null}
      </div>
      <div className="mt-1 text-center font-bold">
        {heading}
        {reprint ? " (چاپ مجدد)" : ""}
      </div>
      <div className="mt-1 grid grid-cols-2 gap-x-2 rounded-[2mm] border-2 border-black px-[1.5mm] py-1">
        <span>شماره: {number}</span>
        <span>تاریخ: {formatDate(when)}</span>
        <span>کاربر: {invoice.cashier_name}</span>
        <span>زمان: {formatTime(when)}</span>
        {isReturn && invoice.original_number ? <span className="col-span-2">برگشت فاکتور {toFaDigits(invoice.original_number)}</span> : null}
        {invoice.customer_name ? <span className="col-span-2">مشتری: {invoice.customer_name}</span> : null}
      </div>
      <table className="mt-1 w-full border-collapse text-[7.5pt]">
        <thead>
          <tr className="receipt-shade font-bold">
            <th className={`${cell} w-[30%] text-start`}>شرح کالا</th>
            <th className={`${cell} w-[10%]`}>مقدار</th>
            <th className={`${cell} w-[20%]`}>قیمت کالا</th>
            <th className={`${cell} w-[20%]`}>قیمت فروشگاه</th>
            <th className={`${cell} w-[20%]`}>مبلغ کل</th>
          </tr>
        </thead>
        <tbody>
          {invoice.lines.map((l) => (
            <tr key={l.id} className="align-top">
              <td className={cell}>{l.item_name}{l.vat_exempt ? " *" : ""}</td>
              <td className={`${cell} tabular text-center`}>{toFaDigits(trimQty(l.qty))}</td>
              <td className={`${cell} tabular text-center`}>{money(l.unit_price)}</td>
              <td className={`${cell} tabular text-center`}>{money(l.net_unit_price ?? l.unit_price)}</td>
              <td className={`${cell} tabular text-center`}>{money(l.net_amount ?? l.line_total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <table className="mt-1 w-full border-collapse">
        <tbody>
          {totals.map((t) => (
            <tr key={t.label} className={`receipt-shade ${t.bold ? "text-[11pt] font-black" : "font-bold"}`}>
              <td className={`${cell} w-1/2`}>{t.label}</td>
              <td className={`${cell} tabular text-center`}>{t.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-1">
        {payments.map((p) => (
          <div key={p.label} className="flex justify-between">
            <span>{p.label}</span>
            <span className="tabular">{p.value}</span>
          </div>
        ))}
      </div>
      {notes.map((n) => (
        <div key={n} className="mt-1 text-[7.5pt]">{n}</div>
      ))}
      {phone || address ? (
        <div className="mt-1 text-center">
          {phone ? <div className="tabular text-[10pt]">{toFaDigits(phone)}</div> : null}
          {address ? <div>{address}</div> : null}
        </div>
      ) : null}
      {footer ? <div className="mt-1 border-t border-dashed border-black pt-1 text-center whitespace-pre-line">{footer}</div> : null}
    </div>
  );
}

const PAGE: Record<InvoicePaper, string> = {
  thermal: "@page { size: 80mm auto; margin: 0; }",
  a5: "@page { size: A5 portrait; margin: 10mm; }",
  a4: "@page { size: A4 portrait; margin: 12mm; }",
  official: "@page { size: A4 landscape; margin: 10mm; }",
};

/** Prints the element with class .print-area on the given paper (default: 80 mm roll). */
export function printReceipt(paper: InvoicePaper = "thermal") {
  const style = document.createElement("style");
  style.textContent = PAGE[paper];
  document.head.appendChild(style);
  window.addEventListener("afterprint", () => style.remove(), { once: true });
  window.print();
}
