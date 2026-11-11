import { Outlet } from "react-router";
import { ModuleTabs, PageTitle } from "@/components/layout/AppShell";
import { useCan } from "@/features/auth/auth";

const TABS = [
  { to: "/accounting/vouchers", label: "اسناد حسابداری" },
  { to: "/accounting/reports", label: "گزارش‌ها", perm: "accounting.report.view" },
  { to: "/accounting/accounts", label: "کدینگ حساب‌ها" },
  { to: "/accounting/details", label: "حساب‌های تفصیلی" },
  { to: "/accounting/fiscal-years", label: "سال و دوره مالی" },
  { to: "/accounting/posting-rules", label: "قواعد ثبت خودکار", perm: "accounting.account.manage" },
  { to: "/accounting/weighbridge", label: "سامانه باسکول", perm: ["accounting.integration.manage", "accounting.report.view"] },
];

export function AccountingLayout() {
  const can = useCan();
  return (
    <>
      <PageTitle title="حسابداری" subtitle="اسناد، دفاتر و گزارش‌های مالی بر اساس اسناد قطعی" />
      <ModuleTabs label="بخش‌های حسابداری" tabs={TABS.filter((t) => can(t.perm))} />
      <Outlet />
    </>
  );
}
