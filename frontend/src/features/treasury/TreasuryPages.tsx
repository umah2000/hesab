import { ShieldAlert } from "lucide-react";
import { NavLink, Outlet } from "react-router";
import { PageTitle } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/feedback";
import { useCan } from "@/features/auth/auth";
import { cn } from "@/lib/utils";

export { MoneyAccountsPage } from "./AccountsPage";
export { ChequesPage } from "./ChequesPage";
export { TreasuryDocumentPage, TreasuryDocumentsPage } from "./DocumentsPages";
export { ReconciliationPage } from "./ReconciliationPage";

export const TREASURY_PERMISSION = "treasury.manage";

const TABS = [
  { to: "/treasury/documents", label: "اسناد دریافت و پرداخت" },
  { to: "/treasury/cheques", label: "چک‌ها" },
  { to: "/treasury/accounts", label: "صندوق و بانک" },
  { to: "/treasury/reconciliation", label: "مغایرت بانکی" },
];

export function TreasuryLayout() {
  const can = useCan();
  return (
    <>
      <PageTitle title="خزانه‌داری" subtitle="دریافت و پرداخت، چک‌ها، صندوق و بانک و مغایرت‌گیری بانکی" />
      {can(TREASURY_PERMISSION) ? (
        <>
          <nav className="no-print glass mb-4 flex gap-1 overflow-x-auto rounded-2xl p-1.5" aria-label="بخش‌های خزانه‌داری">
            {TABS.map((t) => (
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
      ) : (
        <Card>
          <EmptyState icon={ShieldAlert} title="دسترسی ندارید" description="برای خزانه‌داری مجوز «treasury.manage» لازم است." />
        </Card>
      )}
    </>
  );
}
