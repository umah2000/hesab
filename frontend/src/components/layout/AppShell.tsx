import { ChevronLeft, type LucideIcon } from "lucide-react";
import * as React from "react";
import { Link, Outlet } from "react-router";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export function AppShell() {
  return (
    <div className="flex min-h-full print:block">
      <Sidebar />
      <div className="mx-auto flex w-full max-w-[1600px] min-w-0 flex-1 flex-col gap-4 p-3 sm:p-5 print:max-w-none print:p-0">
        <Topbar />
        <main className="flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export type Crumb = { label: string; to?: string };

/**
 * A page's title: optional breadcrumb above, an icon beside the title, and the page's
 * actions on the other side (the main one last, as a primary button).
 */
export function PageTitle({
  title,
  subtitle,
  actions,
  icon: Icon,
  crumbs,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  icon?: LucideIcon;
  crumbs?: Crumb[];
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3 px-1">
      <div className="min-w-0">
        {crumbs?.length ? (
          <nav aria-label="مسیر صفحه" className="mb-1.5 flex flex-wrap items-center gap-1 text-xs text-ink-faint">
            {crumbs.map((c, i) => (
              <React.Fragment key={`${c.label}-${i}`}>
                {i > 0 ? <ChevronLeft className="size-3.5" aria-hidden /> : null}
                {c.to ? (
                  <Link to={c.to} className="hover:text-brand-600 hover:underline dark:hover:text-brand-300">
                    {c.label}
                  </Link>
                ) : (
                  <span>{c.label}</span>
                )}
              </React.Fragment>
            ))}
          </nav>
        ) : null}
        <h1 className="flex items-center gap-2.5 text-2xl font-black tracking-tight text-ink">
          {Icon ? <Icon className="size-7 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden /> : null}
          {title}
        </h1>
        {subtitle ? <p className="mt-1 text-sm text-ink-faint">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
