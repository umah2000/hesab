import { useQuery } from "@tanstack/react-query";
import { NavLink } from "react-router";
import { useCan } from "@/features/auth/auth";
import { api } from "@/lib/api";
import { toFaDigits } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Logo } from "./Logo";
import { NAV_ADMIN, NAV_MAIN, type NavItem } from "./nav";

const APP_VERSION = "0.1.0";

function Item({ item }: { item: NavItem }) {
  const Icon = item.icon;
  if (item.comingInPhase) {
    return (
      <div
        className="flex cursor-not-allowed items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-ink-faint/70"
        aria-disabled="true"
        title={`در فاز ${toFaDigits(item.comingInPhase)} فعال می‌شود`}
      >
        <Icon className="size-[18px]" aria-hidden />
        <span className="flex-1">{item.label}</span>
        <span className="rounded-full bg-black/5 px-2 py-0.5 text-[10px] dark:bg-white/10">
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
            ? "bg-gradient-to-l from-brand-500 to-brand-600 text-white shadow-[0_8px_24px_-8px] shadow-brand-500/70"
            : "text-ink-soft hover:bg-white/50 hover:text-ink dark:hover:bg-white/10",
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
    <div className="glass rounded-2xl p-3.5">
      <div className="flex items-center gap-2.5">
        <span className="relative flex size-2.5">
          {ok ? (
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60" />
          ) : null}
          <span className={cn("relative inline-flex size-2.5 rounded-full", ok ? "bg-success" : "bg-danger")} />
        </span>
        <div className="text-xs">
          <p className="font-semibold text-ink">{ok ? "متصل به سرور" : "قطع ارتباط با سرور"}</p>
          <p className="text-ink-faint">{ok ? "پایگاه داده در دسترس است" : "پایگاه داده در دسترس نیست"}</p>
        </div>
      </div>
      <p className="mt-2 text-[11px] text-ink-faint" dir="ltr">
        v{APP_VERSION}
      </p>
    </div>
  );
}

export function SidebarContent() {
  const can = useCan();
  const admin = NAV_ADMIN.filter((i) => can(i.permission));
  return (
    <>
      <div className="mb-6 flex items-center gap-3 px-2 pt-1">
        <Logo size={40} />
        <div>
          <p className="font-extrabold tracking-tight text-ink">NEXTCAM</p>
          <p className="text-xs text-ink-faint">حسابداری و انبارداری</p>
        </div>
      </div>
      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto" aria-label="منوی اصلی">
        {NAV_MAIN.filter((i) => i.comingInPhase || can(i.permission)).map((item) => (
          <Item key={item.to} item={item} />
        ))}
        {admin.length ? (
          <>
            <p className="mt-5 mb-1 px-3 text-[11px] font-semibold text-ink-faint">مدیریت</p>
            {admin.map((item) => (
              <Item key={item.to} item={item} />
            ))}
          </>
        ) : null}
      </nav>
      <ServerStatus />
    </>
  );
}

export function Sidebar() {
  return (
    <aside className="glass sticky top-4 hidden h-[calc(100vh-2rem)] w-64 shrink-0 flex-col rounded-3xl p-4 lg:flex">
      <SidebarContent />
    </aside>
  );
}
