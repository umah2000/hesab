import * as React from "react";
import { cn } from "@/lib/utils";

export function Card({
  className,
  variant = "glass",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { variant?: "glass" | "surface" }) {
  return (
    <div
      className={cn(
        "rounded-2xl",
        variant === "glass" ? "glass" : "surface shadow-sm",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({
  title,
  description,
  actions,
  icon,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-3 p-5 pb-3", className)}>
      <div className="flex items-center gap-3">
        {icon ? (
          <div className="grid size-10 place-items-center rounded-xl bg-brand-500/10 text-brand-600 dark:text-brand-300">
            {icon}
          </div>
        ) : null}
        <div>
          <h2 className="text-base font-bold text-ink">{title}</h2>
          {description ? <p className="mt-0.5 text-sm text-ink-faint">{description}</p> : null}
        </div>
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function CardBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5 pt-2", className)} {...props} />;
}
