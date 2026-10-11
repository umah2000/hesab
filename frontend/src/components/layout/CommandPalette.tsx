import * as DialogPrimitive from "@radix-ui/react-dialog";
import { CornerDownLeft, Search } from "lucide-react";
import * as React from "react";
import { useNavigate } from "react-router";
import { useCan } from "@/features/auth/auth";
import { cn } from "@/lib/utils";
import { NAV_ADMIN, NAV_MAIN } from "./nav";

/** Keyboard-first navigation: Ctrl+K, type, arrows, Enter. */
export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const can = useCan();
  const navigate = useNavigate();
  const [query, setQuery] = React.useState("");
  const [active, setActive] = React.useState(0);

  const items = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return [...NAV_MAIN, ...NAV_ADMIN]
      .filter((i) => !i.comingInPhase && can(i.permission))
      .filter((i) => !q || `${i.label} ${i.keywords ?? ""}`.toLowerCase().includes(q));
  }, [query, can]);

  React.useEffect(() => setActive(0), [query, open]);
  React.useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const go = (to: string) => {
    onOpenChange(false);
    navigate(to);
  };

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-[oklch(0.2_0.05_275/0.3)]" />
        <DialogPrimitive.Content
          dir="rtl"
          className="glass-strong fixed top-[15vh] left-1/2 z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-3xl"
        >
          <DialogPrimitive.Title className="sr-only">جست‌وجوی سریع</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">نام صفحه را بنویسید و Enter بزنید</DialogPrimitive.Description>
          <div className="flex items-center gap-3 border-b border-[var(--line)] px-5">
            <Search className="size-5 text-ink-faint" aria-hidden />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setActive((a) => Math.min(a + 1, items.length - 1));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setActive((a) => Math.max(a - 1, 0));
                } else if (e.key === "Enter" && items[active]) {
                  go(items[active].to);
                }
              }}
              placeholder="کجا برویم؟"
              className="h-14 flex-1 bg-transparent text-base text-ink outline-none placeholder:text-ink-faint"
            />
          </div>
          <ul className="max-h-80 overflow-y-auto p-2" role="listbox">
            {items.length === 0 ? (
              <li className="px-4 py-8 text-center text-sm text-ink-faint">نتیجه‌ای یافت نشد</li>
            ) : (
              items.map((item, i) => {
                const Icon = item.icon;
                return (
                  <li key={item.to} role="option" aria-selected={i === active}>
                    <button
                      type="button"
                      onMouseEnter={() => setActive(i)}
                      onClick={() => go(item.to)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-ink",
                        i === active && "bg-brand-500/10",
                      )}
                    >
                      <Icon className="size-4 text-brand-500" aria-hidden />
                      <span className="flex-1 text-start">{item.label}</span>
                      {i === active ? <CornerDownLeft className="size-4 text-ink-faint" aria-hidden /> : null}
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
