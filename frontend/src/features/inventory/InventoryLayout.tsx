import { Outlet } from "react-router";
import { ModuleTabs, PageTitle } from "@/components/layout/AppShell";
import { useCan } from "@/features/auth/auth";

const TABS = [
  { to: "/inventory/items", label: "کالاها" },
  { to: "/inventory/documents", label: "اسناد انبار", perm: ["inventory.stock.create", "inventory.stock.adjust", "inventory.report.view"] },
  { to: "/inventory/balances", label: "موجودی و کاردکس", perm: ["inventory.report.view", "inventory.stock.create", "inventory.item.manage"] },
  { to: "/inventory/labels", label: "برچسب بارکد", perm: ["inventory.item.manage", "inventory.stock.create"] },
  { to: "/inventory/price-tickets", label: "برچسب قیمت", perm: ["inventory.item.manage", "inventory.price.manage"] },
  { to: "/inventory/import", label: "ورود از Excel", perm: "import.run" },
  { to: "/inventory/settings", label: "تنظیمات انبار" },
];

export function InventoryLayout() {
  const can = useCan();
  return (
    <>
      <PageTitle title="کالا و انبار" subtitle="کالاها، بارکد، موجودی، اسناد انبار و برچسب" />
      <ModuleTabs label="بخش‌های انبار" tabs={TABS.filter((t) => can(t.perm))} />
      <Outlet />
    </>
  );
}
