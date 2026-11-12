import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { NavLink } from "react-router";
import { useCan } from "@/features/auth/auth";
import { api } from "@/lib/api";
import { toFaDigits } from "@/lib/format";
import { cn } from "@/lib/utils";
import { BrandMark, useBranding } from "./branding";
import { NAV_ADMIN, NAV_MAIN, type NavItem } from "./nav";

const APP_VERSION = "0.1.0";

function Item({ item }: { item: NavItem }) {
  const Icon = item.icon;
  if (item.comingInPhase) {
    return (
      <div
        className="flex cursor-not-allowed items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-white/40"
        aria-disabled="true"
        title={`در فاز ${toFaDigits(item.comingInPhase)} فعال می‌شود`}
      >
        <Icon className="size-[18px]" aria-hidden />
        <span className="flex-1">{item.label}</span>
        <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px]">
          فاز {toFaDigits(item.comingInPhase)}
        </span>
      </div>
    );
  }
  return (
    <NavLink
      to={item.to}
      end={item.to === "/"}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all",
          isActive
            ? "bg-gradient-to-l from-brand-500/55 to-brand-500/25 font-semibold text-white ring-1 ring-white/15 shadow-[0_8px_24px_-10px] shadow-brand-400/60"
            : "text-white/75 hover:bg-white/[0.07] hover:text-white",
        )
      }
    >
      <Icon className="size-[18px]" aria-hidden />
      {item.label}
    </NavLink>
  );
}

function ServerStatus() {
  const { data, isError } = useQuery({
    queryKey: ["system", "ready"],
    queryFn: () => api.get<{ status: string; database: string }>("/system/ready"),
    refetchInterval: 30_000,
    retry: false,
  });
  const ok = !isError && data?.database === "up";
  return (
    <div className="rounded-2xl bg-white/[0.07] p-3.5 ring-1 ring-white/10">
      <div className="flex items-center gap-2.5">
        <span className="relative flex size-2.5">
          {ok ? (
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60" />
          ) : null}
          <span className={cn("relative inline-flex size-2.5 rounded-full", ok ? "bg-success" : "bg-danger")} />
        </span>
        <div className="text-xs">
          <p className="font-semibold text-white">{ok ? "متصل به سرور" : "قطع ارتباط با سرور"}</p>
          <p className="text-white/60">{ok ? "پایگاه داده در دسترس است" : "پایگاه داده در دسترس نیست"}</p>
        </div>
      </div>
    </div>
  );
}

export function SidebarContent() {
  const can = useCan();
  const brand = useBranding();
  const admin = NAV_ADMIN.filter((i) => can(i.permission));
  return (
    <>
      <div className="mb-6 flex items-center gap-3 px-2 pt-1">
        <BrandMark size={42} />
        <div className="min-w-0">
          <p className="truncate text-lg font-black tracking-tight text-white">{brand.data?.organization_name || "NEXTCAM"}</p>
          <p className="text-[11px] text-white/60">{brand.data?.organization_name ? "NEXTCAM ERP" : "حسابداری و انبارداری فروشگاهی"}</p>
        </div>
      </div>
      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto" aria-label="منوی اصلی">
        {NAV_MAIN.filter((i) => i.comingInPhase || can(i.permission)).map((item) => (
          <Item key={item.to} item={item} />
        ))}
        {admin.length ? (
          <>
            <p className="mt-5 mb-1 px-3 text-[11px] font-semibold text-white/45">مدیریت</p>
            {admin.map((item) => (
              <Item key={item.to} item={item} />
            ))}
          </>
        ) : null}
        <div className="mt-auto pt-3">
          <Item item={{ to: "/about", label: "درباره", icon: Info }} />
        </div>
      </nav>
      <ServerStatus />
      <p className="mt-2 text-center text-[11px] text-white/40">
        نسخه <span dir="ltr">{toFaDigits(APP_VERSION)}</span>
      </p>
    </>
  );
}

export function Sidebar() {
  return (
    // The navy band runs the page's full height; its content stays in view while scrolling.
    <aside className="no-print sidebar-navy hidden w-64 shrink-0 shadow-[0_0_40px_-12px] shadow-navy-900/60 lg:block">
      <div className="sticky top-0 flex h-screen flex-col p-4">
        <SidebarContent />
      </div>
    </aside>
  );
}
