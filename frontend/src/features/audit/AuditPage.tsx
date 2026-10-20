import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronDown, ScrollText } from "lucide-react";
import * as React from "react";
import { PageTitle } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { Badge, EmptyState, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Select } from "@/components/ui/form-controls";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/table";
import { api, type Page } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { ACTION_GROUPS, actionLabel } from "./labels";

export type AuditEvent = {
  id: string;
  occurred_at: string;
  user_id: string | null;
  username: string | null;
  branch_id: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  data: unknown;
  ip: string | null;
};

function tone(action: string) {
  if (action.includes("failed") || action.includes("locked")) return "danger" as const;
  if (action.startsWith("auth.")) return "info" as const;
  return "brand" as const;
}

export function AuditPage() {
  const [page, setPage] = React.useState(1);
  const [group, setGroup] = React.useState("");
  const [open, setOpen] = React.useState<string | null>(null);
  const q = useQuery({
    queryKey: ["audit", page, group],
    queryFn: () => api.get<Page<AuditEvent>>(`/audit/events?page=${page}&page_size=25${group ? `&action=${group}.` : ""}`),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageTitle title="رویدادهای ممیزی" subtitle="ثبت دائمی و غیرقابل ویرایش همه عملیات حساس" />
      <Card>
        <div className="flex items-center gap-3 p-4">
          <Select
            className="max-w-56"
            value={group}
            onChange={(e) => {
              setGroup(e.target.value);
              setPage(1);
            }}
            aria-label="نوع رویداد"
          >
            {ACTION_GROUPS.map((g) => (
              <option key={g.value} value={g.value}>
                {g.label}
              </option>
            ))}
          </Select>
        </div>
        <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
          {q.isLoading ? (
            <Spinner />
          ) : q.isError ? (
            <ErrorBox error={q.error} />
          ) : q.data?.items.length === 0 ? (
            <EmptyState icon={ScrollText} title="رویدادی ثبت نشده است" />
          ) : (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th>زمان</Th>
                    <Th>رویداد</Th>
                    <Th>کاربر</Th>
                    <Th>نشانی IP</Th>
                    <Th className="w-10" />
                  </tr>
                </thead>
                <tbody>
                  {q.data?.items.map((e) => (
                    <React.Fragment key={e.id}>
                      <Tr className="cursor-pointer" onClick={() => setOpen(open === e.id ? null : e.id)}>
                        <Td className="tabular whitespace-nowrap text-ink-soft">{formatDateTime(e.occurred_at)}</Td>
                        <Td>
                          <Badge tone={tone(e.action)} icon={tone(e.action) === "danger"}>
                            {actionLabel(e.action)}
                          </Badge>
                        </Td>
                        <Td>{e.username ?? <span className="text-ink-faint">—</span>}</Td>
                        <Td className="text-ink-faint" dir="ltr">{e.ip ?? "—"}</Td>
                        <Td>
                          {e.data ? <ChevronDown className={`size-4 text-ink-faint transition ${open === e.id ? "rotate-180" : ""}`} /> : null}
                        </Td>
                      </Tr>
                      {open === e.id && e.data ? (
                        <tr>
                          <td colSpan={5} className="bg-[var(--surface-muted)] px-4 py-3">
                            <pre dir="ltr" className="max-h-64 overflow-auto text-xs leading-relaxed whitespace-pre-wrap text-ink-soft">
                              {JSON.stringify(e.data, null, 2)}
                            </pre>
                          </td>
                        </tr>
                      ) : null}
                    </React.Fragment>
                  ))}
                </tbody>
              </Table>
              <Pagination page={page} pageSize={25} total={q.data?.total ?? 0} onPage={setPage} />
            </>
          )}
        </div>
      </Card>
    </>
  );
}
