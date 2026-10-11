import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge, ErrorBox, Spinner } from "@/components/ui/feedback";
import { Input, Select } from "@/components/ui/form-controls";
import { Table, Td, Th, Tr } from "@/components/ui/table";
import { useCan } from "@/features/auth/auth";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { type DetailAccount, useDetailAccounts } from "./api";

const KIND_LABEL: Record<DetailAccount["kind"], string> = {
  person: "شخص (مشتری/تأمین‌کننده)",
  bank: "حساب بانکی",
  cash: "صندوق",
  cost_center: "مرکز هزینه",
  project: "پروژه",
  other: "سایر",
};

export function DetailsPage() {
  const qc = useQueryClient();
  const can = useCan();
  const details = useDetailAccounts();
  const [code, setCode] = React.useState("");
  const [name, setName] = React.useState("");
  const [kind, setKind] = React.useState<DetailAccount["kind"]>("person");
  const [filter, setFilter] = React.useState("");
  const keyRef = React.useRef(newIdempotencyKey());

  const add = useMutation({
    mutationFn: () => api.post<DetailAccount>("/accounting/detail-accounts", { code, name, kind }, { idempotencyKey: keyRef.current }),
    onSuccess: () => {
      keyRef.current = newIdempotencyKey();
      setCode("");
      setName("");
      qc.invalidateQueries({ queryKey: ["accounting", "details"] });
      toast.success("حساب تفصیلی اضافه شد");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا"),
  });
  const toggle = useMutation({
    mutationFn: (d: DetailAccount) => api.patch(`/accounting/detail-accounts/${d.id}`, { is_active: !d.is_active }, d.row_version),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounting", "details"] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا"),
  });

  const rows = (details.data ?? []).filter((d) => !filter || d.name.includes(filter) || d.code.toLowerCase().includes(filter.toLowerCase()));

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 p-4">
        <Input className="max-w-xs" placeholder="جست‌وجو" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <div className="flex-1" />
        {can("accounting.account.manage") ? (
          <>
            <Input className="w-28" dir="ltr" placeholder="کد" value={code} onChange={(e) => setCode(e.target.value)} />
            <Input className="w-56" placeholder="نام" value={name} onChange={(e) => setName(e.target.value)} />
            <Select className="w-48" value={kind} onChange={(e) => setKind(e.target.value as DetailAccount["kind"])}>
              {Object.entries(KIND_LABEL).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </Select>
            <Button disabled={!code || name.length < 2} loading={add.isPending} onClick={() => add.mutate()}>
              <Plus /> افزودن
            </Button>
          </>
        ) : null}
      </div>
      <div className="surface mx-4 mb-4 overflow-hidden rounded-2xl">
        {details.isLoading ? (
          <Spinner />
        ) : details.isError ? (
          <ErrorBox error={details.error} />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th className="w-32">کد</Th>
                <Th>نام</Th>
                <Th className="w-56">نوع</Th>
                <Th className="w-32">وضعیت</Th>
                <Th className="w-32" />
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <Tr key={d.id}>
                  <Td className="tabular" dir="ltr">{d.code}</Td>
                  <Td>{d.name}</Td>
                  <Td className="text-ink-soft">{KIND_LABEL[d.kind]}</Td>
                  <Td>{d.is_active ? <Badge tone="success">فعال</Badge> : <Badge tone="neutral">غیرفعال</Badge>}</Td>
                  <Td>
                    {can("accounting.account.manage") ? (
                      <Button size="sm" variant="ghost" onClick={() => toggle.mutate(d)}>
                        {d.is_active ? "غیرفعال کن" : "فعال کن"}
                      </Button>
                    ) : null}
                  </Td>
                </Tr>
              ))}
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-10 text-center text-sm text-ink-faint">حساب تفصیلی تعریف نشده است</td>
                </tr>
              ) : null}
            </tbody>
          </Table>
        )}
      </div>
    </Card>
  );
}
