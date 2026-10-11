import { NavLink, Outlet } from "react-router";
import { PageTitle } from "@/components/layout/AppShell";
import { useCan } from "@/features/auth/auth";
import { cn } from "@/lib/utils";

const TABS = [
  { to: "/accounting/vouchers", label: "اسناد حسابداری" },
  { to: "/accounting/reports", label: "گزارش‌ها", perm: "accounting.report.view" },
  { to: "/accounting/accounts", label: "کدینگ حساب‌ها" },
  { to: "/accounting/details", label: "حساب‌های تفصیلی" },
  { to: "/accounting/fiscal-years", label: "سال و دوره مالی" },
  { to: "/accounting/posting-rules", label: "قواعد ثبت خودکار", perm: "accounting.account.manage" },
];

export function AccountingLayout() {
  const can = useCan();
  return (
    <>
      <PageTitle title="حسابداری" subtitle="اسناد، دفاتر و گزارش‌های مالی بر اساس اسناد قطعی" />
      <nav className="glass mb-4 flex gap-1 overflow-x-auto rounded-2xl p-1.5" aria-label="بخش‌های حسابداری">
        {TABS.filter((t) => can(t.perm)).map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              cn(
                "rounded-xl px-4 py-2 text-sm font-medium whitespace-nowrap transition",
                isActive ? "bg-white text-brand-600 shadow-sm dark:bg-white/15 dark:text-white" : "text-ink-soft hover:text-ink",
              )
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </>
  );
}
