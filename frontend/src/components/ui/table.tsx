import { ChevronLeft, ChevronRight } from "lucide-react";
import type * as React from "react";
import { toFaDigits } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "./button";

export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="overflow-x-auto">
      <table className={cn("w-full min-w-[44rem] border-collapse text-sm", className)} {...props} />
    </div>
  );
}

export function Th({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        "border-b border-[var(--line)] px-4 py-3 text-start text-xs font-semibold whitespace-nowrap text-ink-faint",
        className,
      )}
      {...props}
    />
  );
}

export function Td({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td className={cn("border-b border-[var(--line)] px-4 py-3 align-middle", className)} {...props} />
  );
}

export function Tr({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn("transition-colors hover:bg-brand-500/[0.04] last:[&>td]:border-b-0", className)}
      {...props}
    />
  );
}

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between gap-3 border-t border-[var(--line)] px-4 py-3 text-sm text-ink-faint">
      <span>
        {toFaDigits(total)} مورد · صفحه {toFaDigits(page)} از {toFaDigits(pages)}
      </span>
      <div className="flex gap-1">
        <Button
          variant="ghost"
          size="icon"
          aria-label="صفحه قبل"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
        >
          <ChevronRight />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="صفحه بعد"
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
        >
          <ChevronLeft />
        </Button>
      </div>
    </div>
  );
}
