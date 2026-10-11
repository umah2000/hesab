import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Boxes, X } from "lucide-react";
import * as React from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Checkbox, Input, Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { useCurrency } from "@/features/accounting/api";
import { api, type Page } from "@/lib/api";
import { formatMoney, toFaDigits } from "@/lib/format";
import { isoToJalaliFa } from "@/lib/jalali";
import { DOC_LABEL, type DocType, trimQty, useWarehouses } from "./api";

type BalanceRow = {
  item_id: string;
  item_code: string;
  item_name: string;
  unit_name: string;
  warehouse_id: string;
  qty: string;
  avg_cost: string;
  value: string;
  min_qty: string | null;
  below_min: boolean;
};
type KardexRow = {
  document_id: string;
  doc_type: DocType;
  number: number | null;
  document_date: string;
  qty_in: string;
  qty_out: string;
  value_in: string;
  value_out: string;
  balance_qty: string;
  balance_value: string;
  avg_cost: string;
};

const avgMoney = (v: string) => v.split(".")[0] + "." + (v.split(".")[1] ?? "").slice(0, 4);

function Kardex({ row, onClose }: { row: BalanceRow; onClose: () => void }) {
  const currency = useCurrency();
  const [page, setPage] = React.useState(1);
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    ref.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
  }, [row]);
  const q = useQuery({
    queryKey: ["inventory", "kardex", row.item_id, row.warehouse_id, page],
    queryFn: () => api.get<Page<KardexRow>>(`/inventory/kardex?item_id=${row.item_id}&warehouse_id=${row.warehouse_id}&page=${page}`),
    placeholderData: keepPreviousData,
  });
  return (
    <Card className="p-2">
      <div ref={ref} className="flex items-center justify-between px-3 py-2">
        <h2 className="font-bold text-ink">
          کاردکس: <span className="tabular text-ink-faint" dir="ltr">{row.item_code}</span> {row.item_name}
        </h2>
        <Button variant="ghost" size="icon" aria-label="بستن کاردکس" onClick={onClose}>
          <X />
        </Button>
      </div>
      <div className="surface overflow-x-auto rounded-2xl">
        {q.isLoading ? (
          <Spinner />
        ) : (
          <>
            <table className="w-full min-w-[56rem] text-sm">
              <thead>
                <tr className="text-xs text-ink-faint">
                  <th className="px-3 py-3 text-start">تاریخ</th>
                  <th className="px-3 py-3 text-start">سند</th>
                  <th className="px-3 py-3 text-start">وارده</th>
                  <th className="px-3 py-3 text-start">صادره</th>
                  <th className="px-3 py-3 text-start">مانده</th>
                  <th className="px-3 py-3 text-start">میانگین بها</th>
                  <th className="px-3 py-3 text-start">ارزش مانده</th>
                </tr>
              </thead>
              <tbody>
                {q.data?.items.map((k, i) => (
                  <tr key={i} className="border-t border-[var(--line)]">
                    <td className="tabular px-3 py-2 text-ink-soft">{isoToJalaliFa(k.document_date)}</td>
                    <td className="px-3 py-2">
                      <Link className="text-brand-600 hover:underline dark:text-brand-300" to={`/inventory/documents/${k.document_id}`}>
                        {DOC_LABEL[k.doc_type]} {toFaDigits(k.number ?? 0)}
                      </Link>
                    </td>
                    <td className="tabular px-3 py-2 text-success">{Number(k.qty_in) ? toFaDigits(trimQty(k.qty_in)) : ""}</td>
                    <td className="tabular px-3 py-2 text-danger">{Number(k.qty_out) ? toFaDigits(trimQty(k.qty_out)) : ""}</td>
                    <td className="tabular px-3 py-2 font-semibold">{toFaDigits(trimQty(k.balance_qty))}</td>
                    <td className="tabular px-3 py-2">{formatMoney(avgMoney(k.avg_cost), currency)}</td>
                    <td className="tabular px-3 py-2">{formatMoney(k.balance_value, currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination page={page} pageSize={100} total={q.data?.total ?? 0} onPage={setPage} />
          </>
        )}
      </div>
    </Card>
  );
}

export function BalancesPage() {
  const currency = useCurrency();
  const warehouses = useWarehouses();
  const [wh, setWh] = React.useState("");
  const [q, setQ] = React.useState("");
  const [belowMin, setBelowMin] = React.useState(false);
  const [page, setPage] = React.useState(1);
  const [selected, setSelected] = React.useState<BalanceRow | null>(null);
  const params = new URLSearchParams({ page: String(page), page_size: "50" });
  if (wh) params.set("warehouse_id", wh);
  if (q.trim()) params.set("q", q.trim());
  if (belowMin) params.set("below_min", "true");
  const data = useQuery({
    queryKey: ["inventory", "balances", params.toString()],
    queryFn: () => api.get<Page<BalanceRow> & { total_value: string }>(`/inventory/balances?${params}`),
    placeholderData: keepPreviousData,
  });
  const whName = (id: string) => warehouses.data?.find((w) => w.id === id)?.name ?? "";

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <div className="flex flex-wrap items-center gap-3 p-4">
          <Select className="w-48" value={wh} onChange={(e) => { setWh(e.target.value); setPage(1); }} aria-label="انبار">
            <option value="">همه انبارها</option>
            {warehouses.data?.map((w) => (
              <option key={w.id} value={w.id}>{w.name}</option>
            ))}
          </Select>
          <Input className="max-w-xs" placeholder="کد یا نام کالا" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-soft">
            <Checkbox checked={belowMin} onCheckedChange={(c) => { setBelowMin(c === true); setPage(1); }} />
            فقط زیر حداقل
          </label>
          <div className="flex-1" />
          {data.data ? (
            <div className="text-sm text-ink-soft">
              ارزش کل موجودی: <span className="tabular font-bold text-ink">{formatMoney(data.data.total_value, currency)}</span>
            </div>
          ) : null}
        </div>
        <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
          {data.isLoading ? (
            <Spinner />
          ) : data.isError ? (
            <ErrorBox error={data.error} />
          ) : !data.data?.items.length ? (
            <EmptyState icon={Boxes} title="موجودی ثبت نشده است" />
          ) : (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th className="w-28">کد</Th>
                    <Th>کالا</Th>
                    <Th className="w-36">انبار</Th>
                    <Th className="w-32">موجودی</Th>
                    <Th className="w-40">میانگین بها</Th>
                    <Th className="w-44">ارزش</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.data.items.map((r) => (
                    <Tr key={`${r.item_id}-${r.warehouse_id}`} className="cursor-pointer" onClick={() => setSelected(r)}>
                      <Td className="tabular" dir="ltr">{r.item_code}</Td>
                      <Td>
                        {r.item_name}
                        {r.below_min ? <Badge tone="warning" className="ms-2">زیر حداقل</Badge> : null}
                      </Td>
                      <Td className="text-ink-soft">{whName(r.warehouse_id)}</Td>
                      <Td className="tabular font-semibold">
                        {toFaDigits(trimQty(r.qty))} <span className="text-xs font-normal text-ink-faint">{r.unit_name}</span>
                      </Td>
                      <Td className="tabular">{formatMoney(avgMoney(r.avg_cost), currency)}</Td>
                      <Td className="tabular">{formatMoney(r.value, currency)}</Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
              <Pagination page={page} pageSize={50} total={data.data.total} onPage={setPage} />
            </>
          )}
        </div>
      </Card>
      {selected ? <Kardex row={selected} onClose={() => setSelected(null)} /> : null}
    </div>
  );
}
