import { ChevronLeft, Info, type LucideIcon } from "lucide-react";
import * as React from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { cn } from "@/lib/utils";
import { NAV_ADMIN, NAV_MAIN, type NavItem } from "./nav";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

const ALL_NAV: NavItem[] = [...NAV_MAIN, ...NAV_ADMIN, { to: "/about", label: "درباره", icon: Info }];

/** The menu item a path belongs to (longest prefix), for the page's icon and breadcrumb. */
function navFor(path: string): NavItem | undefined {
  return ALL_NAV.filter((n) => (n.to === "/" ? path === "/" : path === n.to || path.startsWith(`${n.to}/`))).sort(
    (a, b) => b.to.length - a.to.length,
  )[0];
}

// The active module tab, shown at the end of the breadcrumb (set by ModuleTabs).
const activeTab = { label: null as string | null, subs: new Set<() => void>() };
function setActiveTab(label: string | null) {
  if (activeTab.label === label) return;
  activeTab.label = label;
  for (const f of activeTab.subs) f();
}
function useActiveTab() {
  return React.useSyncExternalStore(
    (f) => {
      activeTab.subs.add(f);
      return () => activeTab.subs.delete(f);
    },
    () => activeTab.label,
  );
}

export type ModuleTab = { to: string; label: string };

/** A module's sections as tabs under its title (sales, inventory, accounting…). */
export function ModuleTabs({ tabs, label }: { tabs: ModuleTab[]; label: string }) {
  const { pathname } = useLocation();
  const active = tabs
    .filter((t) => pathname === t.to || pathname.startsWith(`${t.to}/`))
    .sort((a, b) => b.to.length - a.to.length)[0];
  React.useEffect(() => {
    setActiveTab(active?.label ?? null);
    return () => setActiveTab(null);
  }, [active?.label]);
  return (
    <nav className="no-print glass mb-4 flex gap-1 overflow-x-auto rounded-2xl p-1.5" aria-label={label}>
      {tabs.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          className={() =>
            cn(
              "rounded-xl px-4 py-2 text-sm font-medium whitespace-nowrap transition",
              t === active
                ? "bg-brand-500/12 font-semibold text-brand-700 ring-1 ring-brand-500/25 dark:bg-brand-400/20 dark:text-white dark:ring-brand-300/30"
                : "text-ink-soft hover:bg-white/60 hover:text-ink dark:hover:bg-white/10",
            )
          }
        >
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}

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
  icon,
  crumbs,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  icon?: LucideIcon;
  crumbs?: Crumb[];
}) {
  const { pathname } = useLocation();
  const tab = useActiveTab();
  const nav = navFor(pathname);
  const Icon = icon ?? nav?.icon;
  // Without explicit crumbs: home › module › active tab (whatever of these applies).
  const trail: Crumb[] =
    crumbs ??
    [
      { label: "خانه", to: "/" },
      ...(nav && nav.to !== "/" ? [{ label: nav.label, to: tab ? nav.to : undefined }] : []),
      ...(tab ? [{ label: tab }] : []),
    ];
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3 px-1">
      <div className="min-w-0">
        {trail.length > 1 ? (
          <nav aria-label="مسیر صفحه" className="mb-1.5 flex flex-wrap items-center gap-1 text-xs text-ink-faint">
            {trail.map((c, i) => (
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
