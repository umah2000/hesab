import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, PlugZap, RotateCw, Truck } from "lucide-react";
import * as React from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge, EmptyState, ErrorBox, Spinner, type Tone } from "@/components/ui/feedback";
import { Input, Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { useCan } from "@/features/auth/auth";
import { ApiError, api } from "@/lib/api";
import { formatDate, formatDateTime, formatMoney, toFaDigits } from "@/lib/format";
import { useCurrency } from "./api";

type DocStatus = "posted" | "held" | "voided" | "reversed";

type Doc = {
  id: string;
  number: string;
  kind: "haulage" | "sales" | null;
  counterparty_code: string | null;
  counterparty_name: string | null;
  document_date: string | null;
  total: string | null;
  status: DocStatus;
  problem: string | null;
  void_reason: string | null;
  voucher_id: string | null;
  voucher_number: number | null;
  reversal_voucher_id: string | null;
  reversal_voucher_number: number | null;
  created_at: string;
};

type Status = {
  configured: boolean;
  held: number;
  posted: number;
  last_event_at: string | null;
  last_events: { event_type: string; result: string; message: string | null; received_at: string; document_number: string | null }[];
};

const STATUS: Record<DocStatus, { label: string; tone: Tone }> = {
  posted: { label: "ثبت شد", tone: "success" },
  held: { label: "منتظر رسیدگی", tone: "warning" },
  voided: { label: "باطل (بدون سند)", tone: "neutral" },
  reversed: { label: "باطل و برگشت خورد", tone: "neutral" },
};

const KIND = { haulage: "صورت‌وضعیت حمل", sales: "صورت‌حساب فروش" } as const;

const RESULT: Record<string, string> = {
  posted: "ثبت شد",
  held: "منتظر رسیدگی",
  duplicate: "تکراری، بی‌اثر",
  voided: "باطل شد",
  reversed: "برگشت خورد",
  ignored: "نادیده",
};

const EVENT = { "settlement.approved": "تأیید", "settlement.voided": "ابطال", "webhook.ping": "آزمایش اتصال" } as Record<string, string>;

/** Statements of the weighbridge platform posted here (ADR-0025). */
export function WeighbridgePage() {
  const can = useCan();
  const qc = useQueryClient();
  const currency = useCurrency();
  const [status, setStatus] = React.useState<DocStatus | "">("");
  const [q, setQ] = React.useState("");
  const [page, setPage] = React.useState(1);
  const info = useQuery({ queryKey: ["integrations", "va", "status"], queryFn: () => api.get<Status>("/integrations/va/status") });
  const params = new URLSearchParams({ page: String(page), page_size: "25" });
  if (status) params.set("status", status);
  if (q.trim()) params.set("q", q.trim());
  const docs = useQuery({
    queryKey: ["integrations", "va", "documents", status, q, page],
    queryFn: () => api.get<{ items: Doc[]; total: number; page: number; page_size: number }>(`/integrations/va/documents?${params}`),
  });
  const retry = useMutation({
    mutationFn: (id: string) => api.post<Doc>(`/integrations/va/documents/${id}/retry`),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["integrations", "va"] });
      if (d.status === "posted" || d.status === "reversed") toast.success("سند ثبت شد");
      else toast.warning(d.problem ?? "هنوز قابل ثبت نیست");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا"),
  });
  const money = (v: string | null) => (v ? formatMoney(v, currency) : "—");

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader
          icon={<PlugZap className="size-5" />}
          title="اتصال سامانه باسکول و پلاک‌خوان"
          description="صورت‌وضعیت‌های حمل و صورت‌حساب‌های فروشِ تأییدشده در آن سامانه، این‌جا خودکار سند می‌شوند؛ ابطال آن‌جا سند برگشتی می‌سازد."
        />
        <CardBody className="flex flex-wrap items-center gap-3 text-sm">
          {info.data ? (
            <>
              {info.data.configured ? <Badge tone="success">پیکربندی شده</Badge> : <Badge tone="warning">پیکربندی نشده</Badge>}
              <span>ثبت‌شده: <b className="tabular">{toFaDigits(info.data.posted)}</b></span>
              <span>
                منتظر رسیدگی: <b className="tabular">{toFaDigits(info.data.held)}</b>
              </span>
              <span className="text-ink-faint">
                آخرین دریافت: {info.data.last_event_at ? formatDateTime(info.data.last_event_at) : "هنوز چیزی نرسیده"}
              </span>
            </>
          ) : (
            <Spinner />
          )}
          {info.data && !info.data.configured ? (
            <p className="flex w-full items-start gap-1.5 text-xs text-ink-soft">
              <Info className="mt-0.5 size-3.5 shrink-0 text-info" />
              در سامانه باسکول یک وب‌هوک به نشانی
              <span className="latin-digits" dir="ltr">/api/v1/integrations/va/webhook</span> بسازید و کلید امضای آن را با
              شناسه‌ی سازمان در NEXTCAM_VA_WEBHOOK_SECRET و NEXTCAM_VA_TENANT_ID روی سرور بگذارید (راهنمای نصب).
            </p>
          ) : null}
        </CardBody>
      </Card>

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 p-4">
          <Input
            className="max-w-xs"
            placeholder="جست‌وجوی شماره یا طرف‌حساب"
            aria-label="جست‌وجو"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
          <Select
            className="w-52"
            aria-label="وضعیت"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as DocStatus | "");
              setPage(1);
            }}
          >
            <option value="">همه‌ی وضعیت‌ها</option>
            {(Object.keys(STATUS) as DocStatus[]).map((k) => (
              <option key={k} value={k}>{STATUS[k].label}</option>
            ))}
          </Select>
        </div>
        {docs.isLoading ? (
          <Spinner />
        ) : docs.isError ? (
          <ErrorBox error={docs.error} />
        ) : !docs.data?.items.length ? (
          <EmptyState icon={Truck} title="سندی نرسیده" description="پس از تأیید اولین صورت‌وضعیت در سامانه باسکول، این‌جا نمایش داده می‌شود." />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>شماره</Th>
                  <Th>نوع</Th>
                  <Th>طرف‌حساب</Th>
                  <Th>پایان دوره</Th>
                  <Th>مبلغ کل</Th>
                  <Th>وضعیت</Th>
                  <Th>سند</Th>
                </tr>
              </thead>
              <tbody>
                {docs.data.items.map((d) => (
                  <Tr key={d.id}>
                    <Td className="latin-digits whitespace-nowrap" dir="ltr">{d.number}</Td>
                    <Td>{d.kind ? KIND[d.kind] : "—"}</Td>
                    <Td>
                      {d.counterparty_name ?? "—"}
                      {d.counterparty_code ? (
                        <div className="latin-digits text-xs text-ink-faint" dir="ltr">
                          {d.counterparty_code}
                        </div>
                      ) : null}
                    </Td>
                    <Td className="tabular">{d.document_date ? formatDate(d.document_date) : "—"}</Td>
                    <Td className="tabular">{money(d.total)}</Td>
                    <Td>
                      <Badge tone={d.problem ? "warning" : STATUS[d.status].tone}>{d.problem && d.status === "posted" ? "ابطال منتظر رسیدگی" : STATUS[d.status].label}</Badge>
                      {d.problem ? <div className="mt-1 max-w-sm text-xs text-ink-soft">{d.problem}</div> : null}
                      {d.problem && can("accounting.integration.manage") ? (
                        <Button
                          className="mt-1.5"
                          size="sm"
                          variant="secondary"
                          loading={retry.isPending && retry.variables === d.id}
                          onClick={() => retry.mutate(d.id)}
                        >
                          <RotateCw /> ثبت دوباره
                        </Button>
                      ) : null}
                      {d.void_reason && !d.problem ? <div className="mt-1 text-xs text-ink-faint">علت ابطال: {d.void_reason}</div> : null}
                    </Td>
                    <Td className="tabular">
                      {d.voucher_id ? (
                        <Link className="text-brand-600 hover:underline" to={`/accounting/vouchers/${d.voucher_id}`}>
                          {toFaDigits(d.voucher_number ?? 0)}
                        </Link>
                      ) : (
                        "—"
                      )}
                      {d.reversal_voucher_id ? (
                        <>
                          {" ← "}
                          <Link className="text-brand-600 hover:underline" to={`/accounting/vouchers/${d.reversal_voucher_id}`}>
                            {toFaDigits(d.reversal_voucher_number ?? 0)}
                          </Link>
                        </>
                      ) : null}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={25} total={docs.data.total} onPage={setPage} />
          </>
        )}
      </Card>

      {info.data?.last_events.length ? (
        <Card>
          <CardHeader title="آخرین رویدادهای دریافتی" />
          <CardBody>
            <ul className="flex flex-col gap-1 text-sm">
              {info.data.last_events.map((e, i) => (
                <li key={i} className="flex flex-wrap gap-2">
                  <span className="tabular text-ink-faint">{formatDateTime(e.received_at)}</span>
                  <span>{EVENT[e.event_type] ?? e.event_type}</span>
                  {e.document_number ? <span className="latin-digits" dir="ltr">{e.document_number}</span> : null}
                  <span className="text-ink-soft">({RESULT[e.result] ?? e.result})</span>
                  {e.message ? <span className="text-xs text-ink-faint">{e.message}</span> : null}
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      ) : null}
    </div>
  );
}
