import { ShieldAlert } from "lucide-react";
import { Outlet } from "react-router";
import { ModuleTabs, PageTitle } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/feedback";
import { useCan } from "@/features/auth/auth";

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
          <ModuleTabs label="بخش‌های خزانه‌داری" tabs={TABS} />
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
