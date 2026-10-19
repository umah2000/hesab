import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge, Spinner, type Tone } from "@/components/ui/feedback";
import { useCan } from "@/features/auth/auth";
import { ApiError, api } from "@/lib/api";
import { formatDate, toFaDigits } from "@/lib/format";

export type LicenseState = "unlicensed" | "invalid" | "valid" | "expiring" | "expired";

export type LicenseStatus = {
  state: LicenseState;
  customer: string | null;
  issued_at: string | null;
  valid_until: string | null;
  support_until: string | null;
  days_left: number | null;
  features: { code: string; label: string; enabled: boolean }[];
  limits: { kind: string; label: string; used: number; limit: number | null }[];
  installation_id: string;
  request_code: string;
  warnings: string[];
};

const STATE: Record<LicenseState, { tone: Tone; label: string }> = {
  valid: { tone: "success", label: "معتبر" },
  expiring: { tone: "warning", label: "رو به پایان" },
  expired: { tone: "danger", label: "منقضی" },
  invalid: { tone: "danger", label: "نامعتبر" },
  unlicensed: { tone: "neutral", label: "بدون مجوز" },
};

export function useLicense(enabled = true) {
  return useQuery({
    queryKey: ["system", "license"],
    queryFn: () => api.get<LicenseStatus>("/system/license"),
    enabled,
    staleTime: 300_000,
  });
}

export function LicenseCard() {
  const can = useCan();
  const qc = useQueryClient();
  const status = useLicense(can(["settings.manage", "reports.dashboard", "audit.view"]));
  const [text, setText] = React.useState("");
  const install = useMutation({
    mutationFn: () => api.post<LicenseStatus>("/system/license", { text }),
    onSuccess: (d) => {
      qc.setQueryData(["system", "license"], d);
      setText("");
      toast.success("مجوز نصب شد");
    },
    onError: (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا"),
  });
  if (!can(["settings.manage", "reports.dashboard", "audit.view"])) return null;
  const d = status.data;
  const copy = async () => {
    if (!d) return;
    try {
      await navigator.clipboard.writeText(d.request_code);
      toast.success("کد درخواست کپی شد");
    } catch {
      toast.error("کپی ممکن نشد؛ کد را انتخاب و کپی کنید");
    }
  };
  return (
    <Card>
      <CardHeader
        icon={<KeyRound className="size-5" />}
        title="مجوز نرم‌افزار"
        description="سقف شعبه، صندوق و کاربر و امکانات اختیاری. مجوز هرگز فروش، ورود، گزارش یا پشتیبان‌گیری را متوقف نمی‌کند."
      />
      <CardBody className="flex flex-col gap-3 text-sm">
        {status.isLoading || !d ? (
          <Spinner />
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <Badge tone={STATE[d.state].tone}>{STATE[d.state].label}</Badge>
              {d.customer ? <span>صادرشده برای: <b>{d.customer}</b></span> : null}
              {d.valid_until ? (
                <span>
                  اعتبار تا: <b>{formatDate(d.valid_until)}</b>
                  {d.days_left !== null && d.days_left >= 0 ? ` (${toFaDigits(d.days_left)} روز مانده)` : ""}
                </span>
              ) : d.customer ? (
                <span>اعتبار: <b>دائمی</b></span>
              ) : null}
              {d.support_until ? <span>پشتیبانی و به‌روزرسانی تا: <b>{formatDate(d.support_until)}</b></span> : null}
            </div>
            {d.warnings.length ? (
              <ul className="list-inside list-disc rounded-xl bg-warning/10 p-3 text-ink">
                {d.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            ) : null}
            <table className="w-full max-w-md text-right">
              <thead className="text-xs text-ink-faint">
                <tr>
                  <th className="py-1 font-normal">مورد</th>
                  <th className="py-1 font-normal">فعال</th>
                  <th className="py-1 font-normal">سقف مجوز</th>
                </tr>
              </thead>
              <tbody>
                {d.limits.map((l) => (
                  <tr key={l.kind} className="border-t border-[var(--line)]">
                    <td className="py-1.5">{l.label}</td>
                    <td className="py-1.5 tabular-nums">{toFaDigits(l.used)}</td>
                    <td className="py-1.5 tabular-nums">{l.limit === null ? "بدون سقف" : toFaDigits(l.limit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex flex-wrap gap-2">
              {d.features.map((f) => (
                <Badge key={f.code} tone={f.enabled || d.state === "unlicensed" ? "success" : "neutral"}>
                  {f.label}: {f.enabled ? "فعال" : d.state === "unlicensed" ? "بدون محدودیت" : "در مجوز نیست"}
                </Badge>
              ))}
            </div>
            {can("settings.manage") ? (
              <div className="flex flex-col gap-2 rounded-xl border border-[var(--line)] bg-[var(--surface)] p-3">
                <p className="font-medium text-ink">فعال‌سازی یا تمدید</p>
                <p className="text-xs text-ink-soft">
                  ۱) کد درخواست زیر را برای فروشنده بفرستید. ۲) متن مجوزی را که فروشنده می‌فرستد این‌جا بچسبانید و نصب کنید.
                </p>
                <div className="flex items-start gap-2">
                  <code dir="ltr" className="block flex-1 break-all rounded-lg bg-black/5 p-2 text-xs dark:bg-white/10">
                    {d.request_code}
                  </code>
                  <Button size="sm" variant="outline" onClick={copy} aria-label="کپی کد درخواست">
                    <Copy /> کپی
                  </Button>
                </div>
                <textarea
                  dir="ltr"
                  rows={3}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="NCL1.…"
                  aria-label="متن مجوز"
                  className="rounded-xl border border-[var(--line)] bg-[var(--surface)] px-3 py-2 font-mono text-xs text-ink outline-none focus:ring-2 focus:ring-brand-400"
                />
                <div>
                  <Button size="sm" disabled={text.trim().length < 10} loading={install.isPending} onClick={() => install.mutate()}>
                    <KeyRound /> نصب مجوز
                  </Button>
                </div>
              </div>
            ) : null}
          </>
        )}
      </CardBody>
    </Card>
  );
}
