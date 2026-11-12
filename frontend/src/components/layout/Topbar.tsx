import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useQueryClient } from "@tanstack/react-query";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { CalendarDays, ChevronDown, Gauge, Info, KeyRound, LogOut, Menu, Moon, Search, Sparkles, Sun } from "lucide-react";
import * as React from "react";
import { useLocation, useNavigate } from "react-router";
import { signOut, useMe } from "@/features/auth/auth";
import { formatLongDate } from "@/lib/format";
import { CommandPalette } from "./CommandPalette";
import { SidebarContent } from "./Sidebar";
import { type Perf, type Theme, usePreference } from "./preferences";

function Clock() {
  const [now, setNow] = React.useState(() => new Date());
  React.useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);
  const time = new Intl.DateTimeFormat("fa-IR", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Tehran",
  }).format(now);
  return (
    <div className="glass hidden h-11 items-center gap-2 rounded-full px-4 md:flex">
      <CalendarDays className="size-4 text-brand-600 dark:text-brand-300" aria-hidden />
      <span className="text-sm font-semibold text-ink">{formatLongDate(now)}</span>
      <span className="tabular text-xs text-ink-faint">{time}</span>
    </div>
  );
}

function MobileMenu() {
  const [open, setOpen] = React.useState(false);
  const location = useLocation();
  React.useEffect(() => setOpen(false), [location.pathname]);
  return (
    <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Trigger
        className="glass grid size-11 place-items-center rounded-full text-ink-soft lg:hidden"
        aria-label="منو"
      >
        <Menu className="size-5" />
      </DialogPrimitive.Trigger>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-[oklch(0.2_0.06_262/0.35)]" />
        <DialogPrimitive.Content
          dir="rtl"
          className="sidebar-navy fixed inset-y-0 right-0 z-50 flex w-72 flex-col p-4 shadow-2xl"
        >
          <DialogPrimitive.Title className="sr-only">منوی اصلی</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">پیمایش بخش‌های سامانه</DialogPrimitive.Description>
          <SidebarContent />
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0])
    .join("‌");
}

export function Topbar() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [paletteOpen, setPaletteOpen] = React.useState(false);
  const [theme, setTheme] = usePreference<Theme>("theme", "light");
  const [perf, setPerf] = usePreference<Perf>("perf", "glass");

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const logout = () => signOut(qc);

  return (
    <header className="no-print relative z-30 flex items-center gap-2 sm:gap-3">
      <MobileMenu />
      <button
        type="button"
        onClick={() => setPaletteOpen(true)}
        className="glass flex h-11 items-center gap-2 rounded-full px-4 text-sm text-ink-faint transition hover:bg-white/80 sm:max-w-md sm:flex-1 dark:hover:bg-white/10"
      >
        <Search className="size-[18px] text-ink-soft" aria-hidden />
        <span className="hidden flex-1 text-start sm:inline">جست‌وجو در بخش‌های مختلف…</span>
        <kbd className="hidden rounded-md sm:inline bg-black/5 px-1.5 py-0.5 text-[11px] dark:bg-white/10" dir="ltr">
          Ctrl K
        </kbd>
      </button>
      <div className="flex-1" />
      <Clock />
      <button
        type="button"
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        className="glass grid size-11 place-items-center rounded-full text-brand-700 transition hover:bg-white/80 dark:text-brand-200 dark:hover:bg-white/10"
        aria-label={theme === "dark" ? "حالت روشن" : "حالت تیره"}
        title={theme === "dark" ? "حالت روشن" : "حالت تیره"}
      >
        {theme === "dark" ? <Sun className="size-5" /> : <Moon className="size-5" />}
      </button>

      <DropdownMenu.Root dir="rtl">
        <DropdownMenu.Trigger className="glass flex h-12 items-center gap-2.5 rounded-full ps-1.5 pe-3 transition hover:bg-white/80 dark:hover:bg-white/10">
          <span className="grid size-9 place-items-center rounded-full bg-gradient-to-br from-brand-400 to-brand-600 text-sm font-bold text-white ring-2 ring-white/80 dark:ring-white/20">
            {me ? initials(me.full_name) : ""}
          </span>
          <span className="hidden text-start leading-tight sm:block">
            <span className="block text-sm font-semibold text-ink">{me?.full_name}</span>
            <span className="block text-xs text-ink-faint">{me?.roles.map((r) => r.name).join("، ")}</span>
          </span>
          <ChevronDown className="size-4 text-ink-faint" />
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content
            align="end"
            sideOffset={8}
            className="glass-strong z-50 min-w-56 rounded-2xl p-1.5 text-sm"
          >
            <DropdownMenu.Label className="px-3 py-2 text-xs text-ink-faint" dir="ltr">
              {me?.username}
            </DropdownMenu.Label>
            <DropdownMenu.Item
              onSelect={() => navigate("/account")}
              className="flex cursor-pointer items-center gap-2 rounded-xl px-3 py-2 text-ink outline-none data-[highlighted]:bg-brand-500/10"
            >
              <KeyRound className="size-4" /> تغییر رمز عبور
            </DropdownMenu.Item>
            <DropdownMenu.Item
              onSelect={() => navigate("/about")}
              className="flex cursor-pointer items-center gap-2 rounded-xl px-3 py-2 text-ink outline-none data-[highlighted]:bg-brand-500/10"
            >
              <Info className="size-4" /> درباره
            </DropdownMenu.Item>
            <DropdownMenu.Item
              onSelect={() => setPerf(perf === "lite" ? "glass" : "lite")}
              className="flex cursor-pointer items-center gap-2 rounded-xl px-3 py-2 text-ink outline-none data-[highlighted]:bg-brand-500/10"
            >
              {perf === "lite" ? <Sparkles className="size-4" /> : <Gauge className="size-4" />}
              {perf === "lite" ? "ظاهر شیشه‌ای" : "حالت سبک (سیستم ضعیف)"}
            </DropdownMenu.Item>
            <DropdownMenu.Separator className="my-1 h-px bg-[var(--line)]" />
            <DropdownMenu.Item
              onSelect={logout}
              className="flex cursor-pointer items-center gap-2 rounded-xl px-3 py-2 text-danger outline-none data-[highlighted]:bg-danger/10"
            >
              <LogOut className="size-4" /> خروج
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </header>
  );
}
