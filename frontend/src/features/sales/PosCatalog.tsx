import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ImageOff, LayoutGrid, PackageX, Scale, WifiOff } from "lucide-react";
import * as React from "react";
import { Spinner } from "@/components/ui/feedback";
import { type ItemSummary, imageUrl, trimQty, useGroups } from "@/features/inventory/api";
import type { Picked } from "@/features/inventory/ItemSearch";
import { api, type Page } from "@/lib/api";
import { type DisplayCurrency, formatMoney, toFaDigits } from "@/lib/format";
import { qtyUnits } from "@/lib/qty";
import { cn } from "@/lib/utils";

const PAGE = 48;

/**
 * Touch catalogue for the register: categories as large chips, products as tiles with
 * photo, name and list price. A tap adds one (the server still prices the sale); a weighed
 * item asks for its weight. The count already in the cart sits on the tile.
 */
export function PosCatalog({
  currency,
  inCart,
  onPick,
  className,
}: {
  currency: DisplayCurrency;
  inCart: Record<string, string>;
  onPick: (p: Picked & { weighted: boolean }, via: "touch" | "mouse") => void;
  className?: string;
}) {
  const groups = useGroups();
  const [group, setGroup] = React.useState<string>(() => {
    try {
      return localStorage.getItem("nc.pos.group") ?? "";
    } catch {
      return "";
    }
  });
  const [pages, setPages] = React.useState(1);
  const [flash, setFlash] = React.useState<string | null>(null);
  const choose = (id: string) => {
    setGroup(id);
    setPages(1);
    try {
      localStorage.setItem("nc.pos.group", id);
    } catch {
      /* private window: not remembered */
    }
  };
  const params = new URLSearchParams({ page: "1", page_size: String(Math.min(PAGE * pages, 200)), active: "true" });
  if (group) params.set("group_id", group);
  const items = useQuery({
    queryKey: ["inventory", "items", "pos", params.toString()],
    queryFn: () => api.get<Page<ItemSummary>>(`/inventory/items?${params}`),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
  const list = items.data?.items ?? [];
  const chip = (active: boolean) =>
    cn(
      "h-11 shrink-0 snap-start rounded-xl px-4 text-sm font-semibold transition active:scale-95",
      active ? "bg-brand-600 text-white shadow-sm" : "bg-black/[0.04] text-ink hover:bg-brand-500/10 dark:bg-white/5",
    );
  return (
    <section aria-label="کالاها بر اساس دسته" className={cn("surface flex min-h-0 flex-col rounded-2xl", className)}>
      <div className="flex snap-x gap-2 overflow-x-auto border-b border-[var(--line)] p-2 [scrollbar-width:thin]" role="tablist" aria-label="دسته‌بندی‌ها">
        <button type="button" role="tab" aria-selected={!group} className={chip(!group)} onClick={() => choose("")}>
          <LayoutGrid className="me-1 inline size-4" /> همه
        </button>
        {groups.data?.map((g) => (
          <button key={g.id} type="button" role="tab" aria-selected={group === g.id} className={chip(group === g.id)} onClick={() => choose(g.id)}>
            {g.name}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {items.isLoading ? (
          <Spinner />
        ) : items.isError ? (
          <div className="flex flex-col items-center gap-2 p-8 text-center text-sm text-ink-soft">
            <WifiOff className="size-6" />
            فهرست کالاها بدون اتصال به سرور در دسترس نیست؛ کالا را اسکن یا جست‌وجو کنید.
          </div>
        ) : !list.length ? (
          <p className="p-8 text-center text-sm text-ink-soft">در این دسته کالایی نیست.</p>
        ) : (
          <>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(7.75rem,1fr))] gap-2">
              {list.map((it) => {
                const count = inCart[it.id];
                const out = qtyUnits(it.stock_qty) <= 0n;
                return (
                  <button
                    key={it.id}
                    type="button"
                    onPointerUp={(e) => {
                      if (e.button !== 0) return;
                      setFlash(it.id);
                      window.setTimeout(() => setFlash((f) => (f === it.id ? null : f)), 350);
                      onPick({ item_id: it.id, code: it.code, name: it.name, weighted: it.is_weighted }, e.pointerType === "touch" ? "touch" : "mouse");
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onPick({ item_id: it.id, code: it.code, name: it.name, weighted: it.is_weighted }, "mouse");
                      }
                    }}
                    aria-label={`${it.name}${it.price ? `، ${formatMoney(it.price, currency)}` : ""}${count ? `، ${toFaDigits(trimQty(count))} در سبد` : ""}`}
                    className={cn(
                      "group relative flex flex-col overflow-hidden rounded-xl bg-[var(--surface)] text-start ring-1 ring-[var(--line)] transition select-none",
                      "hover:ring-brand-500/50 active:scale-[0.97]",
                      flash === it.id && "ring-2 ring-brand-500",
                      out && "opacity-60",
                    )}
                  >
                    <div className="relative aspect-[4/3] w-full bg-black/[0.03] dark:bg-white/5">
                      {it.image_id ? (
                        <img src={imageUrl(it.image_id)} alt="" loading="lazy" draggable={false} className="size-full object-cover" />
                      ) : (
                        <div className="flex size-full items-center justify-center text-ink-faint">
                          <ImageOff className="size-6" />
                        </div>
                      )}
                      {count ? (
                        <span className="tabular absolute top-1 left-1 min-w-7 rounded-full bg-brand-600 px-2 py-0.5 text-center text-xs font-bold text-white shadow">
                          {toFaDigits(trimQty(count))}
                        </span>
                      ) : null}
                      {it.is_weighted ? (
                        <span className="absolute top-1 right-1 inline-flex items-center gap-0.5 rounded-full bg-white/90 px-1.5 py-0.5 text-[10px] font-semibold text-ink dark:bg-black/60">
                          <Scale className="size-3" /> وزنی
                        </span>
                      ) : null}
                    </div>
                    <div className="flex flex-1 flex-col gap-0.5 p-2">
                      <span className="line-clamp-2 text-sm leading-5 font-medium text-ink">{it.name}</span>
                      <span className="mt-auto flex items-center justify-between gap-1">
                        <span className="tabular text-sm font-bold text-brand-700 dark:text-brand-300">
                          {it.price ? formatMoney(it.price, currency) : "بدون قیمت"}
                        </span>
                        {out ? (
                          <span className="inline-flex items-center gap-0.5 text-[10px] text-danger">
                            <PackageX className="size-3" /> ناموجود
                          </span>
                        ) : null}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
            {items.data && items.data.total > list.length && list.length < 200 ? (
              <button type="button" className="mt-2 h-11 w-full rounded-xl bg-black/[0.04] text-sm font-semibold text-ink hover:bg-brand-500/10 dark:bg-white/5" onClick={() => setPages((p) => p + 1)}>
                کالاهای بیشتر ({toFaDigits(items.data.total - list.length)})
              </button>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}
