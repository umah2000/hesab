import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { FilePlus2, FileText } from "lucide-react";
import * as React from "react";
import { Link, useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Input, Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { useCan } from "@/features/auth/auth";
import { api, type Page } from "@/lib/api";
import { formatMoney, toEnDigits, toFaDigits } from "@/lib/format";
import { isoToJalaliFa } from "@/lib/jalali";
import { SOURCE_LABEL, type VoucherSummary, useCurrency, useCurrentYear, useFiscalYears } from "./api";

export function VouchersPage() {
  const can = useCan();
  const navigate = useNavigate();
  const currency = useCurrency();
  const years = useFiscalYears();
  const current = useCurrentYear();
  const [fy, setFy] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [number, setNumber] = React.useState("");
  const [page, setPage] = React.useState(1);
  const fyId = fy || current?.id || "";

  const params = new URLSearchParams({ page: String(page), page_size: "25" });
  if (fyId) params.set("fiscal_year_id", fyId);
  if (status) params.set("status", status);
  const n = toEnDigits(number).replace(/\D/g, "");
  if (n) params.set("number", n);

  const q = useQuery({
    queryKey: ["accounting", "vouchers", params.toString()],
    queryFn: () => api.get<Page<VoucherSummary>>(`/accounting/vouchers?${params}`),
    enabled: !!fyId,
    placeholderData: keepPreviousData,
  });

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3 p-4">
        <Select className="w-44" value={fyId} onChange={(e) => { setFy(e.target.value); setPage(1); }} aria-label="سال مالی">
          {years.data?.map((y) => (
            <option key={y.id} value={y.id}>
              {y.title}
              {y.status === "closed" ? " (بسته)" : ""}
            </option>
          ))}
        </Select>
        <Select className="w-40" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="وضعیت">
          <option value="">همه وضعیت‌ها</option>
          <option value="draft">پیش‌نویس</option>
          <option value="final">قطعی</option>
        </Select>
        <Input className="w-36" placeholder="شماره سند" value={number} onChange={(e) => { setNumber(e.target.value); setPage(1); }} inputMode="numeric" />
        <div className="flex-1" />
        {can("accounting.voucher.create") ? (
          <Button asChild>
            <Link to="/accounting/vouchers/new">
              <FilePlus2 /> سند جدید
            </Link>
          </Button>
        ) : null}
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {q.isLoading || years.isLoading ? (
          <Spinner />
        ) : q.isError ? (
          <ErrorBox error={q.error} />
        ) : !q.data || q.data.items.length === 0 ? (
          <EmptyState
            icon={FileText}
            title="سندی یافت نشد"
            description={!fyId ? "ابتدا سال مالی را در «سال و دوره مالی» تعریف کنید." : undefined}
            action={
              can("accounting.voucher.create") && fyId ? (
                <Button asChild>
                  <Link to="/accounting/vouchers/new">ثبت اولین سند</Link>
                </Button>
              ) : null
            }
          />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th className="w-24">شماره</Th>
                  <Th className="w-28">تاریخ</Th>
                  <Th>شرح</Th>
                  <Th className="w-24">نوع</Th>
                  <Th className="w-44">مبلغ</Th>
                  <Th className="w-32">وضعیت</Th>
                </tr>
              </thead>
              <tbody>
                {q.data.items.map((v) => (
                  <Tr key={v.id} className="cursor-pointer" onClick={() => navigate(`/accounting/vouchers/${v.id}`)}>
                    <Td className="tabular font-semibold">{v.number ? toFaDigits(v.number) : <span className="text-ink-faint">—</span>}</Td>
                    <Td className="tabular text-ink-soft">{isoToJalaliFa(v.document_date)}</Td>
                    <Td className="max-w-md truncate">{v.description ?? <span className="text-ink-faint">بدون شرح</span>}</Td>
                    <Td className="text-ink-soft">{SOURCE_LABEL[v.source_type]}</Td>
                    <Td className="tabular">{formatMoney(v.total_debit, currency)}</Td>
                    <Td>
                      {v.status === "draft" ? (
                        <Badge tone="warning">پیش‌نویس</Badge>
                      ) : v.reversed_by_id ? (
                        <Badge tone="danger">برگشت‌خورده</Badge>
                      ) : (
                        <Badge tone="success">قطعی</Badge>
                      )}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={25} total={q.data.total} onPage={setPage} />
          </>
        )}
      </div>
    </Card>
  );
}
