import { NavLink, Outlet } from "react-router";
import { PageTitle } from "@/components/layout/AppShell";
import { useCan } from "@/features/auth/auth";
import { cn } from "@/lib/utils";

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
      <nav className="no-print glass mb-4 flex gap-1 overflow-x-auto rounded-2xl p-1.5" aria-label="بخش‌های انبار">
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
