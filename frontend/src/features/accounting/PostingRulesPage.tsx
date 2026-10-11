import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, Workflow } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge, ErrorBox, Spinner } from "@/components/ui/feedback";
import { ApiError, api } from "@/lib/api";
import { useAccounts } from "./api";
import { Picker, accountOptions } from "./inputs";

type Rule = {
  event_type: string;
  event_label: string;
  line_role: string;
  role_label: string;
  account_id: string | null;
  account_code: string | null;
  account_name: string | null;
};

export function PostingRulesPage() {
  const qc = useQueryClient();
  const accounts = useAccounts();
  const options = React.useMemo(() => accountOptions(accounts.data, { postableOnly: true }), [accounts.data]);
  const rules = useQuery({ queryKey: ["accounting", "posting-rules"], queryFn: () => api.get<Rule[]>("/accounting/posting-rules") });
  const set = useMutation({
    mutationFn: (r: { event_type: string; line_role: string; account_id: string }) => api.put<Rule[]>("/accounting/posting-rules", r, ""),
    onSuccess: (data) => {
      qc.setQueryData(["accounting", "posting-rules"], data);
      toast.success("قاعده ذخیره شد");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "خطا"),
  });

  const groups = React.useMemo(() => {
    const m = new Map<string, Rule[]>();
    for (const r of rules.data ?? []) m.set(r.event_label, [...(m.get(r.event_label) ?? []), r]);
    return [...m.entries()];
  }, [rules.data]);

  if (rules.isLoading) return <Spinner />;
  if (rules.isError) return <ErrorBox error={rules.error} />;

  return (
    <div className="flex flex-col gap-4">
      <p className="glass flex items-start gap-2 rounded-2xl p-4 text-sm text-ink-soft">
        <Info className="mt-0.5 size-4 shrink-0 text-info" />
        اسناد خودکار (فروش، خرید، شیفت صندوق و …) حساب‌ها را از این جدول می‌خوانند؛ هیچ حسابی در کد برنامه ثابت نیست. تغییر هر قاعده فقط روی اسناد بعدی اثر دارد و در ممیزی ثبت می‌شود.
      </p>
      <div className="grid gap-4 xl:grid-cols-2">
        {groups.map(([label, items]) => (
          <Card key={label}>
            <CardHeader icon={<Workflow className="size-5" />} title={label} />
            <CardBody className="flex flex-col gap-2">
              {items.map((r) => (
                <div key={r.line_role} className="grid grid-cols-[10rem_1fr] items-center gap-3">
                  <span className="text-sm text-ink-soft">
                    {r.role_label}
                    {!r.account_id ? <Badge tone="danger" className="ms-2">تعریف نشده</Badge> : null}
                  </span>
                  <Picker
                    ariaLabel={`${label} — ${r.role_label}`}
                    options={options}
                    value={r.account_id}
                    onChange={(id) => id && id !== r.account_id && set.mutate({ event_type: r.event_type, line_role: r.line_role, account_id: id })}
                  />
                </div>
              ))}
            </CardBody>
          </Card>
        ))}
      </div>
    </div>
  );
}
