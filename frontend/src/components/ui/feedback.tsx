import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle, type LucideIcon } from "lucide-react";
import type * as React from "react";
import { cn } from "@/lib/utils";

export type Tone = "success" | "warning" | "danger" | "info" | "neutral" | "brand";

const toneClass: Record<Tone, string> = {
  success: "bg-success/12 text-success ring-success/25",
  warning: "bg-warning/15 text-[oklch(0.5_0.13_70)] ring-warning/30 dark:text-warning",
  danger: "bg-danger/12 text-danger ring-danger/25",
  info: "bg-info/12 text-info ring-info/25",
  neutral: "bg-black/5 text-ink-soft ring-black/10 dark:bg-white/10 dark:ring-white/10",
  brand: "bg-brand-500/12 text-brand-600 ring-brand-500/25 dark:text-brand-300",
};

const toneIcon: Partial<Record<Tone, LucideIcon>> = {
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: XCircle,
  info: Info,
};

/** Status is never conveyed by colour alone: text is required, icon by default. */
export function Badge({
  tone = "neutral",
  icon = true,
  children,
  className,
}: {
  tone?: Tone;
  icon?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  const Icon = icon ? toneIcon[tone] : undefined;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset",
        toneClass[tone],
        className,
      )}
    >
      {Icon ? <Icon className="size-3.5" aria-hidden /> : null}
      {children}
    </span>
  );
}

export function Spinner({ label = "در حال بارگذاری…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-10 text-sm text-ink-faint">
      <Loader2 className="size-5 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div className="mb-2 grid size-14 place-items-center rounded-2xl bg-brand-500/10 text-brand-500">
        <Icon className="size-7" aria-hidden />
      </div>
      <p className="font-semibold text-ink">{title}</p>
      {description ? <p className="max-w-sm text-sm text-ink-faint">{description}</p> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "خطای ناشناخته";
  const incident = (error as { incident?: string })?.incident;
  return (
    <div role="alert" className="m-5 flex items-start gap-3 rounded-xl bg-danger/10 p-4 text-sm text-danger">
      <XCircle className="mt-0.5 size-5 shrink-0" aria-hidden />
      <div>
        <p className="font-medium">{message}</p>
        {incident ? <p className="mt-1 text-xs opacity-80">کد پیگیری: {incident}</p> : null}
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-lg bg-black/5 dark:bg-white/10", className)} />;
}
