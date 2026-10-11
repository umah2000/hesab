import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeft,
  BookOpenText,
  Boxes,
  Building2,
  CircleCheck,
  Clock3,
  Database,
  ScrollText,
  Settings,
  ShieldCheck,
  ShoppingCart,
  Users,
} from "lucide-react";
import { Link } from "react-router";
import { PageTitle } from "@/components/layout/AppShell";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge, Skeleton } from "@/components/ui/feedback";
import { useCan, useMe } from "@/features/auth/auth";
import type { AuditEvent } from "@/features/audit/AuditPage";
import { actionLabel } from "@/features/audit/labels";
import type { Organization } from "@/features/settings/types";
import { api, type Page } from "@/lib/api";
import { formatDate, formatDateTime, formatTime, toFaDigits } from "@/lib/format";
import { cn } from "@/lib/utils";

const ROADMAP = [
  { phase: 1, title: "کاربران، نقش‌ها و ممیزی", icon: ShieldCheck, status: "done" as const },
  { phase: 2, title: "هسته حسابداری", icon: BookOpenText, status: "done" as const },
  { phase: 3, title: "کالا، انبار و بارکد", icon: Boxes, status: "active" as const },
  { phase: 4, title: "صندوق فروش و پایلوت", icon: ShoppingCart, status: "next" as const },
];

function StatTile({
  icon: Icon,
  label,
  value,
  hint,
  tone,
}: {
  icon: typeof Users;
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone: "brand" | "success" | "info" | "warning";
}) {
  const tones = {
    brand: "from-brand-400 to-brand-600",
    success: "from-[oklch(0.75_0.14_165)] to-[oklch(0.6_0.15_165)]",
    info: "from-[oklch(0.75_0.12_230)] to-[oklch(0.58_0.15_250)]",
    warning: "from-[oklch(0.82_0.14_75)] to-[oklch(0.7_0.16_55)]",
  };
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm text-ink-faint">{label}</p>
          <div className="mt-2 text-xl font-extrabold text-ink">{value}</div>
          {hint ? <div className="mt-1.5 text-xs text-ink-faint">{hint}</div> : null}
        </div>
        <div
          className={cn(
            "grid size-12 place-items-center rounded-2xl bg-gradient-to-br text-white shadow-lg",
            tones[tone],
          )}
        >
          <Icon className="size-6" aria-hidden />
        </div>
      </div>
    </Card>
  );
}

export function DashboardPage() {
  const { data: me } = useMe();
  const can = useCan();
  const ready = useQuery({
    queryKey: ["system", "ready"],
    queryFn: () => api.get<{ database: string }>("/system/ready"),
    retry: false,
  });
  const org = useQuery({
    queryKey: ["organization"],
    queryFn: () => api.get<Organization>("/organization/settings"),
  });
  const audit = useQuery({
    queryKey: ["audit", "recent"],
    queryFn: () => api.get<Page<AuditEvent>>("/audit/events?page_size=6"),
    enabled: can("audit.view"),
  });
  const users = useQuery({
    queryKey: ["users", "count"],
    queryFn: () => api.get<Page<unknown>>("/users?page_size=1"),
    enabled: can("users.manage"),
  });

  const dbUp = !ready.isError && ready.data?.database === "up";

  return (
    <div className="flex flex-col gap-4">
      <PageTitle
        title={`${me?.full_name ?? ""}، خوش آمدید`}
        subtitle={org.data ? org.data.name : undefined}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          icon={Database}
          label="پایگاه داده"
          tone={dbUp ? "success" : "warning"}
          value={ready.isLoading ? <Skeleton className="h-7 w-20" /> : dbUp ? "متصل" : "قطع"}
          hint={<Badge tone={dbUp ? "success" : "danger"}>{dbUp ? "SQL Server پاسخ می‌دهد" : "بررسی شود"}</Badge>}
        />
        <StatTile
          icon={Users}
          label="کاربران تعریف‌شده"
          tone="brand"
          value={
            !can("users.manage") ? "—" : users.isLoading ? <Skeleton className="h-7 w-12" /> : toFaDigits(users.data?.total ?? 0)
          }
          hint={can("users.manage") ? <Link to="/users" className="text-brand-600 hover:underline dark:text-brand-300">مدیریت کاربران</Link> : "نیازمند مجوز مدیریت کاربران"}
        />
        <StatTile
          icon={Clock3}
          label="پایان نشست شما"
          tone="info"
          value={me?.session_expires_at ? formatTime(me.session_expires_at) : "—"}
          hint={`${me?.session_expires_at ? formatDate(me.session_expires_at) : ""} · دسترسی: ${me?.all_branches ? "همه شعب" : `${toFaDigits(me?.branch_ids.length ?? 0)} شعبه`}`}
        />
        <StatTile
          icon={Building2}
          label="واحد نمایش مبالغ"
          tone="warning"
          value={org.data ? (org.data.display_currency === "IRT" ? "تومان" : "ریال") : <Skeleton className="h-7 w-16" />}
          hint={org.data ? `موجودی منفی: ${org.data.negative_stock_policy === "warn" ? "مجاز با هشدار" : org.data.negative_stock_policy === "deny" ? "غیرمجاز" : "آزاد"}` : null}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader
            icon={<ScrollText className="size-5" />}
            title="آخرین رویدادهای سیستم"
            description="ثبت‌شده در دفتر ممیزی (غیرقابل ویرایش)"
            actions={
              can("audit.view") ? (
                <Link to="/audit" className="flex items-center gap-1 text-sm text-brand-600 hover:underline dark:text-brand-300">
                  مشاهده همه <ArrowLeft className="size-4" />
                </Link>
              ) : null
            }
          />
          <CardBody>
            {!can("audit.view") ? (
              <p className="py-6 text-center text-sm text-ink-faint">برای مشاهده رویدادها مجوز «مشاهده ممیزی» لازم است.</p>
            ) : audit.isLoading ? (
              <div className="flex flex-col gap-2">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-12" />
                ))}
              </div>
            ) : (
              <ul className="flex flex-col divide-y divide-[var(--line)]">
                {audit.data?.items.map((e) => (
                  <li key={e.id} className="flex items-center gap-3 py-3">
                    <span
                      className={cn(
                        "grid size-9 place-items-center rounded-xl",
                        /failed|locked/.test(e.action)
                          ? "bg-danger/10 text-danger"
                          : "bg-brand-500/10 text-brand-600 dark:text-brand-300",
                      )}
                    >
                      <Activity className="size-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-ink">{actionLabel(e.action)}</p>
                      <p className="text-xs text-ink-faint">{e.username ?? "سیستم"}</p>
                    </div>
                    <span className="tabular text-xs text-ink-faint">{formatDateTime(e.occurred_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader icon={<CircleCheck className="size-5" />} title="مسیر راه‌اندازی" description="ماژول‌ها به ترتیب فعال می‌شوند" />
          <CardBody className="flex flex-col gap-2.5">
            {ROADMAP.map((r) => (
              <div
                key={r.phase}
                className={cn(
                  "flex items-center gap-3 rounded-2xl p-3",
                  r.status === "active" ? "bg-brand-500/10 ring-1 ring-brand-500/20" : "bg-black/[0.03] dark:bg-white/5",
                )}
              >
                <r.icon className={cn("size-5", r.status === "active" ? "text-brand-600 dark:text-brand-300" : "text-ink-faint")} />
                <div className="flex-1">
                  <p className="text-sm font-medium text-ink">{r.title}</p>
                  <p className="text-xs text-ink-faint">فاز {toFaDigits(r.phase)}</p>
                </div>
                {r.status === "done" ? <Badge tone="success">انجام شد</Badge> : r.status === "active" ? <Badge tone="brand" icon={false}>فعال</Badge> : r.status === "next" ? <Badge tone="info" icon={false}>بعدی</Badge> : null}
              </div>
            ))}
          </CardBody>
        </Card>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          { to: "/users", label: "کاربر جدید", icon: Users, perm: "users.manage" },
          { to: "/roles", label: "نقش‌ها و مجوزها", icon: ShieldCheck, perm: "roles.manage" },
          { to: "/settings", label: "شعب و صندوق‌ها", icon: Settings, perm: undefined },
          { to: "/audit", label: "دفتر ممیزی", icon: ScrollText, perm: "audit.view" },
        ]
          .filter((a) => can(a.perm))
          .map((a) => (
            <Link
              key={a.to}
              to={a.to}
              className="glass group flex items-center gap-3 rounded-2xl p-4 transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-float)]"
            >
              <span className="grid size-11 place-items-center rounded-xl bg-white/70 text-brand-600 shadow-sm dark:bg-white/10 dark:text-brand-300">
                <a.icon className="size-5" />
              </span>
              <span className="flex-1 text-sm font-semibold text-ink">{a.label}</span>
              <ArrowLeft className="size-4 text-ink-faint transition group-hover:-translate-x-1" />
            </Link>
          ))}
      </div>
    </div>
  );
}
